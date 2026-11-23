"""统一审计日志出口：事件字段必须出现在格式化后的日志行里，便于按 doc_id / request_id 检索。"""
from __future__ import annotations

import logging

# 全包只有一个审计 logger 名，assistant 与 second_check 共用，避免日志分裂到两个 channel。
LOGGER_NAME = "aclguard.audit"

EVENT_DROPPED = "kb_acl_dropped"
EVENT_CACHE_REVOKED = "kb_acl_cache_revoked"

# 审计事件字段顺序固定，便于用正则从纯文本日志里抽字段。
FIELD_ORDER = ("doc_id", "reason", "role_fp", "site_fp", "request_id")


def get_audit_logger(logger: logging.Logger = None) -> logging.Logger:
    """取审计 logger；调用方可注入自定义 logger（测试用），默认用统一名字。"""
    return logger if logger is not None else logging.getLogger(LOGGER_NAME)


def format_audit_line(event: str, fields: dict) -> str:
    """把事件与关键字段拼成一行可检索文本：`kb_acl_dropped doc_id=... reason=...`。

    只允许 doc_id 级信息进入这一行；标题与正文一律不进日志，避免日志本身成为泄露面。
    """
    parts = [event]
    for key in FIELD_ORDER:
        if key in fields and fields[key] not in (None, ""):
            parts.append("%s=%s" % (key, fields[key]))
    return " ".join(parts)
