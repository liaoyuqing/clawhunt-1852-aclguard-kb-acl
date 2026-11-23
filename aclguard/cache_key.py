"""缓存键与带 TTL 的内存缓存。

键结构：kind:role_fp:site_fp:query_fp，角色与 site 指纹必须同时出现。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from .models import Principal


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def role_fingerprint(principal: Principal) -> str:
    """角色指纹：排序后的角色集合做 sha256，取前 16 位十六进制。"""
    return _sha16("|".join(sorted(principal.roles)))


def site_fingerprint(principal: Principal) -> str:
    """site 指纹：site_id 做 sha256，取前 16 位十六进制。"""
    return _sha16(principal.site_id)


def subject_fingerprint(principal: Principal) -> str:
    """主体指纹：同角色不代表同一个人，subject_id 必须参与键。"""
    return _sha16(principal.subject_id)


def scope_fingerprint(principal: Principal) -> str:
    """数据域指纹：scope 收缩后必须换键，否则会读到收缩前的旧答案。"""
    return _sha16("|".join(sorted(principal.data_scope)))


def cache_key(kind: str, principal: Principal, query: str) -> str:
    """构造缓存键：kind:role_fp:site_fp:subject_fp:scope_fp:query_fp（6 段）。

    角色、馆、主体、数据域四者共同决定可见集合，任一变化都必须换键。
    """
    return ":".join([
        kind,
        role_fingerprint(principal),
        site_fingerprint(principal),
        subject_fingerprint(principal),
        scope_fingerprint(principal),
        _sha16(query),
    ])


class TTLCache:
    """极简 TTL 缓存；不同指纹天然落在不同键上，跨角色读取必然 miss。"""

    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 512) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._data: dict = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any:
        item = self._data.get(key)
        if item is None:
            self.misses += 1
            return None
        value, expires = item
        if expires <= time.monotonic():
            self._data.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        now = time.monotonic()
        ttl = self.ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        self._data[key] = (value, now + ttl)
        while len(self._data) > self.max_entries:
            oldest = min(self._data.items(), key=lambda kv: kv[1][1])[0]
            self._data.pop(oldest, None)

    def invalidate(self, key: str) -> bool:
        """作废单个键；返回是否确实删除了一条。用于缓存命中但重判不通过时的撤回。"""
        return self._data.pop(key, None) is not None

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
