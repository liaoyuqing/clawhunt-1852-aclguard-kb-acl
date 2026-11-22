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


def secret_scan() -> dict:
    hits = []
    for file in sorted(ROOT.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(ROOT).as_posix()
        if rel.startswith(".venv/") or "__pycache__" in rel or rel.endswith(".pyc"):
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
    }


def tree_digest() -> str:
    digest = hashlib.sha256()
    for file in sorted(ROOT.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(ROOT).as_posix()
        if rel.startswith(".venv/") or "__pycache__" in rel or rel.endswith(".pyc"):
            continue
        if rel == "metrics.json":
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(file.read_bytes())
    return digest.hexdigest()


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
    payload["secret_scan"] = secret_scan()
    payload["tree_sha256"] = tree_digest()
    (ROOT / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["pytest_exit"] == 0 and payload["leak_hits"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())