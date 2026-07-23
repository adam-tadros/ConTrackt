$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = "kiro-dev"
$env:AWS_REGION = "us-west-2"

# Scheduled "daily alerts" Lambda: sends 30-day and 14-day expiry reminders once
# per day via an EventBridge rule. Reuses the web Lambda's IAM role (it already
# has DynamoDB + SES permissions). Idempotent per stage, so daily runs are safe.

$fn = "contrackt-alerts"
$role = "contrackt-web-role"                 # reuse: has DynamoDB + SES access
$bucket = "contrackt-docs-221889532759"
$account = "221889532759"
$region = "us-west-2"
$ruleName = "contrackt-daily-alerts"
$schedule = "cron(0 13 * * ? *)"             # 13:00 UTC daily (~6am PT)
$build = "deploy\alerts_build"
$zip = "deploy\alerts.zip"
$model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# Resolve the public URL for email links (falls back to the known API URL).
$apiUrl = "https://u06har030f.execute-api.us-west-2.amazonaws.com"
if (Test-Path .\deploy\_web_api_id.txt) {
    $apiId = (Get-Content .\deploy\_web_api_id.txt).Trim()
    if ($apiId) { $apiUrl = "https://$apiId.execute-api.$region.amazonaws.com" }
}

Write-Output "=== build package ==="
if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Path $build | Out-Null
Copy-Item alerts_lambda.py, notifications.py, db.py, config.py, aws_clients.py, memstore.py $build
.\.venv\Scripts\python.exe -m pip install boto3 -t $build --quiet --disable-pip-version-check
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$build\*" -DestinationPath $zip
Write-Output ("  package: {0} ({1} MB)" -f $zip, [math]::Round((Get-Item $zip).Length / 1MB, 1))
aws s3 cp $zip "s3://$bucket/eb-app/alerts.zip" 2>&1 | Out-Null

$roleArn = "arn:aws:iam::${account}:role/$role"
$envVars = "Variables={BEDROCK_MODEL_ID=$model,BEDROCK_REGION=$region,S3_BUCKET=$bucket,DDB_CONTRACTS_TABLE=contrackt_contracts,DDB_DOCUMENTS_TABLE=contrackt_documents,DDB_MESSAGES_TABLE=contrackt_messages,SES_FROM_EMAIL=user79490@gmail.com,ALERT_TEST_RECIPIENT=user79490@gmail.com,SES_REGION=$region,ALERT_WINDOW_DAYS=30,WEBSITE_URL=$apiUrl}"

Write-Output "=== create/update function ==="
$exists = aws lambda get-function --function-name $fn 2>&1
if ($LASTEXITCODE -eq 0) {
    aws lambda update-function-code --function-name $fn --s3-bucket $bucket --s3-key eb-app/alerts.zip 2>&1 | Out-Null
    Start-Sleep -Seconds 6
    aws lambda update-function-configuration --function-name $fn --handler alerts_lambda.handler --timeout 60 --memory-size 256 --environment $envVars 2>&1 | Out-Null
    Write-Output "  updated"
}
else {
    aws lambda create-function --function-name $fn --runtime python3.13 --role $roleArn --handler alerts_lambda.handler --timeout 60 --memory-size 256 --code "S3Bucket=$bucket,S3Key=eb-app/alerts.zip" --environment $envVars 2>&1 | Out-Null
    Write-Output "  created"
}
Start-Sleep -Seconds 8
$fnArn = aws lambda get-function --function-name $fn --query "Configuration.FunctionArn" --output text 2>&1
Write-Output "  function ARN: $fnArn"

Write-Output "=== EventBridge daily schedule ==="
aws events put-rule --name $ruleName --schedule-expression "$schedule" --description "ConTrackt: send 30/14-day expiry alert emails once a day" 2>&1 | Out-Null
$ruleArn = aws events describe-rule --name $ruleName --query "Arn" --output text 2>&1
Write-Output "  rule: $ruleArn ($schedule)"

# Allow EventBridge to invoke the Lambda.
aws lambda add-permission --function-name $fn --statement-id events-daily-invoke --action lambda:InvokeFunction --principal events.amazonaws.com --source-arn $ruleArn 2>&1 | Out-Null

# Point the rule at the Lambda.
aws events put-targets --rule $ruleName --targets "Id=1,Arn=$fnArn" 2>&1 | Out-Null
Write-Output "  target set -> $fn"

Write-Output ""
Write-Output "=== DONE ==="
aws lambda get-function --function-name $fn --query "Configuration.[FunctionName,Runtime,State,LastUpdateStatus]" --output text 2>&1
Write-Output "Schedule: $schedule (daily). Emails go to ALERT_TEST_RECIPIENT while testing."
