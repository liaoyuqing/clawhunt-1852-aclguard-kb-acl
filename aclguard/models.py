"""数据模型：知识条目、权限主体、检索片段、判定结果、引用与会话。

字段命名与工单约定一致；全部使用虚构数据，不含任何真实企业或个人信息。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Tuple

# 四种可见性标签，取值为封闭集合
VISIBILITY_LABELS = ("all_staff", "role_limited", "site_limited", "confidential")

# 历史折叠标记：不可见引用在渲染历史时被替换成这一段文字
FOLDED_TEXT = "「该内容已无权查看」"

# 判定理由枚举（reason 的稳定取值）
REASON_LABEL_ALL_STAFF = "label_all_staff"
REASON_ROLE_HIT = "role_hit"
REASON_ROLE_MISS = "role_miss"
REASON_SITE_HIT = "site_hit"
REASON_SITE_MISS = "site_miss"
REASON_PRINCIPAL_ALLOW = "principal_allow"
REASON_PRINCIPAL_DENY = "principal_deny"
REASON_CONFIDENTIAL_DEFAULT_DENY = "confidential_default_deny"
REASON_SCOPE_MISS = "scope_miss"
REASON_LABEL_UNKNOWN = "label_unknown"


@dataclass(frozen=True)
class KnowledgeEntry:
    """一条知识条目，携带可见性标签与授权条件。"""

    doc_id: str
    title: str
    body: str
    visibility_label: str
    allowed_roles: Tuple[str, ...] = ()
    site_id: Any = None
    allowed_subject_ids: Tuple[str, ...] = ()
    module: str = "kb_core"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "KnowledgeEntry":
        return cls(
            doc_id=raw["doc_id"],
            title=raw["title"],
            body=raw["body"],
            visibility_label=raw["visibility_label"],
            allowed_roles=tuple(raw.get("allowed_roles") or ()),
            site_id=raw.get("site_id"),
            allowed_subject_ids=tuple(raw.get("allowed_subject_ids") or ()),
            module=raw.get("module", "kb_core"),
        )


@dataclass(frozen=True)
class Principal:
    """IAM 快照：当前用户的主体、角色集合、馆与数据域。"""

    subject_id: str
    display_name: str
    roles: frozenset
    site_id: str
    data_scope: frozenset

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Principal":
        return cls(
            subject_id=raw["subject_id"],
            display_name=raw["display_name"],
            roles=frozenset(raw.get("roles") or ()),
            site_id=raw["site_id"],
            data_scope=frozenset(raw.get("data_scope") or ()),
        )

    def without_roles(self, roles) -> "Principal":
        """返回移除若干角色后的新主体：模拟会话中途角色被收回。"""
        drop = set(roles)
        return Principal(
            subject_id=self.subject_id,
            display_name=self.display_name,
            roles=frozenset(r for r in self.roles if r not in drop),
            site_id=self.site_id,
            data_scope=self.data_scope,
        )


@dataclass(frozen=True)
class CitationRef:
    """引用快照：随历史消息一起保存，用于后续按当前权限重新判定。"""

    doc_id: str
    title: str
    snippet: str = ""
    # 默认空串而不是 all_staff：缺失标签的引用必须落到 label_unknown 被拒绝（fail closed），
    # 否则旧快照缺字段时会默认放行，等于给历史消息开后门。
    visibility_label: str = ""
    module: str = "kb_core"
    allowed_roles: Tuple[str, ...] = ()
    site_id: Any = None
    allowed_subject_ids: Tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CitationRef":
        return cls(
            doc_id=raw["doc_id"],
            title=raw.get("title", ""),
            snippet=raw.get("snippet", ""),
            visibility_label=raw.get("visibility_label", ""),
            module=raw.get("module", "kb_core"),
            allowed_roles=tuple(raw.get("allowed_roles") or ()),
            site_id=raw.get("site_id"),
            allowed_subject_ids=tuple(raw.get("allowed_subject_ids") or ()),
        )

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "snippet": self.snippet,
            "visibility_label": self.visibility_label,
            "module": self.module,
            "allowed_roles": list(self.allowed_roles),
            "site_id": self.site_id,
            "allowed_subject_ids": list(self.allowed_subject_ids),
        }


@dataclass(frozen=True)
class Chunk:
    """知识库检索返回的片段（可能未按可见性过滤）。"""

    doc_id: str
    title: str
    text: str
    visibility_label: str
    module: str
    allowed_roles: Tuple[str, ...]
    site_id: Any
    allowed_subject_ids: Tuple[str, ...]
    entry: KnowledgeEntry

    @classmethod
    def from_entry(cls, entry: KnowledgeEntry) -> "Chunk":
        return cls(
            doc_id=entry.doc_id,
            title=entry.title,
            text=entry.body,
            visibility_label=entry.visibility_label,
            module=entry.module,
            allowed_roles=entry.allowed_roles,
            site_id=entry.site_id,
            allowed_subject_ids=entry.allowed_subject_ids,
            entry=entry,
        )


@dataclass(frozen=True)
class Decision:
    """一次可见性判定的结果。"""

    visible: bool
    reason: str
    matched_by: str = ""


@dataclass(frozen=True)
class DroppedChunk:
    """被丢弃片段的最小审计信息：只有 doc_id / reason / matched_by，不含标题与正文。"""

    doc_id: str
    reason: str
    matched_by: str = ""


@dataclass
class SecondCheckResult:
    visible_chunks: list = field(default_factory=list)
    dropped: list = field(default_factory=list)

    @property
    def dropped_doc_ids(self) -> Tuple[str, ...]:
        return tuple(d.doc_id for d in self.dropped)

    @property
    def visible_doc_ids(self) -> Tuple[str, ...]:
        return tuple(c.doc_id for c in self.visible_chunks)
