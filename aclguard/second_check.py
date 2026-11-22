"""助手侧二次校验：丢弃不可见片段，且只记录 doc_id 级审计信息。"""
from __future__ import annotations

import logging

from .cache_key import role_fingerprint, site_fingerprint
from .models import DroppedChunk, Principal, SecondCheckResult
from .visibility import decide

EVENT_DROPPED = "kb_acl_dropped"
DEFAULT_LOGGER_NAME = "aclguard.second_check"


def filter_chunks(chunks, principal: Principal, logger=None, request_id: str = "") -> SecondCheckResult:
    """按当前主体逐片段判定，返回可见片段与丢弃清单。

    日志只写 doc_id/reason/matched_by/指纹/request_id，绝不写标题或正文。
    """
    log = logger if logger is not None else logging.getLogger(DEFAULT_LOGGER_NAME)
    role_fp = role_fingerprint(principal)
    site_fp = site_fingerprint(principal)
    result = SecondCheckResult()
    for chunk in chunks:
        decision = decide(chunk.entry, principal)
        if decision.visible:
            result.visible_chunks.append(chunk)
            continue
        dropped = DroppedChunk(doc_id=chunk.doc_id, reason=decision.reason, matched_by=decision.matched_by)
        result.dropped.append(dropped)
        log.info(
            EVENT_DROPPED,
            extra={
                "event": EVENT_DROPPED,
                "doc_id": dropped.doc_id,
                "reason": dropped.reason,
                "matched_by": dropped.matched_by,
                "role_fp": role_fp,
                "site_fp": site_fp,
                "request_id": request_id,
            },
        )
    return result
