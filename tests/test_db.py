from decimal import Decimal

import db
from tests.fakes import FakeTable


def test_create_and_get_roundtrip():
    t = FakeTable()
    created = db.create_contract(
        {
            "vendor": "Acme",
            "cat": "Construction",
            "value": 1500.5,
            "start": "2024-01-01",
            "end": "2025-01-01",
        },
        table=t,
    )
    assert created["id"].startswith("c_")
    assert created["vendor"] == "Acme"

    got = db.get_contract(created["id"], table=t)
    assert got["vendor"] == "Acme"
    # numeric value round-trips as a plain float, not Decimal
    assert got["value"] == 1500.5
    assert not isinstance(got["value"], Decimal)


def test_value_stored_as_decimal():
    t = FakeTable()
    db.create_contract({"id": "c1", "vendor": "V", "value": 200.0}, table=t)
    stored = t._items["c1"]["value"]
    assert isinstance(stored, Decimal)


def test_list_contracts_returns_all():
    t = FakeTable()
    db.create_contract({"id": "a", "vendor": "A"}, table=t)
    db.create_contract({"id": "b", "vendor": "B"}, table=t)
    ids = {c["id"] for c in db.list_contracts(table=t)}
    assert ids == {"a", "b"}


def test_update_only_changes_given_fields():
    t = FakeTable()
    db.create_contract(
        {"id": "c1", "vendor": "Old", "cat": "Services", "value": 100.0},
        table=t,
    )
    updated = db.update_contract("c1", {"vendor": "New"}, table=t)
    assert updated["vendor"] == "New"
    # untouched fields survive
    assert updated["cat"] == "Services"
    assert updated["value"] == 100


def test_field_whitelist_ignores_unknown_keys():
    t = FakeTable()
    created = db.create_contract(
        {"id": "c1", "vendor": "V", "hacker": "nope"}, table=t
    )
    assert "hacker" not in created


def test_add_document_to_contract():
    t = FakeTable()
    db.create_contract({"id": "c1", "vendor": "V"}, table=t)
    updated = db.add_document_to_contract("c1", "d99", table=t)
    assert "d99" in updated["documents"]
    # idempotent
    again = db.add_document_to_contract("c1", "d99", table=t)
    assert again["documents"].count("d99") == 1


def test_document_crud():
    t = FakeTable()
    doc = db.create_document(
        {"contract_id": "c1", "filename": "f.pdf", "s3_key": "uploads/f.pdf",
         "type": "contract", "size": 10},
        table=t,
    )
    assert doc["id"].startswith("d_")
    assert doc["archived"] is False
    archived = db.update_document(doc["id"], {"archived": True}, table=t)
    assert archived["archived"] is True
