"""AI extraction of contract fields from an uploaded document.

Primary path: Bedrock Converse API with the document sent as a document/image
content block -> the model returns strict JSON.

Fallback path: Textract extracts raw text from the document, then Bedrock maps
that text to JSON.

`map_model_text` is a pure function (no AWS) so the mapping logic is unit
tested independently of the model call.
"""
import json
import re
import time

import config
from aws_clients import bedrock_runtime, textract_client

# Keys we ask the model to return; mirrors db.CONTRACT_FIELDS (minus summary,
# which we also request).
EXTRACT_KEYS = [
    "poly", "vendor", "cat", "sub", "college",
    "scope", "summary", "start", "end", "value",
    "po", "poEnd", "ins", "addl",
]

PROMPT = (
    "You are an assistant that extracts structured data from a contract, "
    "purchase order, or certificate of insurance for a community college "
    "district. Read the attached document and return ONLY a JSON object "
    "(no prose, no markdown fences) with these keys:\n"
    '  "poly": agreement or policy number,\n'
    '  "vendor": vendor / counterparty name,\n'
    '  "cat": high-level category (e.g. Construction, Services, Software, Insurance),\n'
    '  "sub": subcategory / type of work,\n'
    '  "college": campus if stated (Foothill, De Anza, or District),\n'
    '  "scope": one-sentence scope of work,\n'
    '  "summary": a 1-2 sentence plain-language summary,\n'
    '  "start": contract start date as YYYY-MM-DD,\n'
    '  "end": contract end date as YYYY-MM-DD,\n'
    '  "value": total dollar value as a number (no symbols or commas),\n'
    '  "po": purchase order number,\n'
    '  "poEnd": purchase order end date as YYYY-MM-DD,\n'
    '  "ins": insurance / COI expiration date as YYYY-MM-DD,\n'
    '  "addl": "Yes" or "No" for additional insured endorsement.\n'
    "Use null for any field you cannot find. Do not guess dates."
)

_IMAGE_FORMATS = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "gif": "gif"}


def _ext(filename: str) -> str:
    return (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""


def map_model_text(text: str) -> dict:
    """Parse the model's text output into a normalized field dict.

    Tolerant of markdown code fences and surrounding prose. Never raises;
    returns blank/normalized fields on failure so the UI degrades gracefully.
    """
    result = {k: None for k in EXTRACT_KEYS}
    if not text:
        return result
    raw = text.strip()
    # strip ```json ... ``` fences if present
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    # grab the outermost JSON object
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return result
    try:
        parsed = json.loads(raw[start:end + 1])
    except (ValueError, TypeError):
        return result
    if not isinstance(parsed, dict):
        return result

    for k in EXTRACT_KEYS:
        v = parsed.get(k)
        if v in ("", "null", "N/A", "n/a"):
            v = None
        result[k] = v

    # coerce value to a number when possible
    if result.get("value") is not None:
        result["value"] = _coerce_number(result["value"])
    return result


def _coerce_number(v):
    if isinstance(v, (int, float)):
        return v
    try:
        cleaned = re.sub(r"[^0-9.\-]", "", str(v))
        return float(cleaned) if cleaned not in ("", "-", ".") else None
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------
# Bedrock path
# --------------------------------------------------------------------------
def _bedrock_document(data: bytes, filename: str) -> str:
    ext = _ext(filename)
    if ext in _IMAGE_FORMATS:
        block = {
            "image": {
                "format": _IMAGE_FORMATS[ext],
                "source": {"bytes": data},
            }
        }
    else:
        # treat everything else as a PDF document block
        block = {
            "document": {
                "format": "pdf",
                "name": "document",
                "source": {"bytes": data},
            }
        }
    resp = bedrock_runtime().converse(
        modelId=config.BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [block, {"text": PROMPT}]}],
        inferenceConfig={"maxTokens": 1200, "temperature": 0},
    )
    return resp["output"]["message"]["content"][0]["text"]


def _bedrock_from_text(text: str) -> str:
    resp = bedrock_runtime().converse(
        modelId=config.BEDROCK_MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {"text": PROMPT},
                    {"text": "DOCUMENT TEXT:\n" + text[:15000]},
                ],
            }
        ],
        inferenceConfig={"maxTokens": 1200, "temperature": 0},
    )
    return resp["output"]["message"]["content"][0]["text"]


# --------------------------------------------------------------------------
# Textract fallback (sync for images, detect for single blob)
# --------------------------------------------------------------------------
def _textract_text(data: bytes) -> str:
    resp = textract_client().detect_document_text(Document={"Bytes": data})
    lines = [
        b["Text"]
        for b in resp.get("Blocks", [])
        if b.get("BlockType") == "LINE"
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def _demo_fields(filename: str) -> dict:
    """Canned extraction for demo mode (no Bedrock call)."""
    from datetime import date, timedelta

    stem = (filename or "document").rsplit(".", 1)[0]
    vendor = stem.replace("_", " ").replace("-", " ").strip().title() or "Sample Vendor"
    today = date.today()
    return {
        "poly": "DEMO-" + str(abs(hash(filename)) % 9000 + 1000),
        "vendor": vendor,
        "cat": "Services",
        "sub": "General",
        "college": "District",
        "scope": "Auto-filled in demo mode (no AI call was made).",
        "summary": f"Demo record generated from '{filename}'. Edit any field before saving.",
        "start": today.isoformat(),
        "end": (today + timedelta(days=365)).isoformat(),
        "value": 100000,
        "po": "PO-DEMO",
        "poEnd": (today + timedelta(days=365)).isoformat(),
        "ins": (today + timedelta(days=20)).isoformat(),
        "addl": "Yes",
        "_meta": {"ok": True, "method": "demo"},
    }


def parse_document(data: bytes, filename: str, content_type: str = None) -> dict:
    """Return extracted fields plus a `_meta` dict describing which path ran."""
    if config.DEMO_MODE:
        return _demo_fields(filename)
    # 1) Bedrock with the document/image directly
    try:
        text = _bedrock_document(data, filename)
        fields = map_model_text(text)
        fields["_meta"] = {"method": "bedrock_document", "ok": True}
        return fields
    except Exception as bedrock_err:  # noqa: BLE001
        first_error = f"{type(bedrock_err).__name__}: {bedrock_err}"

    # 2) Textract -> Bedrock text
    try:
        raw = _textract_text(data)
        text = _bedrock_from_text(raw)
        fields = map_model_text(text)
        fields["_meta"] = {"method": "textract_bedrock", "ok": True}
        return fields
    except Exception as fallback_err:  # noqa: BLE001
        fields = {k: None for k in EXTRACT_KEYS}
        fields["_meta"] = {
            "method": "none",
            "ok": False,
            "error": first_error,
            "fallback_error": f"{type(fallback_err).__name__}: {fallback_err}",
        }
        return fields
