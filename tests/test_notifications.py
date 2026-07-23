from datetime import date, timedelta

import pytest

import config
import db
import notifications
from tests.fakes import FakeTable


def iso(off):
    return (date.today() + timedelta(days=off)).isoformat()


@pytest.fixture
def wired(monkeypatch):
    contracts, documents, messages = FakeTable(), FakeTable(), FakeTable()
    monkeypatch.setattr(db, "_contracts_table", lambda: contracts)
    monkeypatch.setattr(db, "_documents_table", lambda: documents)
    monkeypatch.setattr(db, "_messages_table", lambda: messages)
    monkeypatch.setattr(config, "DEMO_MODE", False)
    monkeypatch.setattr(config, "SES_FROM_EMAIL", "sender@example.com")
    monkeypatch.setattr(config, "ALERT_TEST_RECIPIENT", "test@example.com")

    sent = []
    monkeypatch.setattr(
        notifications, "_send_ses",
        lambda subject, t, h, to: sent.append((to, subject)) or "ses-abc",
    )

    # expiring contract WITH head email
    db.create_contract({
        "id": "c_mail", "vendor": "Acme", "poly": "A-1", "end": iso(10),
        "ins": iso(400), "contract_head": "Dana", "contract_head_email": "dana@fhda.edu",
    })
    db.create_document({"id": "d_agr", "contract_id": "c_mail", "type": "contract",
                        "filename": "agr.pdf", "s3_key": "uploads/agr.pdf"})
    db.create_document({"id": "d_coi", "contract_id": "c_mail", "type": "coi",
                        "filename": "coi.pdf", "s3_key": "uploads/coi.pdf"})
    # expiring contract WITHOUT head email
    db.create_contract({
        "id": "c_noemail", "vendor": "Beta", "end": iso(5),
        "contract_head": "Sam", "contract_head_email": "",
    })
    # active contract (no alert)
    db.create_contract({"id": "c_active", "vendor": "Gamma", "end": iso(300)})
    return sent


def test_build_message_content():
    subject, text, html = notifications.build_message(
        {"vendor": "Acme", "poly": "A-1"}, "d_agr", "d_coi", "http://site"
    )
    assert "expire in 30 days" in text
    assert "http://site" in text
    assert "/api/documents/d_agr/view" in text
    assert "/api/documents/d_coi/view" in html
    assert "Acme" in subject


def test_notify_sends_for_contract_with_email(wired):
    sent = wired
    results = notifications.notify_expiring("http://site")
    by_id = {r["contract_id"]: r for r in results}
    assert by_id["c_mail"]["status"] == "sent"
    # delivered to the test override, not the head's real address
    assert len(sent) == 1
    assert sent[0][0] == "test@example.com"

    msg = db.get_message(by_id["c_mail"]["message_id"])
    assert msg["to_email"] == "dana@fhda.edu"
    assert msg["to_actual"] == "test@example.com"
    assert msg["send_status"] == "sent"
    assert msg["agreement_doc_id"] == "d_agr"
    assert msg["coi_doc_id"] == "d_coi"


def test_notify_skips_contract_without_email(wired):
    results = notifications.notify_expiring("http://site")
    by_id = {r["contract_id"]: r for r in results}
    assert by_id["c_noemail"]["status"] == "skipped_no_email"
    # no message stored for it
    assert all(m.get("contract_id") != "c_noemail" for m in db.list_messages())


def test_notify_ignores_non_expiring(wired):
    results = notifications.notify_expiring("http://site")
    assert "c_active" not in {r["contract_id"] for r in results}


def test_notify_is_idempotent(wired):
    sent = wired
    notifications.notify_expiring("http://site")
    first = len([s for s in sent if s[0] == "test@example.com"])
    results2 = notifications.notify_expiring("http://site")
    second = len([s for s in sent if s[0] == "test@example.com"])
    assert first == second  # not re-sent
    by_id = {r["contract_id"]: r for r in results2}
    assert by_id["c_mail"]["status"] == "already_sent"
