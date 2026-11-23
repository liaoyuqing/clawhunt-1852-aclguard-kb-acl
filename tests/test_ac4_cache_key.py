"""AC4：单元测试断言缓存键包含角色与 site 指纹。"""
from __future__ import annotations

from aclguard.cache_key import TTLCache, cache_key, role_fingerprint, site_fingerprint
from aclguard.iam_stub import load_roles


def test_acl4_cache_key_contains_role_and_site_fingerprint():
    principals = load_roles()
    front = principals["front"]
    key = cache_key("qa", front, "入馆流程总览的具体要求是什么？")
    assert role_fingerprint(front) in key
    assert site_fingerprint(front) in key
    assert key.startswith("qa:")
    # 键形状 qa:role_fp:site_fp:subject_fp:scope_fp:query_fp —— 5 个冒号切 6 段。
    # （旧形状 4 段/3 冒号不含 subject 与 scope，同角色他人或 scope 收缩后会误命中。）
    assert key.count(":") == 5


def test_acl4_different_role_and_site_never_share_key():
    principals = load_roles()
    question = "入馆流程总览的具体要求是什么？"
    keys = {key: cache_key("qa", p, question) for key, p in principals.items()}
    assert len(set(keys.values())) == len(keys)

    front_key = cache_key("qa", principals["front"], question)
    front_other_site = cache_key("qa", principals["front"].__class__(
        subject_id="u-front-01", display_name="前台", roles=frozenset({"front_desk"}),
        site_id="site-sh-02", data_scope=frozenset({"kb_core", "kb_front"}),
    ), question)
    assert front_key != front_other_site


def test_acl4_cache_written_by_one_role_is_invisible_to_another():
    principals = load_roles()
    question = "招商线索分配规则的具体要求是什么？"
    cache = TTLCache()
    cache.set(cache_key("qa", principals["sales"], question), {"answer": "sales-only"})
    assert cache.get(cache_key("qa", principals["sales"], question)) == {"answer": "sales-only"}
    assert cache.get(cache_key("qa", principals["sales_lead"], question)) is None
    assert cache.get(cache_key("qa", principals["front"], question)) is None
    assert cache.misses == 2