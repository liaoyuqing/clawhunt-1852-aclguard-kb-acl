"""返修 2 轮（买家 3 条）：缓存键跨主体隔离、visible_citations_only 主链路接线、AC2 分母精确断言。

三条都按买家的原文逐条钉成可证伪的回归断言：
1. 同角色、同馆、不同 subject_id 的两个人共用一个缓存实例时，confidential 条目不得串到无权一方；
2. `visible_citations_only` 必须经 `ask()` 主链路产出「下一轮可复用引用」，角色被收回后该集合剔除该 doc_id；
3. AC2 的断言次数必须等于各角色无权条目数之和（1992），不能再用几乎恒真的表达式。
"""
from __future__ import annotations

import json

from aclguard.assistant import RecordingModelClient, Session, ask
from aclguard.cache_key import TTLCache, cache_key
from aclguard.history import FOLD_MARKER
from aclguard.iam_stub import load_roles
from aclguard.kb_stub import LeakyKnowledgeBase, load_entries
from aclguard.leak import run_leak_suite
from aclguard.models import Principal

AC3_DOC_ID = "doc-013"  # role_limited，仅 sales_rep 可见
CONFIDENTIAL_DOC_ID = "doc-034"  # confidential，allowed_subject_ids = (u-fin-05,)


def _same_role_and_site_principals():
    """同角色、同馆、同数据域的两个人：可见集只差在 confidential 的主体白名单上。"""
    allowed = Principal(
        subject_id="u-fin-05",
        display_name="财务（白名单内）",
        roles=frozenset({"finance"}),
        site_id="site-hz-01",
        data_scope=frozenset({"kb_core", "kb_fin"}),
    )
    denied = Principal(
        subject_id="u-fin-06",
        display_name="财务（白名单外）",
        roles=frozenset({"finance"}),
        site_id="site-hz-01",
        data_scope=frozenset({"kb_core", "kb_fin"}),
    )
    return allowed, denied


def test_rework_cache_key_covers_subject_so_confidential_does_not_leak_between_principals():
    """买家 1（blocker）：共享缓存实例下，confidential 条目不得串给同角色但无权的一方。"""
    allowed, denied = _same_role_and_site_principals()
    assert allowed.roles == denied.roles
    assert allowed.site_id == denied.site_id
    assert allowed.data_scope == denied.data_scope
    assert allowed.subject_id != denied.subject_id

    entry = next(e for e in load_entries() if e.doc_id == CONFIDENTIAL_DOC_ID)
    assert entry.visibility_label == "confidential"
    assert entry.allowed_subject_ids == ("u-fin-05",)
    kb = LeakyKnowledgeBase([entry])
    question = entry.title + " 的具体数值是多少？"
    cache = TTLCache()

    warm_model = RecordingModelClient()
    warm = ask(Session(session_id="rework-cache-allowed"), question, allowed, kb, warm_model,
               cache=cache, request_id="rework-cache-1")
    assert warm["cached"] is False
    assert CONFIDENTIAL_DOC_ID in warm["citations"], "白名单内的人必须能拿到该条目"
    assert len(cache) == 1, "同一问题只应写入一条缓存"

    # 键必须不同：同角色同馆同 scope，只差 subject_id。
    assert cache_key("qa", allowed, question) != cache_key("qa", denied, question)

    cold_model = RecordingModelClient()
    cold = ask(Session(session_id="rework-cache-denied"), question, denied, kb, cold_model,
               cache=cache, request_id="rework-cache-2")

    # 核心断言：无权一方的回答与引用里不出现该 confidential 条目的标题与原文。
    assert entry.title not in cold["answer"]
    assert entry.body[:40] not in cold["answer"]
    assert CONFIDENTIAL_DOC_ID not in cold["citations"]
    assert CONFIDENTIAL_DOC_ID in cold["dropped"]
    assert cold["cache"]["served"] is False
    assert cold["served_from_cache_despite_now_denied"] is False

    surface = json.dumps(
        {
            "answer": cold["answer"],
            "citations": cold["citations"],
            "context": cold_model.last_request.chunks,
            "history": cold_model.last_request.history,
        },
        ensure_ascii=False,
    )
    assert entry.title not in surface
    assert entry.body[:40] not in surface


def test_rework_confidential_title_absent_from_denied_side_after_shared_cache_reuse():
    """同一缓存实例被两个人轮流命中：无权一方拿到的仍是自己的（不含该条目的）结果。"""
    allowed, denied = _same_role_and_site_principals()
    entry = next(e for e in load_entries() if e.doc_id == CONFIDENTIAL_DOC_ID)
    kb = LeakyKnowledgeBase([entry])
    question = entry.title + " 的结论是什么？"
    cache = TTLCache()

    for round_no in range(2):
        ask(Session(session_id="rework-loop-a-%d" % round_no), question, allowed, kb,
            RecordingModelClient(), cache=cache, request_id="rework-loop-a-%d" % round_no)
        model = RecordingModelClient()
        result = ask(Session(session_id="rework-loop-b-%d" % round_no), question, denied, kb,
                     model, cache=cache, request_id="rework-loop-b-%d" % round_no)
        # 第二轮的 denied 一方命中的是**自己那把键**（无水印条目），命中后不再发模型请求。
        context = model.last_request.chunks if model.last_request is not None else []
        blob = json.dumps(
            {"answer": result["answer"], "citations": result["citations"], "context": context},
            ensure_ascii=False,
        )
        assert entry.title not in blob
        assert entry.body[:40] not in blob
        assert CONFIDENTIAL_DOC_ID not in result["citations"]


def test_rework_visible_citations_only_wired_through_ask_main_chain():
    """买家 2（minor）：可复用引用必须由 ask() 主链路产出，并随当前权限变化。"""
    principals = load_roles()
    sales = principals["sales"]
    entries = load_entries()
    target = next(e for e in entries if e.doc_id == AC3_DOC_ID)
    kb = LeakyKnowledgeBase(entries)
    session = Session(session_id="rework-reuse")
    question = target.title + " 的具体要求是什么？"

    first = ask(session, question, sales, kb, RecordingModelClient(), cache=None, request_id="rework-reuse-1")
    assert AC3_DOC_ID in first["citations"]
    # 首轮之前会话为空，可复用集合必为空（不是把本轮结果算进去）。
    assert first["reusable_citation_doc_ids"] == []

    second_model = RecordingModelClient()
    second = ask(session, question, sales, kb, second_model, cache=None, request_id="rework-reuse-2")
    # 可复用集合 = 上一轮全部可见引用的 doc_id（不止目标那一条）。
    assert AC3_DOC_ID in second["reusable_citation_doc_ids"]
    assert set(second["reusable_citation_doc_ids"]) == set(first["citations"])
    assert second_model.last_request.reusable_citations == second["reusable_citation_doc_ids"]
    assert second_model.last_request.as_dict()["reusable_citations"] == second["reusable_citation_doc_ids"]

    # 角色被收回：同一份会话，可复用集合里不再有该 doc_id，历史也被折叠。
    revoked = sales.without_roles(["sales_rep"])
    third_model = RecordingModelClient()
    third = ask(session, question, revoked, kb, third_model, cache=None, request_id="rework-reuse-3")
    # 角色被收回：该 doc_id 必须从可复用集合里消失，其它仍可见的引用保留下来。
    assert AC3_DOC_ID not in third["reusable_citation_doc_ids"]
    assert set(third["reusable_citation_doc_ids"]) == set(second["reusable_citation_doc_ids"]) - {AC3_DOC_ID}
    assert third_model.last_request.reusable_citations == third["reusable_citation_doc_ids"]
    assert AC3_DOC_ID not in third["citations"]
    assert AC3_DOC_ID in third["dropped"]
    # 只检查助手侧：用户自己的提问里本来就带着标题，那不是泄露面。
    history = third_model.last_request.history
    assert history, "模型请求体必须带折叠后的历史"
    assistant_blob = json.dumps([m for m in history if m["role"] == "assistant"], ensure_ascii=False)
    assert FOLD_MARKER in assistant_blob
    assert target.title not in assistant_blob
    assert target.body[:40] not in assistant_blob
    folded_refs = [c for m in history for c in m["citations"] if c["doc_id"] == AC3_DOC_ID]
    assert folded_refs, "被收回的引用仍要以折叠形态留在历史里，供审计追溯"
    assert all(c["folded"] is True for c in folded_refs)


def test_rework_ac2_checks_equal_exact_sum_of_denied_entries_per_role():
    """买家 3（minor）：断言次数必须精确等于各角色无权条目数之和（1992），不能近似。"""
    run = run_leak_suite()
    per_role_checks = {key: bucket["checks"] for key, bucket in run.per_role.items()}
    assert per_role_checks == {
        "front": 445,
        "community": 429,
        "sales": 415,
        "sales_lead": 331,
        "finance": 372,
    }
    assert sum(per_role_checks.values()) == 1992
    assert run.checks == 1992
    assert run.skipped_by_acl == 9108
    assert run.cells_total == 11100
    assert run.checks + run.skipped_by_acl == run.cells_total
    assert run.dropped_total == run.checks
    assert run.hits == 0
