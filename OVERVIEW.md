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
| AI extraction | **Amazon Bedrock** (Claude Sonnet 4.5) via the Converse API, with **Amazon Textract** as a fallback |
| Async parsing | **AWS Lambda** triggered by S3 upload events |
| Data store | **Amazon DynamoDB** (NoSQL) |
| Document store | **Amazon S3** |
| Frontend | Vanilla HTML / CSS / JavaScript (single-page UI, no framework) |
| Config | Environment variables via **python-dotenv** |
| Web runtime | **AWS Lambda** running the WSGI app via **apig-wsgi** |
| Hosting | **Amazon API Gateway** (HTTP API) + **AWS Lambda** — serverless, deployed and live |
| Tests | **pytest** (48 tests, run fully offline with in-memory/mocked AWS) |

A built-in **demo mode** (`CONTRACKT_DEMO=1`) swaps all AWS calls for an
in-memory backend, so the app runs with zero credentials for local previews.

---

## AWS Services

| Service | Role in ConTrackt |
|---|---|
| **Amazon S3** | Stores uploaded documents (contracts, POs, COIs). Files are private; the app serves them through short-lived **presigned URLs**. Bucket has all public access blocked. |
| **Amazon DynamoDB** | Two tables: `contracts` (agreement records + derived status) and `documents` (file metadata, S3 keys, links to contracts, with a `contract_id` index). Billed on-demand (pay-per-request). |
| **AWS Lambda** | Two functions: `contrackt-web` runs the whole web app/API (behind API Gateway), and `contrackt-parser` is triggered by S3 uploads to parse documents and write results back to DynamoDB. |
| **Amazon API Gateway** | HTTP API that fronts the `contrackt-web` Lambda — this is the public entry point for the site and JSON API (replaces the old Elastic Beanstalk server). |
| **Amazon Bedrock** | Runs **Claude Sonnet 4.5** to read an uploaded document and return structured JSON (vendor, dates, value, scope, summary, etc.). Invoked from the parser Lambda (or inline in demo mode). |
| **Amazon Textract** | Fallback OCR path: extracts raw text from a document, which is then sent to Bedrock if the direct document parse fails. |
| **Amazon SES** | Sends expiry-alert emails to the contract head. Each sent message is recorded (subject, body, recipient, status) so it can be reviewed from the Alerts tab. |
| **AWS IAM** | Least-privilege policies grant the EC2 instance role and the Lambda role access only to the specific bucket, tables, Textract, and Bedrock actions each needs. No credentials live on the server. |
| **Amazon SES** — reminders | Alert emails are sent at **30 days** and again at **2 weeks** before expiry (two reminders per contract). |

---

## Basic Workflow

### Uploading and parsing a document (event-driven)
1. A user drops a PDF or image on the **Upload** tab.
2. Flask creates a **DynamoDB** document record with `parse_status = pending`,
   then writes the file to **S3**.
3. The S3 upload event triggers the **Lambda** function, which reads the file,
   calls **Bedrock** (Textract fallback), and writes the extracted fields back
   onto the document record (`parse_status = done`).
4. Meanwhile the browser **polls** the document; when parsing completes, the
   fields appear in an editable form **beside a live preview** of the document.
   The user corrects anything the AI missed.
5. On save, Flask writes a **contract** record to DynamoDB and links it to the
   uploaded document.

> In demo mode (no AWS), parsing runs inline with a stub so the flow still works.

### Everyday use
- **Dashboard** shows KPIs, category/campus breakdowns, and a table of
  agreement–PO pairings. Clicking a row opens a detail drawer.
- **Alerts** lists everything (insurance, contract, or PO) expiring within 30
  days — computed server-side from the stored dates.
- **Document Hub** provides search across all files, a current/archived toggle,
  and inline viewing via presigned URLs.

```
Browser (SPA)
   │  fetch (JSON) + poll parse_status
   ▼
API Gateway (HTTP API)
   ▼
Lambda: contrackt-web  (WSGI app via apig-wsgi)
   ├─ db.py ──────▶ DynamoDB   (contracts, documents, messages)
   ├─ notifications ▶ SES  (30-day + 2-week alert emails)
   └─ storage.py ─▶ S3 ──(ObjectCreated event)──▶ Lambda: contrackt-parser
                        (files, presigned URLs)        │
                                                        ├─▶ Bedrock (Claude Sonnet 4.5) / Textract
                                                        └─▶ writes fields back to DynamoDB
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
- **Email alerts to the contract head** — each contract has a contract head and
  (optionally) an email. An SES email is sent at **30 days** before expiry and a
  second reminder at **2 weeks**, linking the app and both the agreement and COI
  documents. Contracts without an email still show an alert; no email is sent.
  Alert boxes are clickable to view the exact message sent.
- **Searchable Document Hub** — search by filename, type, or vendor; toggle
  between current and archived documents; archive/restore.
- **Status tracking** — each contract is automatically classified as active,
  expiring, expired, or unknown based on its end date.

---

## Current Status

- **Deployed and live, fully serverless** in `us-west-2`: Amazon API Gateway +
  AWS Lambda (`contrackt-web`), with S3, DynamoDB, the `contrackt-parser`
  Lambda, Bedrock (Claude Sonnet 4.5), and SES. The old Elastic Beanstalk
  environment has been decommissioned.
- Document parsing runs on **Claude Sonnet 4.5** via Bedrock (real AI, not a
  deterministic parser); demo mode keeps an inline stub for credential-free runs.
- Alert emails go out at **30 days** and again at **2 weeks** before expiry.
- **No authentication yet** — a login/authorization layer (e.g. AWS Cognito) is
  strongly recommended, since the app is publicly reachable.
