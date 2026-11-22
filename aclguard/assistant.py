"""助手主链路：检索 -> 二次校验 -> 拼模型请求 -> 出答案与引用 -> 写缓存。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .cache_key import TTLCache, cache_key
from .models import Chunk, CitationRef, Principal
from .second_check import describe_for_model, filter_chunks


@dataclass
class ModelRequest:
    """交给模型的请求体快照：只有二次校验放行的片段能进来。"""

    question: str
    chunks: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"question": self.question, "context": self.chunks}


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
            "citations": [
                {
                    "doc_id": c.doc_id,
                    "title": c.title,
                    "snippet": c.snippet,
                    "visibility_label": c.visibility_label,
                    "module": c.module,
                    "allowed_roles": list(c.allowed_roles),
                    "site_id": c.site_id,
                    "allowed_subject_ids": list(c.allowed_subject_ids),
                }
                for c in citations
            ],
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
    """一次问答。缓存命中时直接返回，键里带角色与 site 指纹。"""
    log = logger or logging.getLogger("aclguard.assistant")
    key = cache_key("qa", principal, question)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return {"cached": True, "cache_key": key, "answer": hit["answer"], "citations": hit["citations"]}

    chunks = kb.search(question)
    result = filter_chunks(chunks, principal, log, request_id=request_id)
    request = ModelRequest(question=question, chunks=describe_for_model(result.visible_chunks))
    reply = model.complete(request)

    allowed = {c.doc_id for c in result.visible_chunks}
    citations = [citation_of(c) for c in result.visible_chunks if c.doc_id in allowed]
    session.append("user", question)
    session.append("assistant", reply["answer"], tuple(citations))

    payload = {"answer": reply["answer"], "citations": [c.doc_id for c in citations]}
    if cache is not None:
        cache.set(key, payload)
    return {
        "cached": False,
        "cache_key": key,
        "answer": reply["answer"],
        "citations": [c.doc_id for c in citations],
        "dropped": [d.doc_id for d in result.dropped],
        "model_context_doc_ids": [c["doc_id"] for c in request.chunks],
    }