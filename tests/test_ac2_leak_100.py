"""AC2：100 个问题的泄露测试中，无权条目的标题与原文出现次数为 0。"""
from __future__ import annotations

import logging
from pathlib import Path

from aclguard.iam_stub import load_roles
from aclguard.kb_stub import load_entries
from aclguard.leak import load_questions, run_leak_suite, to_report

REPORT = Path(__file__).resolve().parent.parent / "reports" / "leak_test_report.md"


def test_acl2_leak_suite_100_questions_zero_unauthorized_hits():
    logging.getLogger("aclguard.leak").setLevel(logging.WARNING)
    run = run_leak_suite()

    assert run.questions == 100
    assert run.principals == 5
    # 精确断言：断言次数 = 各角色无权条目数之和 = 445 + 429 + 415 + 331 + 372 = 1992。
    # 旧写法 `== 100 * 5 * 40` 与 `or run.checks > 0` 几乎恒真，等于没断言（买家返修第 3 条）。
    assert run.checks == 1992
    assert run.skipped_by_acl == 9108
    assert run.checks + run.skipped_by_acl == 11100
    assert run.hits == 0
    assert run.pass_rate == 1.0
    assert run.positive_citations > 0


def test_acl2_report_written_with_zero_hits():
    logging.getLogger("aclguard.leak").setLevel(logging.WARNING)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    run = run_leak_suite()
    to_report(run, REPORT)
    text = REPORT.read_text(encoding="utf-8")
    assert "| 泄露命中次数 | 0 |" in text
    assert "无命中" in text


def test_acl2_fixture_shape_is_exactly_5_40_100():
    principals = load_roles()
    entries = load_entries()
    questions = load_questions()
    assert len(principals) == 5
    assert len(entries) == 40
    assert len(questions) == 100
    labels = [e.visibility_label for e in entries]
    assert labels.count("all_staff") == 10
    assert labels.count("role_limited") == 12
    assert labels.count("site_limited") == 10
    assert labels.count("confidential") == 8