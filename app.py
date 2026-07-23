"""ConTrackt - FHDA Contract & Insurance Manager (AWS MVP).

Flask app that serves the single-page UI and a small JSON API backed by
DynamoDB (data), S3 (documents), and Bedrock/Textract (AI extraction).
"""
import logging

from flask import Flask, Response, jsonify, render_template, request

import config
import db
import parser as ai_parser
import storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("contrackt")

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _allowed(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS
    )


def _err(message, status=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


@app.errorhandler(413)
def too_large(_e):
    return _err(f"file exceeds {config.MAX_UPLOAD_MB}MB limit", 413)


@app.errorhandler(Exception)
def handle_unexpected(e):
    """Return JSON for API routes so the SPA can surface a clean message.

    Common local cause: AWS credentials/resources not configured yet.
    """
    from werkzeug.exceptions import HTTPException

    if isinstance(e, HTTPException):
        return e
    log.exception("unhandled error")
    if request.path.startswith("/api/"):
        return _err(f"server error: {e}", 500, hint="check AWS credentials, region, and that resources are provisioned")
    raise e


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "demo_mode": config.DEMO_MODE})


@app.route("/demo/file/<path:key>")
def demo_file(key):
    """Serve an in-memory uploaded file (demo mode only)."""
    if not config.DEMO_MODE:
        return _err("not available", 404)
    from urllib.parse import unquote

    import memstore

    blob = memstore.BLOBS.get(unquote(key))
    if not blob:
        return Response(
            "Demo placeholder: this seeded document has no stored file. "
            "Upload a new document to view a real one.",
            mimetype="text/plain",
        )
    data, content_type = blob
    return Response(data, mimetype=content_type or "application/octet-stream")


# --------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------
@app.route("/api/contracts", methods=["GET"])
def list_contracts():
    contracts = [db.enrich(c) for c in db.list_contracts()]
    contracts.sort(key=lambda c: (c.get("end") or ""))
    return jsonify(contracts)


@app.route("/api/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    contract = db.get_contract(cid)
    if not contract:
        return _err("contract not found", 404)
    contract = db.enrich(contract)
    # expand linked documents
    doc_ids = set(contract.get("documents") or [])
    docs = [d for d in db.list_documents() if d["id"] in doc_ids
            or d.get("contract_id") == cid]
    contract["document_records"] = docs
    return jsonify(contract)


@app.route("/api/contracts", methods=["POST"])
def create_contract():
    data = request.get_json(silent=True) or {}
    if not data.get("vendor"):
        return _err("vendor is required")
    document_id = data.pop("document_id", None)
    contract = db.create_contract(data)
    if document_id:
        contract = db.add_document_to_contract(contract["id"], document_id)
        db.update_document(document_id, {"contract_id": contract["id"]})
    return jsonify(db.enrich(contract)), 201


@app.route("/api/contracts/<cid>", methods=["PUT", "PATCH"])
def update_contract(cid):
    if not db.get_contract(cid):
        return _err("contract not found", 404)
    data = request.get_json(silent=True) or {}
    updated = db.update_contract(cid, data)
    return jsonify(db.enrich(updated))


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
@app.route("/api/documents", methods=["GET"])
def list_documents():
    docs = db.list_documents()
    docs.sort(key=lambda d: (d.get("uploaded_at") or ""), reverse=True)
    return jsonify(docs)


@app.route("/api/documents/<did>/url", methods=["GET"])
def document_url(did):
    doc = db.get_document(did)
    if not doc:
        return _err("document not found", 404)
    try:
        url = storage.presigned_url(doc["s3_key"], download_name=doc.get("filename"))
    except Exception as e:  # noqa: BLE001
        log.exception("presign failed")
        return _err(f"could not generate URL: {e}", 502)
    return jsonify({"url": url})


@app.route("/api/documents/<did>", methods=["GET"])
def get_document(did):
    doc = db.get_document(did)
    if not doc:
        return _err("document not found", 404)
    return jsonify(doc)


@app.route("/api/documents/<did>", methods=["PATCH"])
def update_document(did):
    if not db.get_document(did):
        return _err("document not found", 404)
    data = request.get_json(silent=True) or {}
    return jsonify(db.update_document(did, data))


# --------------------------------------------------------------------------
# Upload + AI parse (synchronous)
# --------------------------------------------------------------------------
@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return _err("no file provided")
    f = request.files["file"]
    if not f or f.filename == "":
        return _err("empty filename")
    if not _allowed(f.filename):
        return _err(
            f"unsupported file type; allowed: "
            f"{', '.join(sorted(config.ALLOWED_EXTENSIONS))}"
        )

    data = f.read()
    content_type = f.mimetype or "application/octet-stream"
    doc_type = request.form.get("type", "contract")
    do_parse = request.form.get("parse", "true").lower() != "false"

    key = storage.build_key(f.filename)
    async_parse = do_parse and config.ASYNC_PARSE and not config.DEMO_MODE

    base_doc = {
        "filename": f.filename,
        "s3_key": key,
        "type": doc_type,
        "size": len(data),
        "content_type": content_type,
        "parse_status": (
            "pending" if async_parse else ("processing" if do_parse else "skipped")
        ),
    }

    if async_parse:
        # Create the record FIRST so the S3-triggered Lambda can find it,
        # then write the object (which fires the event).
        doc = db.create_document(base_doc)
        try:
            storage.upload_to_key(key, data, content_type)
        except Exception as e:  # noqa: BLE001
            log.exception("s3 upload failed")
            db.update_document(doc["id"], {"parse_status": "error", "parse_error": str(e)})
            return _err(f"upload failed: {e}", 502)
        # Parsing happens in Lambda; the UI polls GET /api/documents/<id>.
        return jsonify({"document": doc, "fields": None, "async": True}), 201

    # Synchronous path (demo mode, or ASYNC_PARSE disabled).
    try:
        storage.upload_to_key(key, data, content_type)
    except Exception as e:  # noqa: BLE001
        log.exception("s3 upload failed")
        return _err(f"upload failed: {e}", 502)

    doc = db.create_document(base_doc)

    fields = None
    if do_parse:
        try:
            fields = ai_parser.parse_document(data, f.filename, content_type)
        except Exception as e:  # noqa: BLE001
            log.exception("parse failed")
            fields = {"_meta": {"ok": False, "error": str(e)}}
        db.update_document(
            doc["id"], {"parse_status": "done", "parsed_fields": fields}
        )
        doc["parse_status"] = "done"
        doc["parsed_fields"] = fields

    return jsonify({"document": doc, "fields": fields, "async": False}), 201


# --------------------------------------------------------------------------
# Dashboard stats + alerts
# --------------------------------------------------------------------------
@app.route("/api/stats", methods=["GET"])
def stats():
    contracts = [db.enrich(c) for c in db.list_contracts()]
    by_status, by_category, by_college = {}, {}, {}
    total_value = 0.0
    for c in contracts:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
        cat = c.get("cat") or "Uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1
        col = c.get("college") or "Unassigned"
        by_college[col] = by_college.get(col, 0) + 1
        total_value += float(c.get("value") or 0)
    return jsonify(
        {
            "total_contracts": len(contracts),
            "total_value": total_value,
            "active": by_status.get("active", 0),
            "expiring": by_status.get("expiring", 0),
            "expired": by_status.get("expired", 0),
            "by_status": by_status,
            "by_category": by_category,
            "by_college": by_college,
        }
    )


@app.route("/api/alerts", methods=["GET"])
def alerts():
    window = config.ALERT_WINDOW_DAYS
    out = []
    for c in db.list_contracts():
        c = db.enrich(c)
        items = []
        di = c.get("days_to_insurance")
        de = c.get("days_to_end")
        dp = c.get("days_to_po_end")
        if di is not None and 0 <= di <= window:
            items.append({"kind": "insurance", "days": di, "date": c.get("ins")})
        if de is not None and 0 <= de <= window:
            items.append({"kind": "contract", "days": de, "date": c.get("end")})
        if dp is not None and 0 <= dp <= window:
            items.append({"kind": "po", "days": dp, "date": c.get("poEnd")})
        for it in items:
            out.append(
                {
                    "contract_id": c["id"],
                    "vendor": c.get("vendor"),
                    "college": c.get("college"),
                    "poly": c.get("poly"),
                    **it,
                }
            )
    out.sort(key=lambda a: a["days"])
    return jsonify(out)


def _demo_seed_if_empty():
    """Populate the in-memory store with sample data on first boot."""
    if not config.DEMO_MODE:
        return
    if db.list_contracts():
        return
    import seed

    n = seed.seed()
    log.info("demo mode: seeded %d sample contracts", n)


# Seed at import time so it also runs under `flask run` / gunicorn.
_demo_seed_if_empty()


if __name__ == "__main__":
    import os

    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    if config.DEMO_MODE:
        log.info("Starting in DEMO mode (in-memory backend, no AWS).")
    app.run(host="127.0.0.1", port=5000, debug=debug)
