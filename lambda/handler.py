"""AWS Lambda: parse a document when it lands in S3.

Trigger: S3 ObjectCreated on the uploads/ prefix of the documents bucket.

Flow:
  1. Read the S3 object key from the event.
  2. Find the matching DynamoDB document record (created by the Flask app just
     before it wrote the object) that is still in `parse_status == "pending"`.
  3. Download the object and run the shared parser (Bedrock Converse, Textract
     fallback).
  4. Write the extracted fields back onto the document record and set
     `parse_status = "done"` (or "error").

This reuses the same `parser.py` and `db.py` modules as the web app, so parsing
behaviour is identical. boto3 is bundled in the deployment package; python-dotenv
is optional (config.py imports it defensively).
"""
import urllib.parse

import boto3

import db
import parser as ai_parser

_s3 = boto3.client("s3")


def _find_pending_doc(s3_key):
    for d in db.list_documents():
        if d.get("s3_key") == s3_key:
            return d
    return None


def handler(event, context):
    results = []
    for record in event.get("Records", []):
        try:
            bucket = record["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        except (KeyError, TypeError):
            continue

        doc = _find_pending_doc(key)
        if not doc:
            results.append({"key": key, "action": "skip", "reason": "no matching document"})
            continue
        if doc.get("parse_status") != "pending":
            results.append({"key": key, "action": "skip", "reason": f"status={doc.get('parse_status')}"})
            continue

        db.update_document(doc["id"], {"parse_status": "processing"})
        try:
            body = _s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            fields = ai_parser.parse_document(
                body, doc.get("filename") or key, doc.get("content_type")
            )
            db.update_document(
                doc["id"], {"parse_status": "done", "parsed_fields": fields}
            )
            results.append({"key": key, "action": "parsed", "doc_id": doc["id"]})
        except Exception as e:  # noqa: BLE001
            db.update_document(
                doc["id"], {"parse_status": "error", "parse_error": str(e)}
            )
            results.append({"key": key, "action": "error", "error": str(e)})

    return {"results": results}
