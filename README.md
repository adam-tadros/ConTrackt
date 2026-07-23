# ConTrackt — FHDA Contract & Insurance Manager

A serverless web app for the Foothill–De Anza Community College District (FHDA)
that tracks agreements/contracts, purchase orders, and certificates of insurance
(COIs) — and uses AI to read uploaded documents so staff don't have to key the
details in by hand.

Live: `https://u06har030f.execute-api.us-west-2.amazonaws.com`

## The problem it solves

Community college districts sign hundreds of vendor agreements, each with an
associated purchase order and a certificate of insurance that must stay current.
Today that information typically lives in scattered PDFs, shared drives, and
spreadsheets, which makes three things hard:

- **Nothing is tracked in one place.** Contract terms, PO numbers, dollar
  values, and insurance expiration dates are buried inside documents.
- **Expirations get missed.** An expired COI or lapsed contract can create real
  liability, and there's no automatic reminder before a deadline.
- **Manual data entry is slow and error-prone.** Someone has to open each PDF
  and copy the vendor, dates, and values into a system.

ConTrackt addresses this by giving the district a single dashboard where:

1. Documents are **uploaded once** and stored securely in the cloud.
2. **AI extracts** the key fields (vendor, category, dates, value, scope,
   summary) automatically; a person just reviews and corrects them.
3. **Expiration alerts** fire 30 days and again 2 weeks before a contract or
   insurance policy lapses, emailing the responsible "contract head."
4. Everything — agreements paired with their POs and COIs — is **searchable and
   linked**, so the source document is always one click away.

## Features

- **Dashboard** — KPI cards (total, active, expiring, total value), breakdowns
  by category and campus, and a clickable Agreement/Contract–PO pairing table.
- **Upload & Extract** — drag/drop a PDF or image; it's stored in S3 and parsed
  by AI. Review/edit the extracted fields beside a live preview, then save.
- **Alerts** — insurance, contract-end, and PO-end dates expiring within 30
  days. The contract head is emailed at 30 days and again at 2 weeks; each alert
  is clickable to view the exact message sent.
- **Document Hub** — searchable list of current + archived documents; open any
  file through a time-limited presigned URL; archive/restore.
- **Fully responsive** — works on large desktops down to phones (mobile-first
  layout, hamburger nav, touch-friendly, safe-area aware).

## Architecture

Fully **serverless on AWS**. The browser talks to an HTTP API Gateway that
fronts a Lambda running the app; a second Lambda parses documents in the
background when they land in S3.

```
Browser (responsive SPA: templates/index.html + static/)
   │  JSON over fetch  (+ polls parse status)
   ▼
Amazon API Gateway (HTTP API)
   ▼
Lambda: contrackt-web   (Flask app bridged to Lambda via apig-wsgi)
   ├── db.py           → DynamoDB   (contracts, documents, messages)
   ├── storage.py      → S3         (document files, presigned URLs)
   └── notifications.py→ SES        (30-day + 2-week alert emails)

Upload path (event-driven):
   contrackt-web  →  puts file in S3
                        │  (S3 ObjectCreated event, uploads/ prefix)
                        ▼
   Lambda: contrackt-parser
        → Bedrock Converse (Claude Sonnet 4.5) on the document  [Textract fallback]
        → writes extracted fields back to the DynamoDB document record
   Browser polls GET /api/documents/<id> until parse_status = done
```

### Components

| Piece | Role |
|---|---|
| **API Gateway (HTTP API)** | Public entry point; routes everything to the web Lambda |
| **Lambda `contrackt-web`** | Runs the whole site + JSON API (Flask via `apig-wsgi`) |
| **Lambda `contrackt-parser`** | S3-triggered; extracts fields with Bedrock/Textract |
| **Amazon S3** | Stores uploaded documents; served only via presigned URLs |
| **Amazon DynamoDB** | 3 tables: `contracts`, `documents`, `messages` (sent alerts) |
| **Amazon Bedrock** | Claude Sonnet 4.5 reads the document → structured JSON |
| **Amazon Textract** | OCR fallback when the direct document parse fails |
| **Amazon SES** | Sends the two-stage expiry reminder emails |
| **AWS IAM** | Least-privilege roles per Lambda; no long-lived keys in the app |

### Codebase

| File | Responsibility |
|---|---|
| `app.py` | Flask routes / JSON API |
| `web_lambda.py` | Lambda entrypoint (wraps `app` with `apig-wsgi`) |
| `lambda/handler.py` | The `contrackt-parser` handler |
| `db.py` | DynamoDB data access + status/alert logic |
| `storage.py` | S3 upload + presigned URLs |
| `parser.py` | Bedrock/Textract extraction |
| `notifications.py` | Builds + sends SES alert emails |
| `config.py` / `aws_clients.py` | Env config + boto3 clients |
| `provision.py` / `seed.py` / `aws_smoke.py` | Provision resources, seed data, connectivity check |
| `deploy/*.ps1` | Deployment scripts (web Lambda, parser Lambda, IAM, API) |

## Tech stack

Python 3 · Flask (via apig-wsgi on Lambda) · boto3 · vanilla HTML/CSS/JS
(mobile-first) · AWS API Gateway, Lambda, S3, DynamoDB, Bedrock, Textract, SES ·
pytest. A **demo mode** (`CONTRACKT_DEMO=1`) swaps AWS for an in-memory backend
so the app runs with zero credentials.

## Local development

```powershell
# 1. Virtualenv + deps
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2a. Zero-setup preview (no AWS needed) — in-memory data, stubbed parsing
$env:CONTRACKT_DEMO=1
.\.venv\Scripts\python.exe app.py        # http://127.0.0.1:5000

# --- or ---

# 2b. Run against real AWS
Copy-Item .env.example .env              # set region, bucket, model, profile
.\.venv\Scripts\python.exe provision.py  # S3 bucket + DynamoDB tables
.\.venv\Scripts\python.exe aws_smoke.py  # expect S3 / DynamoDB / Bedrock OK
.\.venv\Scripts\python.exe seed.py       # optional sample data
.\.venv\Scripts\python.exe app.py
```

## Deployment

The live app is serverless (API Gateway + Lambda). Full step-by-step
instructions — provisioning, IAM, the web and parser Lambdas, SES verification,
and env vars — are in **[DEPLOY.md](DEPLOY.md)**. In short:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\deploy_web.ps1     # web app
powershell -ExecutionPolicy Bypass -File .\deploy\deploy_lambda.ps1  # parser
```

> Publishing to GitHub (`git push`) and deploying to AWS (the scripts above) are
> separate steps — pushing code does not update the live site.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `AWS_REGION` | Region for S3 + DynamoDB (deployment uses `us-west-2`) |
| `S3_BUCKET` | Bucket for uploaded documents |
| `DDB_CONTRACTS_TABLE` / `DDB_DOCUMENTS_TABLE` / `DDB_MESSAGES_TABLE` | DynamoDB tables |
| `BEDROCK_REGION` / `BEDROCK_MODEL_ID` | Bedrock region + model (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) |
| `ASYNC_PARSE` | `1` = event-driven parsing via the parser Lambda |
| `SES_FROM_EMAIL` / `ALERT_TEST_RECIPIENT` / `SES_REGION` | Alert email sender, test recipient override, SES region |
| `WEBSITE_URL` | Public URL used in email links |
| `MAX_UPLOAD_MB` / `ALERT_WINDOW_DAYS` / `PRESIGN_EXPIRY` | Upload cap, alert window, presigned URL lifetime |
| `CONTRACKT_DEMO` | `1` = in-memory demo mode (no AWS) |

## API

| Method | Route | Description |
|---|---|---|
| GET | `/api/contracts` | List contracts (with derived status) |
| GET/POST/PUT | `/api/contracts[/<id>]` | Read / create / update contracts |
| GET | `/api/documents` | List documents |
| GET/PATCH | `/api/documents/<id>` | Get record (incl. parse status) / update |
| GET | `/api/documents/<id>/url` | Presigned view URL (JSON) |
| GET | `/api/documents/<id>/view` | 302 redirect to a fresh presigned URL (email-safe) |
| POST | `/api/upload` | Upload → S3 + document record (+ async parse) |
| GET | `/api/stats` | Dashboard aggregates |
| GET | `/api/alerts` | Items expiring within the window (+ email state) |
| POST | `/api/alerts/notify` | Send due alert emails (idempotent per stage) |
| GET | `/api/messages/<id>` | View a sent alert message |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

48 tests, fully offline — DynamoDB is an in-memory fake and S3/Bedrock/Textract/
SES calls are monkeypatched, so no AWS credentials are needed.

## Security notes

- **No authentication yet.** The app is publicly reachable; add AWS Cognito (or
  at minimum a login gate) before real use.
- The S3 bucket blocks all public access; documents are reachable only through
  short-lived presigned URLs.
- Alert email delivery uses SES; in the sandbox, sender/recipient must be
  verified (a test recipient override routes all mail to one inbox).
