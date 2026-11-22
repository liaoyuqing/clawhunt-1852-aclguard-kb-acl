"""AC1：知识库桩返回无权片段时，模型请求体不含该片段内容，且有 kb_acl_dropped 日志。"""
from __future__ import annotations

import json
import logging

from aclguard.assistant import RecordingModelClient, Session, ask
from aclguard.iam_stub import load_roles
from aclguard.kb_stub import LeakyKnowledgeBase
from aclguard.models import Chunk, KnowledgeEntry
from aclguard.second_check import EVENT_DROPPED, filter_chunks, log_payload_has_leak


class CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _logger_with_handler():
    logger = logging.getLogger("aclguard.test.ac1")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False
    handler = CollectingHandler()
    logger.addHandler(handler)
    return logger, handler


def _secret_entry():
    return KnowledgeEntry(
        doc_id="doc-033",
        title="三家会员企业欠款清单",
        body="欠款清单一：A 会员企业尚欠 128000 分，账龄 47 天，联系人虚构；清单一：B 会员企业尚欠 96000 分，账龄 12 天。本段为虚构测试文本。",
        visibility_label="confidential",
        module="kb_front",
        allowed_subject_ids=("u-lead-04",),
    )


def _public_entry():
    return KnowledgeEntry(
        doc_id="doc-001",
        title="入馆流程总览",
        body="入馆流程总览的完整说明：适用于所有会员与员工，共 5 个步骤，到访前需在自助终端确认。本段为虚构测试文本。",
        visibility_label="all_staff",
        module="kb_core",
    )


def test_acl1_kb_stub_returns_forbidden_chunk_then_model_body_clean():
    logger, handler = _logger_with_handler()
    principal = load_roles()["front"]
    secret = _secret_entry()
    public = _public_entry()
    kb = LeakyKnowledgeBase([secret, public])
    model = RecordingModelClient()
    session = Session(session_id="ac1")

    result = ask(session, "欠款清单与入馆流程", principal, kb, model, cache=None, logger=logger, request_id="ac1-001")

    body = json.dumps(model.last_request.as_dict(), ensure_ascii=False)
    assert secret.doc_id not in body
    assert secret.title not in body
    assert secret.body[:20] not in body
    assert model.last_request.chunks and all(c["doc_id"] != secret.doc_id for c in model.last_request.chunks)
    assert secret.doc_id in result["dropped"]

    dropped_records = [r for r in handler.records if getattr(r, "event", None) == EVENT_DROPPED]
    assert len(dropped_records) == 1
    assert dropped_records[0].doc_id == secret.doc_id
    assert dropped_records[0].reason == "principal_deny"
    assert dropped_records[0].visibility_label == "confidential"
    assert len(dropped_records[0].role_fp) == 16
    assert len(dropped_records[0].site_fp) == 16
    assert log_payload_has_leak(dropped_records[0], [secret.body[:20], secret.title]) is False


def test_acl1_filter_chunks_drops_every_label_combination():
    logger, handler = _logger_with_handler()
    principals = load_roles()
    secret = _secret_entry()
    public = _public_entry()
    for key, principal in principals.items():
        result = filter_chunks((Chunk.from_entry(secret), Chunk.from_entry(public)), principal, logger, request_id="ac1-%s" % key)
        visible_ids = [c.doc_id for c in result.visible_chunks]
        assert visible_ids == ["doc-001"]
        assert result.dropped_doc_ids == ("doc-033",)
    assert len([r for r in handler.records if getattr(r, "event", None) == EVENT_DROPPED]) == len(principals)