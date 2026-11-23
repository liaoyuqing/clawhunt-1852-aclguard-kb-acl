"""助手侧二次校验：丢弃不可见片段，且审计日志只记 doc_id 级信息。"""
from __future__ import annotations

import logging

from .audit import EVENT_DROPPED, format_audit_line, get_audit_logger
from .cache_key import role_fingerprint, site_fingerprint
from .models import DroppedChunk, Principal, SecondCheckResult
from .visibility import decide

# 保留旧常量名，供既有测试与外部调用方引用；值来自统一审计模块。
DEFAULT_LOGGER_NAME = "aclguard.audit"

# 模型上下文里每条片段注入的正文上限（只放行可见片段，此处仅控制体积）
MODEL_TEXT_LIMIT = 200


def filter_chunks(chunks, principal: Principal, logger=None, request_id: str = "") -> SecondCheckResult:
    """按当前主体逐片段判定，返回可见片段与丢弃清单。

    日志只写 doc_id / reason / matched_by / 标签 / 指纹 / request_id，
    绝不写标题或正文，避免审计日志本身变成泄露面。
    """
    log = get_audit_logger(logger)
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
        fields = {
            "doc_id": dropped.doc_id,
            "reason": dropped.reason,
            "role_fp": role_fp,
            "site_fp": site_fp,
            "request_id": request_id,
        }
        # 消息文本本身带全部关键字段：默认 handler 只渲染 getMessage()，
        # 若只塞 extra，运维 grep 日志时一条都检索不到。
        log.info(
            format_audit_line(EVENT_DROPPED, fields),
            extra={
                "event": EVENT_DROPPED,
                "matched_by": dropped.matched_by,
                "visibility_label": getattr(chunk, "visibility_label", ""),
                **fields,
            },
        )
    return result


def describe_for_model(chunks) -> list:
    """把已放行片段转成模型上下文；只含 doc_id / title / 正文前 N 字。"""
    return [
        {
            "doc_id": c.doc_id,
            "title": c.title,
            "text": c.text[:MODEL_TEXT_LIMIT],
        }
        for c in chunks
    ]


def log_payload_has_leak(record: logging.LogRecord, markers) -> bool:
    """检查一条日志记录的任何字段是否含给定标记（用于反向断言日志不泄正文）。"""
    parts = [str(record.getMessage())]
    for key, value in vars(record).items():
        parts.append(str(key))
        parts.append(str(value))
    blob = " ".join(parts)
    return any(marker and marker in blob for marker in markers)
