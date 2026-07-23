# ConTrackt — Project Overview

**ConTrackt** is a contract and insurance management application for the
Foothill–De Anza Community College District (FHDA). It tracks agreements,
purchase orders, and certificates of insurance (COIs); stores the source
documents in the cloud; and uses AI to extract structured data from uploaded
files so staff don't have to key it in by hand.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, **Flask** (WSGI app) |
| AWS access | **boto3** (AWS SDK for Python) |
| AI extraction | **Amazon Bedrock** (Claude 3 Haiku) via the Converse API, with **Amazon Textract** as a fallback |
| Data store | **Amazon DynamoDB** (NoSQL) |
| Document store | **Amazon S3** |
| Frontend | Vanilla HTML / CSS / JavaScript (single-page UI, no framework) |
| Config | Environment variables via **python-dotenv** |
| Production server | **gunicorn** behind **nginx** |
| Hosting (target) | **AWS Elastic Beanstalk** (single EC2 instance) |
| Tests | **pytest** (33 tests, run fully offline with in-memory/mocked AWS) |

A built-in **demo mode** (`CONTRACKT_DEMO=1`) swaps all AWS calls for an
in-memory backend, so the app runs with zero credentials for local previews.

---

## AWS Services

| Service | Role in ConTrackt |
|---|---|
| **Amazon S3** | Stores uploaded documents (contracts, POs, COIs). Files are private; the app serves them through short-lived **presigned URLs**. Bucket has all public access blocked. |
| **Amazon DynamoDB** | Two tables: `contracts` (agreement records + derived status) and `documents` (file metadata, S3 keys, links to contracts, with a `contract_id` index). Billed on-demand (pay-per-request). |
| **Amazon Bedrock** | Runs Claude 3 Haiku to read an uploaded document and return structured JSON (vendor, dates, value, scope, summary, etc.). |
| **Amazon Textract** | Fallback OCR path: extracts raw text from a document, which is then sent to Bedrock if the direct document parse fails. |
| **AWS IAM** | A least-privilege policy grants the app access only to the specific bucket, tables, Textract, and Bedrock actions it needs. In production the app authenticates via the EC2 instance role (no keys on the server). |
| **AWS Elastic Beanstalk** | Deployment target: provisions EC2 + nginx + gunicorn and runs the Flask app. |

---

## Basic Workflow

### Uploading and parsing a document
1. A user drops a PDF or image on the **Upload** tab.
2. Flask stores the file in **S3** and creates a **DynamoDB** document record.
3. Flask sends the file to **Bedrock** (Textract fallback) and gets back
   structured fields — synchronously, in the same request.
4. The extracted fields appear in an editable form **beside a live preview** of
   the document. The user corrects anything the AI missed.
5. On save, Flask writes a **contract** record to DynamoDB and links it to the
   uploaded document.

### Everyday use
- **Dashboard** shows KPIs, category/campus breakdowns, and a table of
  agreement–PO pairings. Clicking a row opens a detail drawer.
- **Alerts** lists everything (insurance, contract, or PO) expiring within 30
  days — computed server-side from the stored dates.
- **Document Hub** provides search across all files, a current/archived toggle,
  and inline viewing via presigned URLs.

```
Browser (SPA)
   │  fetch (JSON)
   ▼
Flask  ── db.py ──────────▶ DynamoDB   (contracts, documents)
       ── storage.py ─────▶ S3         (files + presigned URLs)
       └─ parser.py ──────▶ Bedrock / Textract  (extract fields)
```

---

## Capabilities

- **Dashboard & statistics** — totals, active/expiring/expired counts, total
  contract value, and breakdowns by category and campus.
- **Agreement–PO pairing view** — clickable pairings with a full detail drawer
  and inline editing of any field.
- **Document upload to S3** — drag-and-drop for PDFs and images, with size and
  file-type validation.
- **AI field extraction** — automatic parsing of vendor, category, dates, value,
  scope, and a plain-language summary from the uploaded document, all
  user-editable afterward.
- **Side-by-side review** — the source document renders next to the extracted
  fields during upload.
- **Multi-document viewer** — the detail drawer and Document Hub open an embedded
  viewer with tabs for a contract and its matching COI.
- **30-day expiration alerts** — for insurance (COI), contract end, and PO end
  dates, with severity based on days remaining.
- **Searchable Document Hub** — search by filename, type, or vendor; toggle
  between current and archived documents; archive/restore.
- **Status tracking** — each contract is automatically classified as active,
  expiring, expired, or unknown based on its end date.

---

## Current Status

- Running locally against **live AWS** (DynamoDB + S3 + Bedrock) in `us-west-2`,
  seeded with 15 sample contracts and 28 documents.
- Elastic Beanstalk deployment artifacts are prepared (see `DEPLOY.md`).
- **No authentication yet** — a login/authorization layer (e.g. AWS Cognito) is
  required before any public deployment.
