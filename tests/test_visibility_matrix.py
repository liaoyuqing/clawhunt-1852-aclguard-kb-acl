"""可见性判定矩阵：4 种 label x 5 个角色 x 2 个馆，逐格断言判定与理由。"""
from __future__ import annotations

import itertools

import pytest

from aclguard.iam_stub import load_roles
from aclguard.models import Principal
from aclguard.visibility import decide


def _entry(**kw):
    from aclguard.models import KnowledgeEntry
    base = dict(doc_id="doc-x", title="t", body="b", visibility_label="all_staff", module="kb_core")
    base.update(kw)
    return KnowledgeEntry(**base)


PRINCIPALS = load_roles()
CASES = list(itertools.product(sorted(PRINCIPALS), ["site-hz-01", "site-sh-02"]))


@pytest.mark.parametrize("role_key,site_id", CASES)
def test_all_staff_visible_for_every_role_and_site(role_key, site_id):
    p = PRINCIPALS[role_key]
    d = decide(_entry(visibility_label="all_staff"), p)
    assert d.visible is True
    assert d.reason == "label_all_staff"


@pytest.mark.parametrize("role_key,site_id", CASES)
def test_role_limited_requires_role_intersection(role_key, site_id):
    p = PRINCIPALS[role_key]
    hit = decide(_entry(visibility_label="role_limited", allowed_roles=("sales_rep",), module="kb_core"), p)
    assert hit.visible is bool({"sales_rep"} & set(p.roles))
    assert hit.reason == ("role_hit" if hit.visible else "role_miss")


@pytest.mark.parametrize("role_key,site_id", CASES)
def test_site_limited_requires_matching_site(role_key, site_id):
    p = PRINCIPALS[role_key]
    d = decide(_entry(visibility_label="site_limited", site_id=site_id), p)
    assert d.visible is (p.site_id == site_id)
    assert d.reason == ("site_hit" if d.visible else "site_miss")


@pytest.mark.parametrize("role_key,site_id", CASES)
def test_confidential_defaults_to_deny(role_key, site_id):
    p = PRINCIPALS[role_key]
    d = decide(_entry(visibility_label="confidential", module="kb_core", allowed_subject_ids=("u-lead-04",)), p)
    assert d.visible is (p.subject_id == "u-lead-04")
    assert d.reason == ("principal_allow" if d.visible else "principal_deny")


@pytest.mark.parametrize("role_key,site_id", CASES)
def test_module_outside_data_scope_is_denied_first(role_key, site_id):
    p = PRINCIPALS[role_key]
    d = decide(_entry(visibility_label="all_staff", module="kb_secret_vault"), p)
    assert d.visible is False
    assert d.reason == "scope_miss"


def test_unknown_label_is_denied():
    p = PRINCIPALS["front"]
    d = decide(_entry(visibility_label="internal_beta"), p)
    assert d.visible is False
    assert d.reason == "label_unknown"