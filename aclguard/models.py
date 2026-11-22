"""数据模型：知识条目、权限主体、检索片段、判定结果、引用与会话。

字段命名与工单约定一致；全部使用虚构数据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VISIBILITY_LABELS = ("all_staff", "role_limited", "site_limited", "confidential")

FOLDED_TEXT = "「该内容已无权查看」"

REASON_LABEL_ALL_STAFF = "label_all_staff"
REASON_ROLE_HIT = "role_hit"
REASON_ROLE_MISS = "role_miss"
REASON_SITE_HIT = "site_hit"
REASON_SITE_MISS = "site_miss"
REASON_PRINCIPAL_ALLOW = "principal_allow"
REASON_PRINCIPAL_DENY = "principal_deny"
REASON_CONFIDENTIAL_DEFAULT_DENY = "confidential_default_deny"
REASON_SCOPE_MISS = "scope_miss"
REASON_UNKNOWN_LABEL = "unknown_label"
REASON_UNKNOWN_DOC = "unknown_doc"


@dataclass(frozen=True)
class KnowledgeEntry:
    """一条知识条目，携带可见性标签与授权条件。"""

    doc_id: str
    title: str
    body: str
    visibility_label: str
    allowed_roles: tuple = ()
    site_id: str | None = None
    allowed_subject_ids: tuple = ()
    module: str = "kb"

    @classmethod
    def from_dict(cls, raw: dict) -> "KnowledgeEntry":
        return cls(
            doc_id=raw["doc_id"],
            title=raw["title"],
            body=raw["body"],
            visibility_label=raw["visibility_label"],
            allowed_roles=tuple(raw.get("allowed_roles") or ()),
            site_id=raw.get("site_id"),
            allowed_subject_ids=tuple(raw.get("allowed_subject_ids") or ()),
            module=raw.get("module", "kb"),
        )

    @property
    def body_prefix(self) -> str:
        return self.body[:40]


@dataclass(frozen=True)
class Principal:
    """IAM 快照：当前用户的主体、角色集合、site 与数据域。"""

    subject_id: str
    display_name: str
    roles: frozenset
    site_id: str
    data_scope: frozenset

    @classmethod
    def from_dict(cls, raw: dict) -> "Principal":
        return cls(
            subject_id=raw["subject_id"],
            display_name=raw["display_name"],
            roles=frozenset(raw.get("roles") or ()),
            site_id=raw["site_id"],
            data_scope=frozenset(raw.get("data_scope") or ()),
        )

    def without_role(self, role: str) -> "Principal":
        """返回移除某个角色后的新主体，用于模拟角色被收回。"""
        return Principal(
            subject_id=self.subject_id,
            display_name=self.display_name,
            roles=frozenset(r for r in self.roles if r != role),
            site_id=self.site_id,
            data_scope=self.data_scope,
        )


@dataclass(frozen=True)
class Chunk:
    """知识库检索返回的片段（可能未按可见性过滤）。"""

    doc_id: str
    title: str
    body: str
    score: float
    entry: KnowledgeEntry

    @classmethod
    def from_entry(cls, entry: KnowledgeEntry, score: float = 0.0) -> "Chunk":
        return cls(doc_id=entry.doc_id, title=entry.title, body=entry.body, score=score, entry=entry)


@dataclass(frozen=True)
class Decision:
    """一次可见性判定的结果。"""

    visible: bool
    reason: str
    matched_by: str = ""


@dataclass(frozen=True)
class DroppedChunk:
    """被丢弃片段的最小审计信息，不含标题与正文。"""

    doc_id: str
    reason: str
    matched_by: str = ""


@dataclass
class SecondCheckResult:
    visible_chunks: list = field(default_factory=list)
    dropped: list = field(default_factory=list)

    @property
    def visible_doc_ids(self) -> list:
        return [c.doc_id for c in self.visible_chunks]


@dataclass(frozen=True)
class Citation:
    doc_id: str
    title: str
    snippet: str = ""


@dataclass
class Answer:
    text: str
    citations: list = field(default_factory=list)


@dataclass
class HistoryMessage:
    role: str
    text: str
    citations: list = field(default_factory=list)


@dataclass
class Session:
    session_id: str
    messages: list = field(default_factory=list)
    kb: Any = None

    def append(self, role: str, text: str, citations=None) -> None:
        self.messages.append(HistoryMessage(role=role, text=text, citations=list(citations or [])))


@dataclass
class AskResult:
    request_id: str
    answer: Answer
    visible_doc_ids: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    request_body: dict = field(default_factory=dict)
    cache_hit: bool = False
