"""返修新增：把审计发现的 9 处缺口逐条钉成回归断言。

每个用例都对应一处「改坏实现后必须变红」的可证伪点，见 FIX_REVIEW.md 的变异自证表。
"""
from __future__ import annotations

import json
import logging
import re

import pytest

from aclguard.assistant import RecordingModelClient, Session, ask
from aclguard.audit import EVENT_DROPPED, LOGGER_NAME, format_audit_line
from aclguard.cache_key import (
    TTLCache,
    cache_key,
    role_fingerprint,
    scope_fingerprint,
    site_fingerprint,
    subject_fingerprint,
)
from aclguard.history import FOLD_MARKER, render_history
from aclguard.iam_stub import load_roles
from aclguard.kb_stub import LeakyKnowledgeBase, load_entries
from aclguard.leak import run_leak_suite, scan_surface, scan_text
from aclguard.models import CitationRef, KnowledgeEntry, Principal
from aclguard.visibility import decide

DOC_SALES = "doc-013"  # role_limited，仅 sales_rep


class CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        # 只取 getMessage()：默认 handler 渲染的就是这一段，能在这里检索到才算真可检索。
        self.lines.append(record.getMessage())


def _logger():
    logger = logging.getLogger("aclguard.test.repair")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False
    handler = CollectingHandler()
    logger.addHandler(handler)
    return logger, handler


def _entries():
    return load_entries()


def _ask_sales(session, question, principal, logger, request_id, cache=None):
    kb = LeakyKnowledgeBase(_entries())
    model = RecordingModelClient()
    result = ask(session, question, principal, kb, model, cache=cache, logger=logger, request_id=request_id)
    return result, model


# ---------------------------------------------------------------- 1. AC3 接线

def test_repair_history_folding_is_wired_into_model_request():
    """折叠必须接进 ask() 的上下文构造路径，而不只是存在一个没被调用的函数。"""
    logger, _ = _logger()
    principals = load_roles()
    sales = principals["sales"]
    entries = _entries()
    target = next(e for e in entries if e.doc_id == DOC_SALES)

    session = Session(session_id="repair-fold")
    first, _ = _ask_sales(session, target.title + " 的要求是什么？", sales, logger, "repair-1")
    assert first["citations"], "首轮必须产生引用，否则后续折叠无从谈起"

    revoked = sales.without_roles(["sales_rep"])
    second, model = _ask_sales(session, target.title + " 还有哪几条？", revoked, logger, "repair-2")

    # 模型请求体里的折叠后历史：助手侧产物（助手轮次文本 + 引用项）里
    # 原 title 与 body[:40] 都不能出现。用户自己的提问轮次不在统计面内，
    # 与 AC2 的口径一致（提问里本来就带着被问条目）。
    request = model.last_request
    assert request is not None
    assert request.history, "模型请求体必须带折叠后的历史，证明折叠真的接线了"
    assistant_turns = [m for m in request.history if m.get("role") == "assistant"]
    citations = [c for m in request.history for c in m.get("citations") or []]
    blob = json.dumps(assistant_turns, ensure_ascii=False) + json.dumps(citations, ensure_ascii=False)
    assert target.title not in blob
    assert target.body[:40] not in blob
    assert FOLD_MARKER in blob
    assert request.folded_count >= 1
    # ask() 的返回值同样带折叠计数，便于上层观测。
    assert second["folded_count"] >= 1


def test_repair_render_history_leaves_no_original_text_when_role_revoked():
    """折叠后的整份历史里不得残留被召回条目的标题与正文片段。"""
    principals = load_roles()
    sales = principals["sales"]
    entries = _entries()
    target = next(e for e in entries if e.doc_id == DOC_SALES)
    logger, _ = _logger()
    session = Session(session_id="repair-render")
    _ask_sales(session, target.title + " 的要求是什么？", sales, logger, "repair-3")

    rendered, folded = render_history(session.messages, sales.without_roles(["sales_rep"]))
    assistant_turns = [m for m in rendered if m.get("role") == "assistant"]
    citations = [c for m in rendered for c in m.get("citations") or []]
    blob = json.dumps(assistant_turns, ensure_ascii=False) + json.dumps(citations, ensure_ascii=False)
    assert folded >= 1
    assert target.title not in blob
    assert target.body[:40] not in blob
    # 对照：角色未收回时同一份历史必须仍能看到该条目，证明折叠由当前权限决定。
    kept, folded_kept = render_history(session.messages, sales)
    kept_blob = json.dumps([m for m in kept if m.get("role") == "assistant"], ensure_ascii=False)
    assert folded_kept == 0
    assert target.title in kept_blob


# ------------------------------------------------- 2. 缓存命中不得绕过二次校验

def test_repair_cache_hit_rechecks_and_does_not_serve_reclassified_entry():
    """条目在写入缓存后被重新密级化：键不变（同人同角色同 scope），

    但命中后必须按知识库的现行条目重判，旧答案不得返回。
    """
    import dataclasses

    logger, _ = _logger()
    principals = load_roles()
    sales = principals["sales"]
    entries = _entries()
    target = next(e for e in entries if e.doc_id == DOC_SALES)
    cache = TTLCache()
    question = target.title + " 的要求是什么？"

    session_a = Session(session_id="repair-cache-a")
    warm, _ = _ask_sales(session_a, question, sales, logger, "repair-cache-1", cache=cache)
    assert warm["citations"], "预热必须产生可缓存的引用"
    assert warm["cached"] is False

    # 同一个人、同一角色、同一 scope —— 缓存键一个字都不变；
    # 变的是知识库里这条目的密级：role_limited -> confidential（只放行 u-lead-04）。
    reclassified = [
        dataclasses.replace(e, visibility_label="confidential", allowed_roles=())
        if e.doc_id == target.doc_id else e
        for e in entries
    ]
    kb = LeakyKnowledgeBase(reclassified)
    model = RecordingModelClient()
    session_b = Session(session_id="repair-cache-b")
    cold = ask(session_b, question, sales, kb, model, cache=cache, logger=logger,
               request_id="repair-cache-2")

    assert cold["cache"]["hit"] is True, "同键必须命中，否则这个用例测不到重判"
    assert cold["served_from_cache_despite_now_denied"] is False
    assert target.doc_id not in cold["citations"]
    assert target.doc_id in cold["dropped"], "重判不通过必须记进 dropped"
    assert cold["cache"]["revoked"] is True, "旧缓存必须被作废"


def test_repair_role_revocation_changes_key_so_stale_entry_never_hits():
    """角色被收回会改变 role_fp，键随之改变：旧答案连命中机会都不该有。"""

    logger, _ = _logger()
    principals = load_roles()
    sales = principals["sales"]
    question = "招商线索分配规则的具体要求是什么？"
    cache = TTLCache()
    first, _ = _ask_sales(Session(session_id="repair-rk-a"), question, sales, logger, "repair-rk-1", cache=cache)
    assert first["cached"] is False

    revoked = sales.without_roles(["sales_rep"])
    assert cache_key("qa", revoked, question) != cache_key("qa", sales, question)
    second, _ = _ask_sales(Session(session_id="repair-rk-b"), question, revoked, logger, "repair-rk-2", cache=cache)
    assert second["cache"]["hit"] is False
    assert second["served_from_cache_despite_now_denied"] is False


def test_repair_cache_hit_still_serves_when_entry_remains_visible():
    """反向控制：条目仍可见时，缓存命中应正常走缓存，不被误杀。"""
    logger, _ = _logger()
    principals = load_roles()
    front = principals["front"]
    question = "入馆流程总览的具体要求是什么？"
    cache = TTLCache()
    first, _ = _ask_sales(Session(session_id="repair-hit-a"), question, front, logger, "repair-hit-1", cache=cache)
    second, model = _ask_sales(Session(session_id="repair-hit-b"), question, front, logger, "repair-hit-2", cache=cache)
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["served_from_cache_despite_now_denied"] is False
    assert second["cache"]["revoked"] is False
    # 命中确实短路了检索：没有新的模型请求被记录。
    assert model.last_request is None


# --------------------------------------- 3. 缓存键必须覆盖 subject 与 data_scope

def test_repair_cache_key_covers_subject_and_scope():
    principals = load_roles()
    sales = principals["sales"]
    question = "招商线索分配规则的具体要求是什么？"
    key = cache_key("qa", sales, question)

    assert subject_fingerprint(sales) in key
    assert scope_fingerprint(sales) in key
    assert role_fingerprint(sales) in key
    assert site_fingerprint(sales) in key
    assert key.count(":") == 5
    assert len(key.split(":")) == 6

    # 同角色、同馆、同 scope，但换一个人：键必须不同。
    other_person = Principal(
        subject_id="u-sales-99",
        display_name="招商业务员（另一人）",
        roles=frozenset(sales.roles),
        site_id=sales.site_id,
        data_scope=frozenset(sales.data_scope),
    )
    assert cache_key("qa", other_person, question) != key

    # 同一个人，但 data_scope 被收缩：键必须不同。
    narrowed = Principal(
        subject_id=sales.subject_id,
        display_name=sales.display_name,
        roles=frozenset(sales.roles),
        site_id=sales.site_id,
        data_scope=frozenset({"kb_core"}),
    )
    assert cache_key("qa", narrowed, question) != key


def test_repair_cache_does_not_leak_across_subject_or_scope():
    """功能侧：同角色他人 / scope 收缩后都不得命中同一条缓存。"""
    principals = load_roles()
    sales = principals["sales"]
    question = "招商线索分配规则的具体要求是什么？"
    cache = TTLCache()
    cache.set(cache_key("qa", sales, question), {"answer": "sales-only", "citations": []})

    other_person = Principal(
        subject_id="u-sales-99",
        display_name="招商业务员（另一人）",
        roles=frozenset(sales.roles),
        site_id=sales.site_id,
        data_scope=frozenset(sales.data_scope),
    )
    assert cache.get(cache_key("qa", other_person, question)) is None

    narrowed = Principal(
        subject_id=sales.subject_id,
        display_name=sales.display_name,
        roles=frozenset(sales.roles),
        site_id=sales.site_id,
        data_scope=frozenset({"kb_core"}),
    )
    assert cache.get(cache_key("qa", narrowed, question)) is None


# ---------------------------------------------- 4. 审计事件必须可被日志文本检索

def test_repair_audit_event_is_greppable_in_formatted_line():
    logger, handler = _logger()
    principals = load_roles()
    sales = principals["sales"]
    entries = _entries()
    target = next(e for e in entries if e.doc_id == DOC_SALES)
    session = Session(session_id="repair-audit")
    _ask_sales(session, "欠款清单与入馆流程", sales, logger, "repair-audit-1")

    lines = [line for line in handler.lines if line.startswith(EVENT_DROPPED)]
    assert lines, "kb_acl_dropped 必须以可渲染的日志行出现"
    line = lines[0]
    # 用正则从纯文本里抽字段：这模仿运维 grep，而不是从 LogRecord 对象里读。
    match = re.search(r"doc_id=(\S+).*reason=(\S+).*role_fp=(\S+).*site_fp=(\S+).*request_id=(\S+)", line)
    assert match, "doc_id / reason / role_fp / site_fp / request_id 必须都在行文本里: %r" % line
    assert match.group(1)
    assert match.group(2) in {
        "label_all_staff", "role_hit", "role_miss", "site_hit", "site_miss",
        "principal_allow", "principal_deny", "confidential_default_deny",
        "scope_miss", "label_unknown",
    }
    assert len(match.group(3)) == 16
    assert len(match.group(4)) == 16
    assert match.group(5) == "repair-audit-1"


def test_repair_single_logger_name_across_modules():
    """assistant 与 second_check 必须共用同一个审计 logger 名，不能分裂。"""
    from aclguard import assistant, second_check

    assert LOGGER_NAME == "aclguard.audit"
    assert second_check.DEFAULT_LOGGER_NAME == LOGGER_NAME
    # assistant 里不再硬编码另一个 logger 名。
    source = open(assistant.__file__, encoding="utf-8").read()
    assert "aclguard.assistant" not in source


def test_repair_default_logger_emits_to_caplog(caplog):
    """不注入 logger 时，默认 handler 也必须能拿到这条审计行。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    principals = load_roles()
    sales = principals["sales"]
    session = Session(session_id="repair-caplog")
    kb = LeakyKnowledgeBase(_entries())
    ask(session, "欠款清单", sales, kb, RecordingModelClient(), cache=None, request_id="repair-caplog-1")
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == LOGGER_NAME)
    assert "kb_acl_dropped" in text
    assert "request_id=repair-caplog-1" in text


# ------------------------------------------------- 5. 检测器本身必须有正控

def test_repair_detector_positive_control_catches_real_leak():
    """把泄露内容真的塞进产物，检测器必须命中 —— 证明 scan_text 不是恒 False。"""
    entries = _entries()
    target = next(e for e in entries if e.doc_id == DOC_SALES)
    assert scan_text("无关内容", target) is False
    assert scan_text("前缀 " + target.title + " 后缀", target) is True
    assert scan_text("前缀 " + target.body[:40] + " 后缀", target) is True

    principals = load_roles()
    sales = principals["sales"]
    revoked = sales.without_roles(["sales_rep"])
    model = RecordingModelClient()

    class _FakeRequest:
        chunks = [{"doc_id": target.doc_id, "title": target.title, "text": target.body[:200]}]
        history = []

    model.requests.append(_FakeRequest())
    surface = scan_surface({"answer": target.title}, [], model)
    assert scan_text(surface, target) is True


def test_repair_leak_suite_excludes_idle_cells_from_denominator():
    """分母只算真的被检索到并拦下的格；空转格单列，不能混进 checks。"""
    run = run_leak_suite()
    assert run.questions == 100
    assert run.principals == 5
    assert run.checks > 0
    assert run.checks + run.skipped_by_acl == run.cells_total
    # 全表逐条遍历的候选格是 11100；实际扫描远小于它，差额就是空转。
    assert run.cells_total == 11100
    assert run.skipped_by_acl > 0
    assert run.checks < 11100
    assert run.hits == 0
    # 每个被计数的格都必须真的被检索到过：checks 等于丢弃总数。
    assert run.checks == run.dropped_total


# ------------------------------------------------ 6. request_id 必须能对上号

def test_repair_request_id_matches_between_dropped_events_and_return():
    logger, handler = _logger()
    principals = load_roles()
    sales = principals["sales"]
    session = Session(session_id="repair-reqid")
    result, _ = _ask_sales(session, "欠款清单与入馆流程", sales, logger, "repair-reqid-42")

    assert result["request_id"] == "repair-reqid-42"
    dropped_lines = [l for l in handler.lines if l.startswith(EVENT_DROPPED)]
    assert dropped_lines
    event_ids = {re.search(r"request_id=(\S+)", l).group(1) for l in dropped_lines}
    assert event_ids == {result["request_id"]}


# --------------------------------------------- 7. CitationRef 缺失标签必须默认拒绝

def test_repair_citation_ref_default_label_fails_closed():
    principals = load_roles()
    front = principals["front"]
    # 旧快照缺 visibility_label：默认值不能是 all_staff，否则等于默认放行。
    ref = CitationRef.from_dict({"doc_id": "doc-legacy", "title": "历史引用", "snippet": "片段"})
    assert ref.visibility_label == ""
    decision = decide(ref, front)
    assert decision.visible is False
    assert decision.reason == "label_unknown"


def test_repair_citation_ref_without_label_folds_in_history():
    """缺标签的旧引用渲染历史时必须被折叠掉，而不是原样露出。"""
    principals = load_roles()
    front = principals["front"]
    messages = [{"role": "assistant", "text": "历史引用 片段", "citations": [
        {"doc_id": "doc-legacy", "title": "历史引用", "snippet": "片段"},
    ]}]
    rendered, folded = render_history(messages, front)
    assert folded == 1
    assert FOLD_MARKER in json.dumps(rendered, ensure_ascii=False)
    assert "历史引用" not in json.dumps(rendered, ensure_ascii=False)


# --------------------------------------------------- 8. tree_sha256 不得含 .git

def test_repair_tree_digest_ignores_git_directory():
    """同一份工作树，无论 .git 在不在，摘要都必须一致。"""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("collect_metrics", root / "scripts" / "collect_metrics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert ".git/" in module.SKIP_DIRS
    assert module._skipped(".git/HEAD") is True
    assert module._skipped(".git/objects/ab/cdef") is True
    assert module._skipped("aclguard/assistant.py") is False
    assert module._skipped("metrics.json") is False
    # 行尾归一：CRLF 与 LF 是同一份内容，摘要不能因为平台换行习惯而不同。
    assert module.normalize_eol(b"a\r\nb\r\n") == b"a\nb\n"
    assert module.normalize_eol(b"a\nb\n") == b"a\nb\n"


# ---------------------------------------------------------------- 9. 文档口径

def test_repair_ac_matrix_states_real_case_count():
    """ac_matrix.md 里的用例数必须与实际收集数一致（旧文写 51 例、实际 40 条夹具）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    text = (root / "reports" / "ac_matrix.md").read_text(encoding="utf-8")
    assert "51 例" not in text
    assert "40 例" in text