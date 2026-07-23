"""Expiry alert emails via Amazon SES.

Builds a simple "this contract is about to expire in 30 days" message that
links back to the app and to both associated documents (agreement + COI), and
sends it to the contract head. For testing, delivery can be redirected to a
single verified address via ALERT_TEST_RECIPIENT (the head's real address is
still recorded on the message).
"""
import html as _html

import config
import db
from aws_clients import ses_client


def _doc_link(website_url, doc_id):
    # Link through the app so the URL never expires; the app 302-redirects to a
    # freshly signed S3 URL.
    return f"{website_url.rstrip('/')}/api/documents/{doc_id}/view"


def build_message(contract, agreement_id, coi_id, website_url):
    vendor = contract.get("vendor") or "this vendor"
    poly = contract.get("poly") or ""
    site = website_url.rstrip("/")

    lines_txt = [
        "This contract is about to expire in 30 days.",
        "",
        f"Contract: {vendor} {('(' + poly + ')') if poly else ''}".strip(),
        f"Open ConTrackt: {site}",
    ]
    if agreement_id:
        lines_txt.append(f"Agreement document: {_doc_link(site, agreement_id)}")
    if coi_id:
        lines_txt.append(f"Insurance (COI) document: {_doc_link(site, coi_id)}")
    body_text = "\n".join(lines_txt)

    def esc(s):
        return _html.escape(str(s or ""))

    doc_links_html = ""
    if agreement_id:
        doc_links_html += f'<li><a href="{_doc_link(site, agreement_id)}" target="_blank" rel="noopener">Agreement document</a></li>'
    if coi_id:
        doc_links_html += f'<li><a href="{_doc_link(site, coi_id)}" target="_blank" rel="noopener">Insurance (COI) document</a></li>'

    body_html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;color:#0f172a;font-size:15px;line-height:1.5">
  <p><strong>This contract is about to expire in 30 days.</strong></p>
  <p>Contract: {esc(vendor)} {('(' + esc(poly) + ')') if poly else ''}</p>
  <p><a href="{site}" target="_blank" rel="noopener" style="color:#1d4ed8">Open ConTrackt &rarr;</a></p>
  <ul>{doc_links_html}</ul>
  <p style="color:#64748b;font-size:12px">Automated alert from ConTrackt.</p>
</div>"""

    subject = f"Contract expiring in 30 days: {vendor}"
    return subject, body_text, body_html


def _send_ses(subject, body_text, body_html, to_address):
    resp = ses_client().send_email(
        Source=config.SES_FROM_EMAIL,
        Destination={"ToAddresses": [to_address]},
        Message={
            "Subject": {"Data": subject},
            "Body": {
                "Text": {"Data": body_text},
                "Html": {"Data": body_html},
            },
        },
    )
    return resp["MessageId"]


def _docs_by_contract():
    mapping = {}
    for d in db.list_documents():
        cid = d.get("contract_id")
        if not cid:
            continue
        slot = mapping.setdefault(cid, {"agreement": None, "coi": None})
        if d.get("type") == "coi" and not slot["coi"]:
            slot["coi"] = d["id"]
        elif d.get("type") != "coi" and not slot["agreement"]:
            slot["agreement"] = d["id"]
    return mapping


def notify_expiring(website_url, window=None):
    """Send alert emails for contracts expiring within the window.

    Idempotent: a contract's message id encodes its current dates, so it is not
    re-sent unless the dates change. Failed sends are retried on the next run.
    Returns a summary list of per-contract results.
    """
    window = window if window is not None else config.ALERT_WINDOW_DAYS
    docmap = _docs_by_contract()
    results = []

    for raw in db.list_contracts():
        c = db.enrich(raw, window=window)
        # does this contract have any alert inside the window?
        days = [c.get("days_to_end"), c.get("days_to_insurance"), c.get("days_to_po_end")]
        has_alert = any(d is not None and 0 <= d <= window for d in days)
        if not has_alert:
            continue

        mid = db.message_id_for(c)
        existing = db.get_message(mid)
        if existing and existing.get("send_status") in ("sent", "demo"):
            results.append({"contract_id": c["id"], "status": "already_sent", "message_id": mid})
            continue

        head_email = (c.get("contract_head_email") or "").strip()
        if not head_email:
            # No email on file: alert stays, but nothing is sent.
            results.append({"contract_id": c["id"], "status": "skipped_no_email"})
            continue

        docs = docmap.get(c["id"], {})
        agreement_id = docs.get("agreement")
        coi_id = docs.get("coi")
        subject, body_text, body_html = build_message(c, agreement_id, coi_id, website_url)
        actual = (config.ALERT_TEST_RECIPIENT or head_email).strip()

        record = {
            "id": mid,
            "contract_id": c["id"],
            "kind": "expiry",
            "to_email": head_email,
            "to_actual": actual,
            "subject": subject,
            "body_html": body_html,
            "body_text": body_text,
            "website_url": website_url.rstrip("/"),
            "agreement_doc_id": agreement_id,
            "coi_doc_id": coi_id,
        }

        if config.DEMO_MODE:
            record["send_status"] = "demo"
            db.create_message(record)
            results.append({"contract_id": c["id"], "status": "demo", "message_id": mid})
            continue

        if not config.SES_FROM_EMAIL:
            record["send_status"] = "failed"
            record["error"] = "SES_FROM_EMAIL not configured"
            db.create_message(record)
            results.append({"contract_id": c["id"], "status": "failed",
                            "error": record["error"], "message_id": mid})
            continue

        try:
            ses_id = _send_ses(subject, body_text, body_html, actual)
            record["send_status"] = "sent"
            record["ses_message_id"] = ses_id
            db.create_message(record)
            results.append({"contract_id": c["id"], "status": "sent", "message_id": mid})
        except Exception as e:  # noqa: BLE001
            record["send_status"] = "failed"
            record["error"] = str(e)
            db.create_message(record)
            results.append({"contract_id": c["id"], "status": "failed",
                            "error": str(e), "message_id": mid})

    return results
