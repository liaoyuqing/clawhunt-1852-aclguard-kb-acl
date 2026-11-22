"""现算交付指标：所有数字都来自真实执行，不手写。"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "aclguard"
TESTS = ROOT / "tests"
FIXTURES = ROOT / "fixtures"
REPORTS = ROOT / "reports"
# 模式本身由片段拼出来，避免扫描脚本自己变成「命中项」。
SECRET_PATTERNS = ("cp" + "h_", "gh" + "o_", "github_" + "pat_", "s" + "k-", "AK" + "IA")


def run_pytest() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = [line for line in proc.stdout.strip().splitlines() if line.strip()][-1:]
    return {
        "pytest_exit": proc.returncode,
        "pytest_last_line": tail[0] if tail else "",
        "pytest_stdout_sha256": hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest(),
    }


def count_cases() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    ids = [line for line in proc.stdout.splitlines() if "::" in line]
    return len(ids)


def loc(path: Path) -> int:
    total = 0
    for file in sorted(path.rglob("*.py")):
        total += sum(1 for line in file.read_text(encoding="utf-8").splitlines() if line.strip())
    return total


def fixture_counts() -> dict:
    roles = json.loads((FIXTURES / "roles.json").read_text(encoding="utf-8"))["roles"]
    entries = json.loads((FIXTURES / "knowledge_40.json").read_text(encoding="utf-8"))["entries"]
    questions = json.loads((FIXTURES / "questions_100.json").read_text(encoding="utf-8"))["questions"]
    labels = {}
    for e in entries:
        labels[e["visibility_label"]] = labels.get(e["visibility_label"], 0) + 1
    return {
        "roles": len(roles),
        "entries": len(entries),
        "questions": len(questions),
        "labels": dict(sorted(labels.items())),
        "sites": len({r["site_id"] for r in roles}),
    }


# 不参与扫描与摘要的目录：虚拟环境、字节码缓存、pytest 缓存（后者每次跑测试都会变）
SKIP_DIRS = (".venv/", ".pytest_cache/", "__pycache__/")


def _skipped(rel: str) -> bool:
    if rel.endswith(".pyc") or "__pycache__" in rel:
        return True
    return any(rel.startswith(d) or ("/" + d) in rel for d in SKIP_DIRS)


def secret_scan() -> dict:
    hits = []
    for file in sorted(ROOT.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(ROOT).as_posix()
        if _skipped(rel):
            continue
        if rel == "metrics.json":
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern in text:
                hits.append({"file": rel, "pattern": pattern})
    return {"scanned": len(SECRET_PATTERNS), "hits": hits, "hit_count": len(hits)}


def leak_metrics() -> dict:
    sys.path.insert(0, str(ROOT))
    from aclguard.leak import run_leak_suite, to_report

    logging.getLogger("aclguard.leak").setLevel(logging.WARNING)
    REPORTS.mkdir(parents=True, exist_ok=True)
    run = run_leak_suite()
    to_report(run, REPORTS / "leak_test_report.md")
    return {
        "leak_questions": run.questions,
        "leak_principals": run.principals,
        "leak_checks": run.checks,
        "leak_hits": run.hits,
        "leak_pass_rate": run.pass_rate,
        "leak_positive_citations": run.positive_citations,
        "leak_dropped_total": run.dropped_total,
        "leak_per_role": run.per_role,
    }


def fold_metrics() -> dict:
    """把 AC3 的「角色被收回」场景真跑一遍，数折叠标记出现的次数。"""
    sys.path.insert(0, str(ROOT))
    from aclguard.assistant import RecordingModelClient, Session, ask
    from aclguard.history import FOLD_MARKER, render_history
    from aclguard.iam_stub import load_roles
    from aclguard.kb_stub import LeakyKnowledgeBase, load_entries

    principals = load_roles()
    sales = principals["sales"]
    entries = load_entries()
    kb = LeakyKnowledgeBase(entries)
    session = Session(session_id="metrics-fold")
    target = next(e for e in entries if e.doc_id == "doc-013")
    ask(session, target.title + " 的具体要求是什么？", sales, kb, RecordingModelClient(),
        cache=None, request_id="metrics-fold")
    rendered_revoked, folded = render_history(session.messages, sales.without_roles(["sales_rep"]))
    rendered_kept, folded_kept = render_history(session.messages, sales)
    blob = json.dumps(rendered_revoked, ensure_ascii=False)
    return {
        "fold_marker": FOLD_MARKER,
        "fold_marker_count": blob.count(FOLD_MARKER),
        "fold_citations": folded,
        "fold_marker_count_when_role_kept": json.dumps(rendered_kept, ensure_ascii=False).count(FOLD_MARKER),
        "fold_citations_when_role_kept": folded_kept,
    }


def tree_digest() -> str:
    digest = hashlib.sha256()
    for file in sorted(ROOT.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(ROOT).as_posix()
        if _skipped(rel):
            continue
        if rel == "metrics.json":
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(file.read_bytes())
    return digest.hexdigest()


def metrics_block(payload: dict) -> str:
    """渲染 README 里那段实测数字，保证正文与 metrics.json 永远同源。"""
    fx = payload["fixtures"]
    labels = fx["labels"]
    return "\n".join([
        # 末行里的耗时每次都不同，正文只写「用例数 + 退出码」，逐字末行以 metrics.json 为准，
        # 这样 README 不会因为几毫秒的抖动而每跑一次都变，tree_sha256 才有可比性。
        "- Python `%s`；`pytest -q` 结果 `%s`，退出码 `%s`（逐字末行与耗时见 `metrics.json`）" % (
            payload["python"], payload["pytest_last_line"].split(" in ")[0], payload["pytest_exit"]),
        "- 测试文件 `%d` 个、用例 `%d` 个；包内 `%d` 个 `.py`、有效代码行 `%d`；测试有效代码行 `%d`" % (
            payload["test_files"], payload["test_cases"], payload["package_py_files"],
            payload["package_loc"], payload["tests_loc"]),
        "- 夹具：角色 `%d`、知识 `%d`（`all_staff` %d / `role_limited` %d / `site_limited` %d / `confidential` %d）、问题 `%d`、馆 `%d`" % (
            fx["roles"], fx["entries"], labels.get("all_staff", 0), labels.get("role_limited", 0),
            labels.get("site_limited", 0), labels.get("confidential", 0), fx["questions"], fx["sites"]),
        "- 泄露测试：断言 `%d` 次、命中 `%d`、通过率 `%s`、正控引用 `%d` 次、被判丢弃片段累计 `%d` 次" % (
            payload["leak_checks"], payload["leak_hits"], payload["leak_pass_rate"],
            payload["leak_positive_citations"], payload["leak_dropped_total"]),
        "- 折叠标记 `%s` 在角色被收回的渲染结果中出现 `%d` 次（折叠引用 `%d` 条），角色未收回时 `%d` 次" % (
            payload["fold_marker"], payload["fold_marker_count"], payload["fold_citations"],
            payload["fold_marker_count_when_role_kept"]),
        "- 密钥扫描命中 `%d` 条（模式组 `%d` 个）" % (
            payload["secret_scan"]["hit_count"], payload["secret_scan"]["scanned"]),
    ])


def sync_readme(payload: dict) -> None:
    """把实测数字写回 README 的标记区间，避免正文与快照漂移。"""
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    begin, end = "<!-- METRICS:BEGIN -->", "<!-- METRICS:END -->"
    if begin not in text or end not in text:
        return
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    path.write_text(head + begin + "\n" + metrics_block(payload) + "\n" + end + tail, encoding="utf-8")


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "test_files": len(sorted(TESTS.glob("test_*.py"))),
        "test_cases": count_cases(),
        "package_py_files": len(sorted(PKG.glob("*.py"))),
        "package_loc": loc(PKG),
        "tests_loc": loc(TESTS),
        "fixtures": fixture_counts(),
    }
    payload.update(run_pytest())
    payload.update(leak_metrics())
    payload.update(fold_metrics())
    scan = secret_scan()
    payload["secret_scan"] = scan
    payload["secret_scan_hits"] = scan["hit_count"]
    # 先回填 README，再算目录摘要：否则摘要反映的是「上一轮」的 README，永远对不上最终文件。
    sync_readme(payload)
    payload["tree_sha256"] = tree_digest()
    (ROOT / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["pytest_exit"] == 0 and payload["leak_hits"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())