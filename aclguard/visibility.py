"""可见性判定：对每个片段独立重算，防止知识库侧过滤失效导致越权。

判定顺序（fail closed）：
1. data_scope 不含该条目 module -> scope_miss，直接拒绝；
2. all_staff -> 全员可见；
3. role_limited -> allowed_roles 与 principal.roles 有交集；
4. site_limited -> entry.site_id 等于 principal.site_id；
5. confidential -> 仅允许 subject_id 在 allowed_subject_ids 中，默认拒绝。
"""
from __future__ import annotations

from .models import (
    REASON_CONFIDENTIAL_DEFAULT_DENY,
    REASON_LABEL_ALL_STAFF,
    REASON_LABEL_UNKNOWN,
    REASON_PRINCIPAL_ALLOW,
    REASON_PRINCIPAL_DENY,
    REASON_ROLE_HIT,
    REASON_ROLE_MISS,
    REASON_SCOPE_MISS,
    REASON_SITE_HIT,
    REASON_SITE_MISS,
    Decision,
    KnowledgeEntry,
    Principal,
)


def decide(entry, principal: Principal) -> Decision:
    """返回该条目对该主体是否可见及判定理由。

    entry 可以是 KnowledgeEntry，也可以是历史里的 CitationRef：两者字段一致。
    """
    module = getattr(entry, "module", "kb_core")
    if module not in principal.data_scope:
        return Decision(False, REASON_SCOPE_MISS, "module:" + str(module))

    label = getattr(entry, "visibility_label", "")
    if label == "all_staff":
        return Decision(True, REASON_LABEL_ALL_STAFF, "label:all_staff")

    if label == "role_limited":
        allowed = set(getattr(entry, "allowed_roles", ()) or ())
        hit = sorted(allowed & set(principal.roles))
        if hit:
            return Decision(True, REASON_ROLE_HIT, ",".join(hit))
        return Decision(False, REASON_ROLE_MISS, "roles:" + ",".join(sorted(principal.roles)))

    if label == "site_limited":
        entry_site = getattr(entry, "site_id", None)
        if entry_site is not None and entry_site == principal.site_id:
            return Decision(True, REASON_SITE_HIT, "site:" + principal.site_id)
        return Decision(False, REASON_SITE_MISS, "site:" + str(entry_site))

    if label == "confidential":
        allowed_subjects = set(getattr(entry, "allowed_subject_ids", ()) or ())
        if not allowed_subjects:
            return Decision(False, REASON_CONFIDENTIAL_DEFAULT_DENY, "no_allowed_subject")
        if principal.subject_id in allowed_subjects:
            return Decision(True, REASON_PRINCIPAL_ALLOW, "subject:" + principal.subject_id)
        return Decision(False, REASON_PRINCIPAL_DENY, "subject:" + principal.subject_id)

    return Decision(False, REASON_LABEL_UNKNOWN, "label:" + str(label))


def is_visible(entry, principal: Principal) -> bool:
    return decide(entry, principal).visible
