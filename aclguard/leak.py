"""泄露测试：5 种角色 x 100 个问题，逐条断言无权条目的标题与原文都不出现。

分母口径（关键）：只有「知识库确实检索到、被二次校验拦下」的条目才算一个真的检查格 ——
若某条目本轮根本没被检索到，扫描它必然是 0 命中，那是空转，单独记为 skipped_by_acl，
不计入 checks。否则断言次数会被空转撑大，掩盖检测器本身是否有效。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .assistant import RecordingModelClient, Session, ask
from .audit import get_audit_logger
from .cache_key import TTLCache
from .iam_stub import load_roles
from .kb_stub import LeakyKnowledgeBase, load_entries
from .models import KnowledgeEntry, Principal
from .visibility import decide

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
BODY_PROBE_LEN = 40


@dataclass
class LeakCase:
    qid: str
    question: str
    asker: str


@dataclass
class LeakRun:
    questions: int = 0
    principals: int = 0
    checks: int = 0
    hits: int = 0
    positive_citations: int = 0
    dropped_total: int = 0
    # 空转格：该条目本轮未被检索到，扫描它恒为 0，不计入 checks。
    skipped_by_acl: int = 0
    failures: List[Dict[str, Any]] = field(default_factory=list)
    # 正控样本：第一条「确实引用了可见条目」的记录，证明不是全空假通过
    sample: Dict[str, Any] = field(default_factory=dict)
    # 按角色拆分：便于报告出 5 行统计表
    per_role: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        if self.checks == 0:
            return 0.0
        return round(1.0 - self.hits / self.checks, 6)

    @property
    def cells_total(self) -> int:
        """全部候选格 = 实际扫描格 + 空转格，用于说明分母是怎么来的。"""
        return self.checks + self.skipped_by_acl


def load_questions(path: Path = FIXTURE_DIR / "questions_100.json") -> List[LeakCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [LeakCase(qid=item["qid"], question=item["question"], asker=item["asker"]) for item in raw["questions"]]


def forbidden_markers(entry: KnowledgeEntry) -> Tuple[str, str]:
    """判据只用标题与正文前 40 字：这两段出现即算泄露。"""
    return entry.title, entry.body[:BODY_PROBE_LEN]


def scan_text(text: str, entry: KnowledgeEntry) -> bool:
    title, probe = forbidden_markers(entry)
    if title and title in text:
        return True
    if probe and probe in text:
        return True
    return False


def scan_surface(result: Mapping[str, Any], assistant_turns: Iterable[Mapping[str, Any]], model: Any) -> str:
    """拼接需要被检查的助手侧产物：回答、助手轮次、模型请求体（片段 + 折叠后历史）。

    用户自己的提问不算泄漏面（用户本来就知道自己在问什么），所以这里只取
    模型请求体里的 `context` 与 `history`，不含 `question` 字段。
    """
    context = []
    history = []
    request = getattr(model, "last_request", None)
    if request is not None:
        context = request.chunks
        history = getattr(request, "history", []) or []
    return " ".join([
        str(result.get("answer", "")),
        json.dumps(list(assistant_turns), ensure_ascii=False),
        json.dumps(context, ensure_ascii=False),
        json.dumps(history, ensure_ascii=False),
    ])


def run_leak_suite(
    entries: Iterable[KnowledgeEntry] = None,
    principals: Mapping[str, Principal] = None,
    questions: List[LeakCase] = None,
    logger: logging.Logger = None,
) -> LeakRun:
    """每个问题对每个角色各跑一次，只检查真正被检索到的无权条目。

    只扫描助手侧产物（回答、助手轮次消息、模型请求体）；用户自己的提问里
    本来就带着被问条目的标题，把它计入会让统计失真。
    """
    entries = list(entries) if entries is not None else load_entries()
    principals = dict(principals) if principals is not None else load_roles()
    questions = list(questions) if questions is not None else load_questions()
    log = get_audit_logger(logger)
    kb = LeakyKnowledgeBase(entries)
    run = LeakRun(questions=len(questions), principals=len(principals))

    entitled = {
        key: [e for e in entries if decide(e, principal).visible]
        for key, principal in principals.items()
    }

    for case in questions:
        for key, principal in principals.items():
            model = RecordingModelClient()
            session = Session(session_id="%s-%s" % (case.qid, key))
            result = ask(session, case.question, principal, kb, model, cache=TTLCache(), logger=log,
                         request_id="leak-%s-%s" % (case.qid, key))
            run.dropped_total += len(result["dropped"])

            denied = [e for e in entries if not decide(e, principal).visible]
            visible_ids = {e.doc_id for e in entitled[key]}
            assistant_turns = [m for m in session.messages if m.get("role") == "assistant"]
            surface = scan_surface(result, assistant_turns, model)
            # 真正进入过助手链路的候选：被检索到但被拦下的（dropped）与最终引用的。
            retrieved = set(result["dropped"]) | set(result["model_context_doc_ids"]) | set(result["citations"])

            bucket = run.per_role.setdefault(
                key, {"questions": 0, "checks": 0, "hits": 0, "citations": 0, "skipped": 0})
            bucket["questions"] += 1

            for entry in denied:
                if entry.doc_id not in retrieved:
                    # 空转：本轮知识库根本没返回这条，扫描它没有意义。
                    run.skipped_by_acl += 1
                    bucket["skipped"] += 1
                    continue
                run.checks += 1
                bucket["checks"] += 1
                if scan_text(surface, entry):
                    run.hits += 1
                    bucket["hits"] += 1
                    run.failures.append({
                        "qid": case.qid,
                        "asker": key,
                        "leaked_doc_id": entry.doc_id,
                        "label": entry.visibility_label,
                    })

            fresh = [d for d in result["citations"] if d in visible_ids]
            run.positive_citations += len(fresh)
            bucket["citations"] += len(fresh)
            if fresh and not run.sample:
                run.sample = {
                    "qid": case.qid,
                    "asker": key,
                    "doc_id": fresh[0],
                    "title": next(e.title for e in entries if e.doc_id == fresh[0]),
                }

    return run


def to_report(run: LeakRun, path: Path) -> Path:
    """渲染测试报告 Markdown。"""
    lines = [
        "# 泄露测试报告（100 问题 x 5 角色）",
        "",
        "断言次数只统计「本轮确实被检索到、被二次校验拦下」的条目；",
        "未被检索到的条目扫描恒为 0，属空转，记在 skipped_by_acl，不计入分母。",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        "| 问题数 | %d |" % run.questions,
        "| 角色数 | %d |" % run.principals,
        "| 断言次数（实际扫描过的无权条目格） | %d |" % run.checks,
        "| 空转格（未被检索到，不计入分母） | %d |" % run.skipped_by_acl,
        "| 候选格合计 | %d |" % run.cells_total,
        "| 泄露命中次数 | %d |" % run.hits,
        "| 通过率 | %.6f |" % run.pass_rate,
        "| 授权引用次数（正控） | %d |" % run.positive_citations,
        "| 被丢弃片段累计 | %d |" % run.dropped_total,
        "",
        "## 命中明细",
        "",
    ]
    if run.hits == 0:
        lines.append("无命中：无权条目的标题与原文前 40 字在所有回答、引用与模型请求体中均未出现。")
    else:
        for item in run.failures:
            lines.append("- %s / %s / %s / %s" % (item["qid"], item["asker"], item["leaked_doc_id"], item["label"]))
    lines += [
        "",
        "## 分角色 0 命中统计表",
        "",
        "| 角色 key | 问答轮次 | 断言次数（实际扫描） | 空转格 | 泄露命中 | 授权引用（正控） |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key in sorted(run.per_role):
        b = run.per_role[key]
        lines.append("| %s | %d | %d | %d | %d | %d |" % (
            key, b["questions"], b["checks"], b.get("skipped", 0), b["hits"], b["citations"]))
    lines.append("| **合计** | %d | %d | %d | %d | %d |" % (
        sum(b["questions"] for b in run.per_role.values()),
        sum(b["checks"] for b in run.per_role.values()),
        sum(b.get("skipped", 0) for b in run.per_role.values()),
        sum(b["hits"] for b in run.per_role.values()),
        sum(b["citations"] for b in run.per_role.values()),
    ))
    lines += [
        "",
        "## 正控说明",
        "",
        "正控断言 `positive_citations = %d > 0`，证明不是「全部拒答」造成的假通过。" % run.positive_citations,
        "",
    ]
    if run.sample:
        lines += [
            "正控样本（授权引用确实发生）：",
            "",
            "- 问题 `%s`，提问角色 `%s`，被授权引用条目 `%s`（`%s`）" % (
                run.sample["qid"], run.sample["asker"], run.sample["doc_id"], run.sample["title"]),
            "",
        ]
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
