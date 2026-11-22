"""AC3：角色被收回后，历史消息中的引用折叠为「该内容已无权查看」。"""
from __future__ import annotations

import json

from aclguard.assistant import RecordingModelClient, Session, ask
from aclguard.history import FOLD_MARKER, render_history, visible_citations_only
from aclguard.iam_stub import load_roles
from aclguard.kb_stub import LeakyKnowledgeBase, load_entries

TARGET_DOC_ID = "doc-013"


def _session_with_sales_citation():
    principals = load_roles()
    sales = principals["sales"]
    entries = load_entries()
    target = next(e for e in entries if e.doc_id == TARGET_DOC_ID)
    kb = LeakyKnowledgeBase(entries)
    model = RecordingModelClient()
    session = Session(session_id="ac3")
    ask(session, target.title + " 的具体要求是什么？", sales, kb, model, cache=None, request_id="ac3-001")
    return principals, session, target


def test_acl3_revoked_role_folds_history_citation():
    principals, session, target = _session_with_sales_citation()
    sales = principals["sales"]
    assert target.visibility_label == "role_limited"
    assert any(c["doc_id"] == target.doc_id for m in session.messages for c in m["citations"])

    revoked = sales.without_roles(["sales_rep"])
    rendered, folded = render_history(session.messages, revoked)
    text = json.dumps(rendered, ensure_ascii=False)

    assert folded >= 1
    assert FOLD_MARKER in text
    assistant_text = " ".join(m["text"] for m in rendered if m["role"] == "assistant")
    assert target.title not in assistant_text
    assert target.body[:40] not in assistant_text
    for msg in rendered:
        for c in msg["citations"]:
            if c["doc_id"] == target.doc_id:
                assert c["title"] == FOLD_MARKER and c["snippet"] == FOLD_MARKER

    still_visible = render_history(session.messages, sales)[0]
    assert FOLD_MARKER not in json.dumps(still_visible, ensure_ascii=False)
    assert target.title in json.dumps(still_visible, ensure_ascii=False)


def test_acl3_next_turn_model_request_excludes_revoked_citation():
    principals, session, target = _session_with_sales_citation()
    revoked = principals["sales"].without_roles(["sales_rep"])
    kept = visible_citations_only(session.messages, revoked)
    assert all(c.doc_id != target.doc_id for c in kept)

    model = RecordingModelClient()
    kb = LeakyKnowledgeBase(load_entries())
    ask(session, target.title + " 还有哪几条？", revoked, kb, model, cache=None, request_id="ac3-002")
    context = json.dumps(model.last_request.chunks, ensure_ascii=False)
    assert target.title not in context
    assert target.body[:40] not in context