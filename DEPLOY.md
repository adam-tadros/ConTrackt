# Deploying ConTrackt to AWS (Elastic Beanstalk)

This puts the Flask app on **Elastic Beanstalk** (EC2 + nginx + gunicorn) and
uses **DynamoDB, S3, Textract, and Bedrock** as the backend. The app
authenticates to AWS through the EB instance's **IAM role** — no access keys
live on the server.

> Run everything from the project root in PowerShell.

## 0. Prerequisites

```powershell
# AWS CLI configured with an admin-ish user (for provisioning + deploy)
aws configure                      # keys + default region (e.g. us-east-1)
aws sts get-caller-identity        # should print your account/user

# Install the Elastic Beanstalk CLI
pip install awsebcli
eb --version
```

Bedrock model access for `anthropic.claude-3-haiku-20240307-v1:0` must already
be enabled (you confirmed this) in the region you'll use for `BEDROCK_REGION`.

## 1. Create the data resources (once)

```powershell
python provision.py     # creates the S3 bucket + 2 DynamoDB tables
python aws_smoke.py     # expect: S3 / DynamoDB / Bedrock all OK
```

If `S3_BUCKET` (default `contrackt-documents`) is taken globally, set a unique
name in `.env` and re-run — then update `deploy/iam-policy.json` to match.

## 2. Initialize Elastic Beanstalk

```powershell
eb init
```

Pick: your **region**, **Create new application** (name `contrackt`), platform
**Python** (choose 3.11 or newer), and decline CodeCommit. Say yes to SSH if you
want shell access.

## 3. Create the environment

```powershell
eb create contrackt-env --single
```

`--single` uses one instance with no load balancer (cheapest for an MVP). Drop
it if you want a load-balanced, scalable environment. This takes a few minutes.

## 4. Grant the instance role permission to use AWS

The app calls S3/DynamoDB/Textract/Bedrock using the EC2 instance profile. Attach
the least-privilege policy in `deploy/iam-policy.json` to that role
(`aws-elasticbeanstalk-ec2-role` unless you set a custom one):

```powershell
aws iam put-role-policy `
  --role-name aws-elasticbeanstalk-ec2-role `
  --policy-name ContracktRuntime `
  --policy-document file://deploy/iam-policy.json
```

## 5. Set environment variables

```powershell
eb setenv `
  AWS_REGION=us-east-1 `
  BEDROCK_REGION=us-east-1 `
  BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0 `
  S3_BUCKET=contrackt-documents `
  DDB_CONTRACTS_TABLE=contrackt_contracts `
  DDB_DOCUMENTS_TABLE=contrackt_documents `
  SECRET_KEY=<put-a-long-random-string-here>
```

Do **not** set `CONTRACKT_DEMO` — leaving it unset runs against real AWS.

## 6. Deploy and open

```powershell
eb deploy
eb open
```

## 7. (Optional) Load the sample contracts

Run the seeder locally against the same live AWS resources — it uploads the real
sample PDFs to S3 and creates the linked records:

```powershell
python seed.py
```

Refresh the app and the dashboard, alerts, and Document Hub will be populated.

## Updating later

Commit or just save your changes, then:

```powershell
eb deploy
```

## Logs & troubleshooting

```powershell
eb logs
eb status
eb health
```

- **500s / "Unable to locate credentials"** → the instance role is missing the
  policy from step 4, or `AWS_REGION` is wrong.
- **Uploads fail at ~1MB** → the nginx limit; `.platform/nginx/conf.d/upload_size.conf`
  raises it to 25M and ships automatically. Confirm it deployed with `eb ssh`.
- **Bedrock AccessDenied** → model access not enabled in `BEDROCK_REGION`, or the
  policy's Bedrock statement is missing.

## Important security note

This MVP has **no authentication**. Before exposing it publicly:
- Put it behind auth (AWS Cognito, or at minimum an app-level login), and
- Serve over HTTPS (an Application Load Balancer + ACM certificate, or CloudFront).

## Teardown

```powershell
eb terminate contrackt-env
# then remove data resources if you no longer need them:
#   aws s3 rb s3://contrackt-documents --force
#   aws dynamodb delete-table --table-name contrackt_contracts
#   aws dynamodb delete-table --table-name contrackt_documents
```

## Event-driven parsing with AWS Lambda

Parsing runs in a Lambda function (`contrackt-parser`) triggered by S3 upload
events, instead of blocking the web request.

### How it works
1. Flask creates the document record (`parse_status=pending`), then writes the
   file to S3 under `uploads/`.
2. The S3 `ObjectCreated` event invokes the Lambda.
3. The Lambda finds the pending record, calls Bedrock/Textract (reusing
   `parser.py` + `db.py`), and writes the fields back with `parse_status=done`.
4. The browser polls `GET /api/documents/<id>` until parsing completes.

Enable it on the web tier by setting the environment variable:

```powershell
eb setenv ASYNC_PARSE=1      # or set it in the EB option settings
```

Without `ASYNC_PARSE` (and in demo mode), the app falls back to inline parsing.

### Deploying / updating the Lambda

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\deploy_lambda.ps1
```

This script (idempotent):
- packages `handler.py` + shared modules + a bundled boto3 into `deploy/lambda.zip`
- uploads it to S3
- creates/updates the `contrackt-lambda-role` (S3 read, DynamoDB documents
  read/write, Bedrock invoke, Textract, CloudWatch Logs — see
  `deploy/lambda-iam-policy.json`)
- creates/updates the `contrackt-parser` function (Python 3.13)
- grants S3 permission to invoke it and wires the `s3:ObjectCreated:*`
  notification on the `uploads/` prefix

### Troubleshooting the Lambda

```powershell
# tail logs
aws logs tail /aws/lambda/contrackt-parser --follow --profile kiro-dev --region us-west-2
```

- Document stuck on `pending` → the S3 notification or invoke permission is
  missing; re-run `deploy_lambda.ps1`.
- `parse_status=error` with an AccessDenied → the Lambda role is missing Bedrock
  or S3 permissions.

## Email alerts with Amazon SES

Contracts entering the 30-day expiry window trigger an email to the contract
head (if an email is on file). The message says the contract expires in 30 days
and links the app plus the agreement and COI documents. Each send is recorded so
the Alerts tab can link to the exact message.

### One-time setup

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\setup_ses.ps1
```

This provisions the `contrackt_messages` table, adds SES + messages permissions
to the instance role, requests SES identity verification, and backfills contract
heads on the sample data.

### Verify the sender/recipient (required — SES sandbox)

SES starts in the sandbox, so both the sender and recipient must be verified.
For testing we use one address for both. After running setup, open the inbox for
`user79490@gmail.com` and click the AWS verification link. Check status with:

```powershell
aws ses get-identity-verification-attributes --identities user79490@gmail.com --region us-west-2
```

Until it shows `Success`, sends are recorded with `send_status=failed`
("Email address is not verified") and retried on the next run.

### Relevant environment variables (set on the EB environment)

| Variable | Value |
|---|---|
| `SES_FROM_EMAIL` | verified sender (e.g. `user79490@gmail.com`) |
| `ALERT_TEST_RECIPIENT` | if set, all alert emails go here instead of the head's real address |
| `SES_REGION` | `us-west-2` |
| `WEBSITE_URL` | public app URL used in the email links |
| `DDB_MESSAGES_TABLE` | `contrackt_messages` |

To go beyond the sandbox (send to arbitrary contract-head addresses), request
SES production access in the console and remove `ALERT_TEST_RECIPIENT`.

### How emails are triggered

Opening the Alerts tab (or clicking **Send alert emails**) POSTs
`/api/alerts/notify`, which sends one email per expiring contract (idempotent per
contract's dates). For fully automated sending, schedule that call — e.g. an
EventBridge rule invoking a small Lambda that hits the endpoint daily.

## Serverless hosting: API Gateway + Lambda (replaces Elastic Beanstalk)

The web app now runs in AWS Lambda (`contrackt-web`) behind an API Gateway HTTP
API, instead of Flask on Elastic Beanstalk. Flask remains only as the internal
WSGI app; `web_lambda.py` bridges it to Lambda via **apig-wsgi**.

### Deploy / update

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\deploy_web.ps1
```

This (idempotently):
- packages the app + templates + static + deps into `deploy/web.zip`
- creates/updates the `contrackt-web-role` (same runtime permissions as
  `deploy/iam-policy.json`: S3, DynamoDB x3, Bedrock, Textract, SES)
- creates/updates the `contrackt-web` Lambda (Python 3.13, handler
  `web_lambda.handler`)
- quick-creates the `contrackt-api` HTTP API (catch-all `$default` route → Lambda)
- **grants API Gateway permission to invoke the Lambda** (quick-create does not
  always add this — the script adds it explicitly)
- sets `WEBSITE_URL` to the API URL and all app env vars

The public URL is printed at the end:
`https://<api-id>.execute-api.us-west-2.amazonaws.com`

### Notes / tradeoffs

- **Upload size**: API Gateway caps request payloads at 10 MB, so
  `MAX_UPLOAD_MB` is set to 8 on the Lambda. For larger files, switch uploads to
  presigned direct-to-S3 (client uploads straight to S3, then notifies the API).
- **Model**: `BEDROCK_MODEL_ID` is `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
  (a US cross-region inference profile). Model access must be enabled in Bedrock.
- **Two reminders**: alert emails fire at 30 days and again at 2 weeks before
  expiry (distinct, idempotent messages per stage).
- Decommission the old server with `eb terminate contrackt-env` or
  `aws elasticbeanstalk terminate-environment --environment-name contrackt-env`.
