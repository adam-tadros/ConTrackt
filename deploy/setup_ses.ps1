$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = "kiro-dev"
$env:AWS_REGION = "us-west-2"

Write-Output "=== 1. provision (adds contrackt_messages table; idempotent) ==="
.\.venv\Scripts\python.exe provision.py

Write-Output "=== 2. update instance role policy (adds SES + messages table) ==="
aws iam put-role-policy --role-name contrackt-eb-ec2-role --policy-name ContracktRuntime --policy-document file://deploy/iam-policy.json 2>&1
Write-Output "  role policy updated"

Write-Output "=== 3. verify SES identity user79490@gmail.com ==="
aws ses verify-email-identity --email-address user79490@gmail.com --region us-west-2 2>&1
Write-Output "  verification email requested"

Write-Output "=== 4. backfill contract heads on existing contracts ==="
.\.venv\Scripts\python.exe -c "import seed; seed.backfill_heads()"

Write-Output "=== SES identity status ==="
aws ses get-identity-verification-attributes --identities user79490@gmail.com --region us-west-2 --output text 2>&1
