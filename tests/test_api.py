import io
from datetime import date, timedelta

import pytest

import app as flask_app
import db
import notifications
import parser as ai_parser
import storage
from tests.fakes import FakeTable


def iso(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


@pytest.fixture
def client(monkeypatch):
    contracts = FakeTable()
    documents = FakeTable()
    messages = FakeTable()
    monkeypatch.setattr(db, "_contracts_table", lambda: contracts)
    monkeypatch.setattr(db, "_documents_table", lambda: documents)
    monkeypatch.setattr(db, "_messages_table", lambda: messages)

    # seed one active + one expiring-insurance contract
    db.create_contract(
        {"id": "c1", "vendor": "Acme", "cat": "Construction",
         "college": "Foothill", "value": 1000.0, "end": iso(400),
         "ins": iso(400), "po": "PO-1", "poly": "A-1"}
    )
    db.create_contract(
        {"id": "c2", "vendor": "BrightClean", "cat": "Services",
         "college": "De Anza", "value": 500.0, "end": iso(10),
         "ins": iso(5), "po": "PO-2", "poly": "A-2"}
    )
    db.create_document(
        {"id": "d1", "contract_id": "c1", "filename": "acme.pdf",
         "s3_key": "uploads/acme.pdf", "type": "contract", "archived": False}
    )

    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"ConTrackt" in r.data


def test_list_contracts_enriched(client):
    r = client.get("/api/contracts")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 2
    statuses = {c["id"]: c["status"] for c in data}
    assert statuses["c1"] == "active"
    assert statuses["c2"] == "expiring"


def test_get_single_contract_expands_documents(client):
    r = client.get("/api/contracts/c1")
    assert r.status_code == 200
    data = r.get_json()
    assert data["vendor"] == "Acme"
    assert any(d["id"] == "d1" for d in data["document_records"])


def test_get_missing_contract_404(client):
    assert client.get("/api/contracts/nope").status_code == 404


def test_stats(client):
    s = client.get("/api/stats").get_json()
    assert s["total_contracts"] == 2
    assert s["total_value"] == 1500.0
    assert s["active"] == 1
    assert s["expiring"] == 1
    assert s["by_category"]["Construction"] == 1


def test_alerts_only_within_window(client):
    alerts = client.get("/api/alerts").get_json()
    # c2 has both insurance(5d) and contract-end(10d) in window; c1 is far out
    kinds = {(a["contract_id"], a["kind"]) for a in alerts}
    assert ("c2", "insurance") in kinds
    assert ("c2", "contract") in kinds
    assert all(a["contract_id"] == "c2" for a in alerts)


def test_create_contract_requires_vendor(client):
    r = client.post("/api/contracts", json={"cat": "X"})
    assert r.status_code == 400


def test_create_and_update_contract(client):
    r = client.post("/api/contracts", json={"vendor": "New Co", "value": 42.0})
    assert r.status_code == 201
    cid = r.get_json()["id"]

    r2 = client.put(f"/api/contracts/{cid}", json={"vendor": "Renamed"})
    assert r2.status_code == 200
    assert r2.get_json()["vendor"] == "Renamed"


def test_upload_stores_and_parses(client, monkeypatch):
    # sync path: ASYNC_PARSE disabled
    monkeypatch.setattr(flask_app.config, "ASYNC_PARSE", False)
    monkeypatch.setattr(storage, "upload_to_key", lambda *a, **k: a[0] if a else "uploads/x.pdf")
    monkeypatch.setattr(
        ai_parser, "parse_document",
        lambda *a, **k: {"vendor": "Parsed Vendor", "value": 99,
                         "_meta": {"ok": True, "method": "bedrock_document"}},
    )
    data = {"file": (io.BytesIO(b"%PDF-1.4 fake"), "test.pdf")}
    r = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert r.status_code == 201
    body = r.get_json()
    assert body["async"] is False
    assert body["document"]["s3_key"].startswith("uploads/")
    assert body["fields"]["vendor"] == "Parsed Vendor"
    assert body["document"]["parse_status"] == "done"


def test_upload_rejects_bad_extension(client):
    data = {"file": (io.BytesIO(b"x"), "malware.exe")}
    r = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert r.status_code == 400


def test_document_presign(client, monkeypatch):
    monkeypatch.setattr(storage, "presigned_url", lambda *a, **k: "https://signed")
    r = client.get("/api/documents/d1/url")
    assert r.status_code == 200
    assert r.get_json()["url"] == "https://signed"


def test_document_archive_toggle(client):
    r = client.patch("/api/documents/d1", json={"archived": True})
    assert r.status_code == 200
    assert r.get_json()["archived"] is True


def test_get_document(client):
    r = client.get("/api/documents/d1")
    assert r.status_code == 200
    assert r.get_json()["filename"] == "acme.pdf"


def test_alerts_include_email_info(client):
    # c2 is expiring; give it a head email so the alert reports has_email
    db.update_contract("c2", {"contract_head": "Sam", "contract_head_email": "sam@fhda.edu"})
    alerts = client.get("/api/alerts").get_json()
    c2 = [a for a in alerts if a["contract_id"] == "c2"][0]
    assert c2["has_email"] is True
    assert c2["contract_head"] == "Sam"
    assert "message_id" in c2  # None until notified


def test_notify_and_view_message(client, monkeypatch):
    monkeypatch.setattr(flask_app.config, "DEMO_MODE", False)
    monkeypatch.setattr(flask_app.config, "SES_FROM_EMAIL", "sender@example.com")
    monkeypatch.setattr(flask_app.config, "ALERT_TEST_RECIPIENT", "test@example.com")
    monkeypatch.setattr(notifications, "_send_ses", lambda *a, **k: "ses-xyz")
    db.update_contract("c2", {"contract_head_email": "sam@fhda.edu"})

    r = client.post("/api/alerts/notify")
    assert r.status_code == 200
    assert r.get_json()["summary"].get("sent", 0) >= 1

    # the alert now carries a message_id we can open
    alerts = client.get("/api/alerts").get_json()
    c2 = [a for a in alerts if a["contract_id"] == "c2"][0]
    assert c2["message_id"]
    msg = client.get(f"/api/messages/{c2['message_id']}").get_json()
    assert "expire in 30 days" in msg["body_text"]
    assert msg["send_status"] == "sent"


def test_document_view_redirects(client, monkeypatch):
    monkeypatch.setattr(storage, "presigned_url", lambda *a, **k: "https://signed.example")
    r = client.get("/api/documents/d1/view", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"] == "https://signed.example"


def test_upload_async_sets_pending_and_skips_inline_parse(client, monkeypatch):
    monkeypatch.setattr(flask_app.config, "ASYNC_PARSE", True)
    monkeypatch.setattr(flask_app.config, "DEMO_MODE", False)
    monkeypatch.setattr(storage, "upload_to_key", lambda *a, **k: "uploads/x.pdf")

    def _boom(*a, **k):
        raise AssertionError("parse_document must NOT run in async mode")

    monkeypatch.setattr(ai_parser, "parse_document", _boom)

    data = {"file": (io.BytesIO(b"%PDF-1.4"), "async.pdf")}
    r = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert r.status_code == 201
    body = r.get_json()
    assert body["async"] is True
    assert body["fields"] is None
    assert body["document"]["parse_status"] == "pending"

    # the record is retrievable for polling
    did = body["document"]["id"]
    doc = client.get(f"/api/documents/{did}").get_json()
    assert doc["parse_status"] == "pending"
