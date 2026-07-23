from datetime import date, timedelta

import db


def iso(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def test_days_until_handles_formats_and_none():
    assert db.days_until(None) is None
    assert db.days_until("not-a-date") is None
    assert db.days_until(iso(10)) == 10
    assert db.days_until("01/01/2020") is not None


def test_compute_status_active():
    assert db.compute_status({"end": iso(200)}) == "active"


def test_compute_status_expiring_within_window():
    assert db.compute_status({"end": iso(15)}) == "expiring"


def test_compute_status_expired():
    assert db.compute_status({"end": iso(-1)}) == "expired"


def test_compute_status_unknown_without_date():
    assert db.compute_status({}) == "unknown"


def test_enrich_adds_derived_fields():
    c = db.enrich({"end": iso(10), "ins": iso(5), "poEnd": iso(400)})
    assert c["status"] == "expiring"
    assert c["days_to_end"] == 10
    assert c["days_to_insurance"] == 5
    assert c["days_to_po_end"] == 400


def test_window_is_configurable():
    # a 45-day-out contract is active under a 30-day window...
    assert db.compute_status({"end": iso(45)}, window=30) == "active"
    # ...but expiring under a 60-day window
    assert db.compute_status({"end": iso(45)}, window=60) == "expiring"
