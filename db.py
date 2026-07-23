"""DynamoDB data-access layer for contracts and documents.

All numeric values are stored as Decimal (DynamoDB requirement) and converted
back to plain int/float on read so the rest of the app deals in JSON-friendly
types. Table accessors are indirected through small functions so tests can
inject an in-memory fake.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import config
from aws_clients import dynamodb_resource

# Fields that make up a contract record (aligned with the UI field names).
CONTRACT_FIELDS = [
    "poly",     # agreement / policy number
    "vendor",   # vendor / counterparty name
    "cat",      # category
    "sub",      # subcategory
    "college",  # campus (Foothill / De Anza / District)
    "scope",    # scope of work (raw)
    "summary",  # AI-generated summary
    "start",    # contract start date (YYYY-MM-DD)
    "end",      # contract end date (YYYY-MM-DD)
    "value",    # dollar value (number)
    "po",       # purchase order number
    "poEnd",    # PO end date (YYYY-MM-DD)
    "ins",      # insurance / COI expiration date (YYYY-MM-DD)
    "addl",     # additional insured endorsement (Yes/No/text)
    "contract_head",        # name of the responsible person
    "contract_head_email",  # their email (blank => no alert email sent)
    "archived",             # True => hidden from the dashboard/stats/alerts
]

MESSAGE_FIELDS = [
    "contract_id",
    "kind",             # e.g. "expiry"
    "to_email",         # the contract head's email (display)
    "to_actual",        # where it was actually delivered (test override)
    "subject",
    "body_html",
    "body_text",
    "website_url",
    "agreement_doc_id",
    "coi_doc_id",
    "send_status",      # sent | demo | failed
    "ses_message_id",
    "error",
    "sent_at",
]

DOCUMENT_FIELDS = [
    "contract_id",
    "filename",
    "s3_key",
    "type",
    "size",
    "content_type",
    "archived",
    "parse_status",   # pending | processing | done | error | skipped
    "parsed_fields",  # dict of AI-extracted fields (async parse result)
    "parse_error",    # error message if parse_status == error
]


# --------------------------------------------------------------------------
# Table accessors (indirected for testability)
# --------------------------------------------------------------------------
def _contracts_table():
    if config.DEMO_MODE:
        import memstore
        return memstore.CONTRACTS
    return dynamodb_resource().Table(config.DDB_CONTRACTS_TABLE)


def _documents_table():
    if config.DEMO_MODE:
        import memstore
        return memstore.DOCUMENTS
    return dynamodb_resource().Table(config.DDB_DOCUMENTS_TABLE)


def _messages_table():
    if config.DEMO_MODE:
        import memstore
        return memstore.MESSAGES
    return dynamodb_resource().Table(config.DDB_MESSAGES_TABLE)


# --------------------------------------------------------------------------
# (de)serialization helpers
# --------------------------------------------------------------------------
def _now():
    return datetime.now(timezone.utc).isoformat()


def to_dynamo(value):
    """Recursively convert floats to Decimal for DynamoDB."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [to_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    return value


def from_dynamo(value):
    """Recursively convert Decimal back to int/float for JSON responses."""
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------
# Domain logic (server is the source of truth for status + alerts)
# --------------------------------------------------------------------------
def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(value)[:10], fmt).date()
        except ValueError:
            continue
    return None


def days_until(value, today=None):
    d = _parse_date(value)
    if d is None:
        return None
    today = today or date.today()
    return (d - today).days


def compute_status(contract, today=None, window=None):
    """Derive an overall status from the contract end date."""
    window = window if window is not None else config.ALERT_WINDOW_DAYS
    d = days_until(contract.get("end"), today)
    if d is None:
        return "unknown"
    if d < 0:
        return "expired"
    if d <= window:
        return "expiring"
    return "active"


def enrich(contract, today=None, window=None):
    """Attach derived fields the UI relies on."""
    window = window if window is not None else config.ALERT_WINDOW_DAYS
    c = dict(contract)
    c["status"] = compute_status(c, today, window)
    c["days_to_end"] = days_until(c.get("end"), today)
    c["days_to_insurance"] = days_until(c.get("ins"), today)
    c["days_to_po_end"] = days_until(c.get("poEnd"), today)
    return c


# --------------------------------------------------------------------------
# Contracts CRUD
# --------------------------------------------------------------------------
def create_contract(data, table=None):
    table = table or _contracts_table()
    cid = data.get("id") or "c_" + uuid.uuid4().hex[:12]
    now = _now()
    item = {
        "id": cid,
        "documents": data.get("documents", []),
        "created_at": now,
        "updated_at": now,
    }
    for f in CONTRACT_FIELDS:
        if data.get(f) is not None:
            item[f] = data[f]
    table.put_item(Item=to_dynamo(item))
    return from_dynamo(item)


def get_contract(cid, table=None):
    table = table or _contracts_table()
    item = table.get_item(Key={"id": cid}).get("Item")
    return from_dynamo(item) if item else None


def list_contracts(table=None):
    table = table or _contracts_table()
    items = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return [from_dynamo(i) for i in items]


def update_contract(cid, updates, table=None):
    table = table or _contracts_table()
    allowed = {
        k: v
        for k, v in updates.items()
        if k in CONTRACT_FIELDS or k == "documents"
    }
    allowed["updated_at"] = _now()
    names, values, sets = {}, {}, []
    for i, (k, v) in enumerate(allowed.items()):
        names[f"#f{i}"] = k
        values[f":v{i}"] = to_dynamo(v)
        sets.append(f"#f{i} = :v{i}")
    resp = table.update_item(
        Key={"id": cid},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return from_dynamo(resp.get("Attributes", {}))


def add_document_to_contract(cid, doc_id, table=None):
    table = table or _contracts_table()
    contract = get_contract(cid, table)
    if not contract:
        return None
    docs = contract.get("documents") or []
    if doc_id not in docs:
        docs.append(doc_id)
    return update_contract(cid, {"documents": docs}, table)


# --------------------------------------------------------------------------
# Documents CRUD
# --------------------------------------------------------------------------
def create_document(data, table=None):
    table = table or _documents_table()
    did = data.get("id") or "d_" + uuid.uuid4().hex[:12]
    item = {
        "id": did,
        "uploaded_at": _now(),
        "archived": bool(data.get("archived", False)),
    }
    for f in DOCUMENT_FIELDS:
        if data.get(f) is not None:
            item[f] = data[f]
    table.put_item(Item=to_dynamo(item))
    return from_dynamo(item)


def get_document(did, table=None):
    table = table or _documents_table()
    item = table.get_item(Key={"id": did}).get("Item")
    return from_dynamo(item) if item else None


def list_documents(table=None):
    table = table or _documents_table()
    items = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return [from_dynamo(i) for i in items]


def update_document(did, updates, table=None):
    table = table or _documents_table()
    allowed = {k: v for k, v in updates.items() if k in DOCUMENT_FIELDS}
    if not allowed:
        return get_document(did, table)
    names, values, sets = {}, {}, []
    for i, (k, v) in enumerate(allowed.items()):
        names[f"#f{i}"] = k
        values[f":v{i}"] = to_dynamo(v)
        sets.append(f"#f{i} = :v{i}")
    resp = table.update_item(
        Key={"id": did},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return from_dynamo(resp.get("Attributes", {}))


# --------------------------------------------------------------------------
# Messages (sent alert emails)
# --------------------------------------------------------------------------
def create_message(data, table=None):
    """Store a sent-message record. `id` is caller-provided (deterministic)."""
    table = table or _messages_table()
    mid = data.get("id") or "m_" + uuid.uuid4().hex[:12]
    item = {"id": mid, "sent_at": data.get("sent_at") or _now()}
    for f in MESSAGE_FIELDS:
        if data.get(f) is not None:
            item[f] = data[f]
    table.put_item(Item=to_dynamo(item))
    return from_dynamo(item)


def get_message(mid, table=None):
    table = table or _messages_table()
    item = table.get_item(Key={"id": mid}).get("Item")
    return from_dynamo(item) if item else None


def list_messages(table=None):
    table = table or _messages_table()
    items = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return [from_dynamo(i) for i in items]


def message_id_for(contract, stage):
    """Deterministic message id for a contract's expiry window + reminder stage.

    Includes the end + insurance dates so a renewed contract (new dates) can
    trigger fresh notifications, plus the stage ("d30" / "d14") so the 30-day
    and 2-week reminders are distinct and both get sent.
    """
    cid = contract.get("id")
    return f"m_{cid}_{contract.get('end') or 'na'}_{contract.get('ins') or 'na'}_{stage}"
