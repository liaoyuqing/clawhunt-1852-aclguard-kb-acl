"""知识库桩：刻意返回越过 ACL 的片段，用来证明助手侧这一道确实拦得住。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Tuple

from .models import Chunk, KnowledgeEntry, Principal

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "knowledge_40.json"


def load_entries(path: Path = FIXTURE) -> List[KnowledgeEntry]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [KnowledgeEntry.from_dict(item) for item in raw["entries"]]


class LeakyKnowledgeBase:
    """最坏情形的桩：完全不做 ACL，按关键词把命中条目整条返回。"""

    def __init__(self, entries: Iterable[KnowledgeEntry]) -> None:
        self._entries = list(entries)
        self.calls = 0

    def search(self, question: str, limit: int = 6) -> Tuple[Chunk, ...]:
        self.calls += 1
        scored = []
        for entry in self._entries:
            score = 0
            for token in (entry.title, entry.body, entry.doc_id):
                if token and token in question:
                    score += 3
            for ch in set(question):
                if ch in entry.title:
                    score += 1
            scored.append((score, entry.doc_id, entry))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        picked = [entry for score, _, entry in scored[:limit]]
        return tuple(Chunk.from_entry(entry) for entry in picked)


def forbidden_for(entry: KnowledgeEntry, principal: Principal) -> bool:
    """测试辅助：这条条目对该主体是否本就无权（用于计算泄漏分母）。"""
    from .visibility import decide
    return not decide(entry, principal).visible