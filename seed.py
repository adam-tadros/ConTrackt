"""Seed the backend with sample FHDA contracts + their documents.

Reads the real PDF pairs in ./samples (AGR_xx = agreement, COI_xx = matching
certificate of insurance), stores each file via storage.upload_bytes (S3 in
normal mode, in-memory blob store in demo mode), and creates linked contract +
document records in DynamoDB (or the in-memory tables in demo mode).

    python seed.py            # insert sample data
    python seed.py --wipe     # remove previously-seeded sample rows first

Because it goes through the same storage/db layer as the app, this works
against live AWS and populates real, viewable documents.
"""
import glob
import os
import re
import sys
from datetime import date, timedelta

import db
import storage

SAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

# Rotated so the seeded set has a realistic spread (and drives the Alerts tab).
_CATEGORIES = [
    ("Construction", "General Contractor"),
    ("Services", "Consulting"),
    ("Services", "Landscaping"),
    ("Services", "Campus Security"),
    ("Services", "Catering"),
    ("Software", "IT Consulting"),
    ("Services", "Facilities"),
    ("Services", "Marketing"),
    ("Services", "Environmental"),
    ("Software", "IT Consulting"),
]
_COLLEGES = ["Foothill", "De Anza", "District"]
_HEADS = ["Dana Ruiz", "Marcus Lee", "Priya Shah", "Tom Becker", "Elena Cortez"]


def _head_for(i):
    """Return (name, email). Roughly 1 in 6 has no email (alert-only case)."""
    head = _HEADS[i % len(_HEADS)]
    email = "" if i % 6 == 5 else head.lower().replace(" ", ".") + "@fhda.edu"
    return head, email
# (contract end offset, insurance expiry offset) in days from today.
_DATE_PLANS = [
    (-25, -25),   # expired  -> archived
    (14, 6),      # expiring soon (contract + insurance)
    (60, 18),     # insurance expiring soon
    (200, 25),    # insurance expiring soon
    (400, 120),   # active
    (730, 365),   # active
]


def _vendor_from(stem: str) -> str:
    name = re.sub(r"^(AGR|COI)_\d+_", "", stem)
    name = name.replace("___", " & ").replace("__", ", ").replace("_", " ")
    return name.strip()


def _iso(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _scan_pairs():
    """Return {num: {'agr': path, 'coi': path|None, 'vendor': str}} sorted by num."""
    agrs, cois = {}, {}
    for path in glob.glob(os.path.join(SAMPLES_DIR, "*.pdf")):
        base = os.path.basename(path)
        m = re.match(r"(AGR|COI)_(\d+)_", base)
        if not m:
            continue
        kind, num = m.group(1), m.group(2)
        (agrs if kind == "AGR" else cois)[num] = path
    pairs = {}
    for num, agr in agrs.items():
        pairs[num] = {
            "agr": agr,
            "coi": cois.get(num),
            "vendor": _vendor_from(os.path.basename(agr)[:-4]),
        }
    return dict(sorted(pairs.items(), key=lambda kv: int(kv[0])))


def _store_pdf(path, contract_id, doc_type, archived):
    with open(path, "rb") as fh:
        data = fh.read()
    key = storage.upload_bytes(data, os.path.basename(path), "application/pdf")
    doc = db.create_document(
        {
            "contract_id": contract_id,
            "filename": os.path.basename(path),
            "s3_key": key,
            "type": doc_type,
            "size": len(data),
            "content_type": "application/pdf",
            "archived": archived,
        }
    )
    db.add_document_to_contract(contract_id, doc["id"])
    return doc


def seed(wipe_first=False):
    pairs = _scan_pairs()
    if not pairs:
        print(f"No sample PDFs found in {SAMPLES_DIR}")
        return 0
    if wipe_first:
        wipe()

    count = 0
    for i, (num, p) in enumerate(pairs.items()):
        cid = f"c_sample_{num}"
        cat, sub = _CATEGORIES[i % len(_CATEGORIES)]
        college = _COLLEGES[i % len(_COLLEGES)]
        end_off, ins_off = _DATE_PLANS[i % len(_DATE_PLANS)]
        expired = end_off < 0
        vendor = p["vendor"]
        head, head_email = _head_for(i)

        db.create_contract(
            {
                "id": cid,
                "poly": f"AGR-2024-{num.zfill(3)}",
                "vendor": vendor,
                "cat": cat,
                "sub": sub,
                "college": college,
                "contract_head": head,
                "contract_head_email": head_email,
                "scope": f"{sub} services provided by {vendor} for the district.",
                "summary": f"Sample {cat.lower()} agreement with {vendor}.",
                "start": _iso(-365),
                "end": _iso(end_off),
                "value": float(75000 + (i * 41000) % 900000),
                "po": f"PO-{10000 + i * 137}",
                "poEnd": _iso(end_off),
                "ins": _iso(ins_off),
                "addl": "Yes" if i % 3 else "No",
            }
        )
        _store_pdf(p["agr"], cid, "contract", expired)
        if p["coi"]:
            _store_pdf(p["coi"], cid, "coi", expired)
        count += 1

    print(f"Seeded {count} contracts (with agreement + COI documents).")
    return count


def backfill_heads():
    """Set contract_head/contract_head_email on already-seeded contracts
    without recreating their documents. Safe to run against live data."""
    pairs = _scan_pairs()
    n = 0
    for i, num in enumerate(pairs):
        cid = f"c_sample_{num}"
        if not db.get_contract(cid):
            continue
        head, email = _head_for(i)
        db.update_contract(cid, {"contract_head": head, "contract_head_email": email})
        n += 1
    print(f"Backfilled contract heads on {n} contracts.")
    return n


def wipe():
    for num in _scan_pairs():
        cid = f"c_sample_{num}"
        contract = db.get_contract(cid)
        if contract:
            for doc_id in contract.get("documents", []):
                db._documents_table().delete_item(Key={"id": doc_id})
        db._contracts_table().delete_item(Key={"id": cid})
    print("Wiped previously-seeded sample rows.")


if __name__ == "__main__":
    seed(wipe_first="--wipe" in sys.argv)
