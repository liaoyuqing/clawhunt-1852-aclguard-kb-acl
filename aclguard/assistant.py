"""助手主链路：检索 -> 二次校验 -> 历史折叠 -> 拼模型请求 -> 出答案与引用 -> 写缓存。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .audit import EVENT_CACHE_REVOKED, format_audit_line, get_audit_logger
from .cache_key import TTLCache, cache_key
from .history import render_history
from .models import Chunk, CitationRef, Principal
from .second_check import describe_for_model, filter_chunks


@dataclass
class ModelRequest:
    """交给模型的请求体快照：只有二次校验放行的片段与已折叠的历史能进来。"""

    question: str
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    # 已按当前权限折叠过的历史轮次；引用不可见者 title/snippet 已换成折叠标记。
    history: List[Dict[str, Any]] = field(default_factory=list)
    folded_count: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {"question": self.question, "context": self.chunks, "history": self.history}


@dataclass(frozen=True)
class _CachedCitation:
    """把缓存里的引用快照包成 filter_chunks 认得的片段形状，复用同一套重判逻辑。

    visibility.decide 同时接受 KnowledgeEntry 与 CitationRef（字段一致），
    因此这里把 CitationRef 直接当作 entry 传入，不必重新加载知识库。
    """

    citation: CitationRef

    @property
    def doc_id(self) -> str:
        return self.citation.doc_id

    @property
    def entry(self) -> CitationRef:
        return self.citation

    @property
    def visibility_label(self) -> str:
        return self.citation.visibility_label


class RecordingModelClient:
    """模型客户端桩：记录最后一次请求体，回答里只回引用可见片段的标题。"""

    def __init__(self) -> None:
        self.requests: List[ModelRequest] = []

    @property
    def last_request(self) -> Optional[ModelRequest]:
        return self.requests[-1] if self.requests else None

    def complete(self, request: ModelRequest) -> Dict[str, Any]:
        self.requests.append(request)
        cited = [c["doc_id"] for c in request.chunks[:2]]
        answer = " ".join(c["title"] for c in request.chunks[:2]) or "no_visible_context"
        return {"answer": answer, "cited_doc_ids": cited}


@dataclass
class Session:
    """一个会话：历史消息里带着引用快照，供后续轮次重新判定。"""

    session_id: str
    messages: List[Dict[str, Any]] = field(default_factory=list)

    def append(self, role: str, text: str, citations: Tuple[CitationRef, ...] = ()) -> None:
        self.messages.append({
            "role": role,
            "text": text,
            "citations": [c.to_dict() for c in citations],
        })


def citation_of(chunk: Chunk) -> CitationRef:
    return CitationRef(
        doc_id=chunk.doc_id,
        title=chunk.title,
        snippet=chunk.text[:40],
        visibility_label=chunk.visibility_label,
        module=chunk.module,
        allowed_roles=chunk.allowed_roles,
        site_id=chunk.site_id,
        allowed_subject_ids=chunk.allowed_subject_ids,
    )


def recheck_cached(payload: Mapping[str, Any], principal: Principal, log, request_id: str,
                  current_entries: Optional[Mapping[str, Any]] = None):
    """缓存命中后仍按当前权限重判引用；返回（重判结果, 被撤销的 doc_id 列表）。

    优先用知识库的**现行**条目重判：条目在写缓存后被重新密级化时，
    缓存里的旧引用快照仍带旧标签，只按快照重判会漏过去。取不到现行条目
    才退回快照（此时缺失标签按 fail closed 处理）。
    """
    raw = payload.get("citations") or []
    configs = [CitationRef.from_dict(c) for c in raw if isinstance(c, Mapping)]
    if not configs:
        return None, []
    rebuilt = []
    for citation in configs:
        entry = (current_entries or {}).get(citation.doc_id)
        if entry is not None:
            rebuilt.append(Chunk.from_entry(entry))
        else:
            rebuilt.append(_CachedCitation(citation))
    result = filter_chunks(rebuilt, principal, log, request_id=request_id)
    revoked = list(result.dropped_doc_ids)
    if revoked:
        fields = {
            "doc_id": revoked[0],
            "reason": result.dropped[0].reason,
            "request_id": request_id,
        }
        log.info(format_audit_line(EVENT_CACHE_REVOKED, fields))
    return result, revoked


def ask(
    session: Session,
    question: str,
    principal: Principal,
    kb: Any,
    model: RecordingModelClient,
    cache: Optional[TTLCache] = None,
    logger: Optional[logging.Logger] = None,
    request_id: str = "req-0",
) -> Dict[str, Any]:
    """一次问答。缓存命中也要重判，历史引用按当前权限折叠。"""
    log = get_audit_logger(logger)
    key = cache_key("qa", principal, question)
    current_entries = kb.entry_map() if hasattr(kb, "entry_map") else None
    dropped_ids: List[str] = []
    cache_hit = False
    cache_revoked = False
    served_from_cache = False

    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            cache_hit = True
            _, revoked = recheck_cached(hit, principal, log, request_id,
                                        current_entries=current_entries)
            if revoked:
                # 条目在写入缓存后被重新密级化 / 角色被收回：旧答案必须作废。
                cache_revoked = True
                dropped_ids.extend(revoked)
                cache.invalidate(key)
            else:
                served_from_cache = True
                return {
                    "cached": True,
                    "cache_key": key,
                    "answer": hit.get("answer", ""),
                    "citations": [c.get("doc_id") for c in (hit.get("citations") or [])],
                    "dropped": [],
                    "model_context_doc_ids": [],
                    "request_id": request_id,
                    "cache": {"hit": True, "served": True, "revoked": False},
                    "served_from_cache_despite_now_denied": False,
                }

    chunks = kb.search(question)
    result = filter_chunks(chunks, principal, log, request_id=request_id)
    dropped_ids.extend(d.doc_id for d in result.dropped)

    # 历史折叠接线：用当前 principal 重判历史引用，折叠后的结果才进模型上下文。
    history, folded_count = render_history(session.messages, principal)
    request = ModelRequest(
        question=question,
        chunks=describe_for_model(result.visible_chunks),
        history=history,
        folded_count=folded_count,
    )
    reply = model.complete(request)

    allowed = {c.doc_id for c in result.visible_chunks}
    citations = [citation_of(c) for c in result.visible_chunks if c.doc_id in allowed]
    session.append("user", question)
    session.append("assistant", reply["answer"], tuple(citations))

    payload = {"answer": reply["answer"], "citations": [c.to_dict() for c in citations]}
    if cache is not None:
        cache.set(key, payload)
    return {
        "cached": False,
        "cache_key": key,
        "answer": reply["answer"],
        "citations": [c.doc_id for c in citations],
        "dropped": dropped_ids,
        "model_context_doc_ids": [c["doc_id"] for c in request.chunks],
        "request_id": request_id,
        "folded_count": folded_count,
        "cache": {"hit": cache_hit, "served": served_from_cache, "revoked": cache_revoked},
        "served_from_cache_despite_now_denied": bool(served_from_cache and cache_revoked),
    }
