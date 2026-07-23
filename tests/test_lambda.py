import importlib.util
import io
import os

import pytest

import db
import parser as ai_parser
from tests.fakes import FakeTable


def _load_handler():
    path = os.path.join(os.path.dirname(__file__), "..", "lambda", "handler.py")
    spec = importlib.util.spec_from_file_location("lambda_handler", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeS3:
    def __init__(self, data):
        self._data = data

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self._data)}


def _event(key, bucket="contrackt-docs"):
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


@pytest.fixture
def wired(monkeypatch):
    docs = FakeTable()
    monkeypatch.setattr(db, "_documents_table", lambda: docs)
    handler = _load_handler()
    monkeypatch.setattr(handler, "_s3", _FakeS3(b"%PDF-1.4 fake"))
    return handler


def test_handler_parses_pending_doc(wired, monkeypatch):
    doc = db.create_document(
        {"s3_key": "uploads/abc_test.pdf", "filename": "test.pdf",
         "type": "contract", "parse_status": "pending"}
    )
    monkeypatch.setattr(
        ai_parser, "parse_document",
        lambda *a, **k: {"vendor": "Acme", "value": 100, "_meta": {"ok": True}},
    )

    out = wired.handler(_event("uploads/abc_test.pdf"), None)
    assert out["results"][0]["action"] == "parsed"

    updated = db.get_document(doc["id"])
    assert updated["parse_status"] == "done"
    assert updated["parsed_fields"]["vendor"] == "Acme"


def test_handler_skips_non_pending(wired, monkeypatch):
    db.create_document(
        {"s3_key": "uploads/seed.pdf", "filename": "seed.pdf", "type": "contract"}
    )
    monkeypatch.setattr(ai_parser, "parse_document",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not parse")))
    out = wired.handler(_event("uploads/seed.pdf"), None)
    assert out["results"][0]["action"] == "skip"


def test_handler_records_parse_error(wired, monkeypatch):
    doc = db.create_document(
        {"s3_key": "uploads/bad.pdf", "filename": "bad.pdf",
         "type": "contract", "parse_status": "pending"}
    )

    def _boom(*a, **k):
        raise RuntimeError("bedrock exploded")

    monkeypatch.setattr(ai_parser, "parse_document", _boom)
    out = wired.handler(_event("uploads/bad.pdf"), None)
    assert out["results"][0]["action"] == "error"
    assert db.get_document(doc["id"])["parse_status"] == "error"


def test_handler_ignores_unknown_key(wired):
    out = wired.handler(_event("uploads/nonexistent.pdf"), None)
    assert out["results"][0]["action"] == "skip"
