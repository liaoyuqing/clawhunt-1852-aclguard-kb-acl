"""会话历史：角色被收回后，历史里的引用要折叠成不可查看。"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Tuple

from .models import CitationRef, Principal
from .visibility import decide

FOLD_MARKER = "「该内容已无权查看」"


def fold_citation(ref: CitationRef, principal: Principal) -> Mapping[str, Any]:
    """单条引用：可见则原样，不可见则标题与片段一起折叠。"""
    d = decide(ref, principal)
    if d.visible:
        return {"doc_id": ref.doc_id, "title": ref.title, "snippet": ref.snippet, "folded": False}
    return {"doc_id": ref.doc_id, "title": FOLD_MARKER, "snippet": FOLD_MARKER, "folded": True}


def render_history(messages: Iterable[Mapping[str, Any]], principal: Principal) -> Tuple[list, int]:
    """渲染整个会话：返回（渲染后的消息列表, 折叠次数）。"""
    out = []
    folded_count = 0
    for msg in messages:
        citations = [fold_citation(CitationRef.from_dict(c), principal) for c in msg.get("citations", ())]
        folded_count += sum(1 for c in citations if c["folded"])
        text = str(msg.get("text", ""))
        for c in msg.get("citations", ()):
            ref = CitationRef.from_dict(c)
            if decide(ref, principal).visible:
                continue
            if ref.title:
                text = text.replace(ref.title, FOLD_MARKER)
            if ref.snippet:
                text = text.replace(ref.snippet, FOLD_MARKER)
        out.append({
            "role": msg.get("role", "assistant"),
            "text": text,
            "citations": citations,
        })
    return out, folded_count


def visible_citations_only(messages: Iterable[Mapping[str, Any]], principal: Principal) -> Tuple[CitationRef, ...]:
    """下一轮允许复用的引用：只保留当前仍可见的那些。"""
    kept = []
    for msg in messages:
        for c in msg.get("citations", ()):
            ref = CitationRef.from_dict(c)
            if decide(ref, principal).visible:
                kept.append(ref)
    return tuple(kept)