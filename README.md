# ConTrackt — FHDA Contract & Insurance Manager (AWS MVP)

A Flask app for the Foothill–De Anza CCD that tracks agreements/contracts,
purchase orders, and certificates of insurance. Documents are stored in **S3**,
records live in **DynamoDB**, and uploaded files are parsed by **Amazon Bedrock**
(with **Textract** as a fallback).

## Features

- **Dashboard** — KPI cards (total, active, expiring, total value), breakdowns
  by category and campus, and a clickable Agreement/Contract–PO pairing table.
- **Upload & Extract** — drag/drop a PDF or image; it lands in S3 and an AI
  parses vendor, dates, value, scope, etc. Review/edit the fields, then save.
- **Alerts** — everything (insurance, contract end, PO end) expiring within 30 days.
- **Document Hub** — searchable list of current + archived documents; open any
  file through a time-limited presigned URL; archive/restore.

## Architecture

```
Browser (SPA: templates/index.html + static/js/app.js)
   │  JSON over fetch
   ▼
Flask (app.py)
   ├── db.py        → DynamoDB  (contracts, documents)
   ├── storage.py   → S3        (document files, presigned URLs)
   └── parser.py    → Bedrock Converse (PDF/image) → JSON  [Textract fallback]
```

Parsing runs **synchronously inside the upload request** (MVP choice — no Lambda
or S3-event wiring). The tradeoff is a slower upload response on large files.

## Prerequisites

- Python 3.11+ (developed on 3.14)
- An AWS account with permissions for S3, DynamoDB, Textract, and Bedrock
- **Bedrock model access enabled** for the model in `BEDROCK_MODEL_ID`
  (AWS console → Bedrock → Model access)

## Setup

```powershell
# 1. Create a virtualenv and install deps
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Configure environment
Copy-Item .env.example .env
#   edit .env  (or run `aws configure` to use a shared credentials profile)

# 3. Provision AWS resources (S3 bucket + 2 DynamoDB tables)
.\.venv\Scripts\python.exe provision.py

# 4. Confirm connectivity to all three services
.\.venv\Scripts\python.exe aws_smoke.py
#   expect:  S3 ✓ / DynamoDB ✓ / Bedrock ✓

# 5. (optional) Load sample FHDA data for the demo
.\.venv\Scripts\python.exe seed.py

# 6. Run the app
.\.venv\Scripts\python.exe app.py
#   open http://127.0.0.1:5000
```

Set `FLASK_DEBUG=1` before step 6 for the interactive debugger during development.

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `AWS_REGION` | `us-east-1` | Region for S3 + DynamoDB |
| `S3_BUCKET` | `contrackt-documents` | Bucket for uploaded documents |
| `DDB_CONTRACTS_TABLE` | `contrackt_contracts` | Contracts table |
| `DDB_DOCUMENTS_TABLE` | `contrackt_documents` | Documents table |
| `BEDROCK_REGION` | = `AWS_REGION` | Region where the model is enabled |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-haiku-20240307-v1:0` | Extraction model |
| `MAX_UPLOAD_MB` | `20` | Max upload size |
| `ALERT_WINDOW_DAYS` | `30` | Expiry alert window |
| `PRESIGN_EXPIRY` | `3600` | Presigned URL lifetime (seconds) |

## API

| Method | Route | Description |
|---|---|---|
| GET | `/api/contracts` | List contracts (with derived status) |
| GET | `/api/contracts/<id>` | One contract + linked document records |
| POST | `/api/contracts` | Create (pass `document_id` to link an upload) |
| PUT | `/api/contracts/<id>` | Update changed fields |
| GET | `/api/documents` | List documents |
| GET | `/api/documents/<id>/url` | Presigned view URL |
| PATCH | `/api/documents/<id>` | Update (e.g. `{"archived": true}`) |
| POST | `/api/upload` | Multipart upload → S3 + doc record + AI parse |
| GET | `/api/stats` | Dashboard aggregates |
| GET | `/api/alerts` | Items expiring within the window |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests run entirely offline — DynamoDB is replaced by an in-memory fake and the
S3/Bedrock/Textract calls are monkeypatched, so no AWS credentials are needed.

## Notes & next steps

- **No authentication** in this MVP. Do not expose it publicly as-is; add
  Cognito (or at minimum a login gate) before deploying.
- The S3 bucket is created with public access fully blocked; files are only
  reachable through short-lived presigned URLs.
- To move parsing off the request path later, replace the synchronous call in
  `/api/upload` with an S3 event → Lambda pipeline that writes parsed fields back
  to DynamoDB and have the UI poll for status.
```
