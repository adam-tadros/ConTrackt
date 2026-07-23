$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = "kiro-dev"
$env:AWS_REGION = "us-west-2"

$fn = "contrackt-parser"
$role = "contrackt-lambda-role"
$bucket = "contrackt-docs-221889532759"
$account = "221889532759"
$build = "deploy\lambda_build"
$zip = "deploy\lambda.zip"

Write-Output "=== build package ==="
if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Path $build | Out-Null
Copy-Item handler.py, parser.py, db.py, config.py, aws_clients.py $build -ErrorAction SilentlyContinue
Copy-Item lambda\handler.py $build\handler.py -Force
# bundle boto3 (guarantees the Converse API is available)
.\.venv\Scripts\python.exe -m pip install boto3 -t $build --quiet --disable-pip-version-check
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$build\*" -DestinationPath $zip
$zipMB = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Output "  package: $zip ($zipMB MB)"

Write-Output "=== upload package to S3 ==="
aws s3 cp $zip "s3://$bucket/eb-app/lambda.zip" 2>&1 | Out-Null

Write-Output "=== IAM role ==="
'{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' |
    Out-File -Encoding ascii -NoNewline .\deploy\_lambda_trust.json
aws iam create-role --role-name $role --assume-role-policy-document file://deploy/_lambda_trust.json 2>&1 | Out-Null
aws iam attach-role-policy --role-name $role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>&1 | Out-Null
aws iam put-role-policy --role-name $role --policy-name ContracktParser --policy-document file://deploy/lambda-iam-policy.json 2>&1 | Out-Null
Remove-Item .\deploy\_lambda_trust.json -ErrorAction SilentlyContinue
$roleArn = "arn:aws:iam::${account}:role/$role"
Write-Output "  role: $roleArn"
Write-Output "  waiting for role propagation..."
Start-Sleep -Seconds 15

Write-Output "=== create/update function ==="
$exists = aws lambda get-function --function-name $fn 2>&1
if ($LASTEXITCODE -eq 0) {
    aws lambda update-function-code --function-name $fn --s3-bucket $bucket --s3-key eb-app/lambda.zip 2>&1 | Out-Null
    Start-Sleep -Seconds 5
    aws lambda update-function-configuration --function-name $fn --handler handler.handler --timeout 120 --memory-size 512 --environment "Variables={BEDROCK_REGION=us-west-2,BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0,DDB_DOCUMENTS_TABLE=contrackt_documents,DDB_CONTRACTS_TABLE=contrackt_contracts}" 2>&1 | Out-Null
    Write-Output "  updated existing function"
}
else {
    aws lambda create-function --function-name $fn --runtime python3.13 --role $roleArn --handler handler.handler --timeout 120 --memory-size 512 --code "S3Bucket=$bucket,S3Key=eb-app/lambda.zip" --environment "Variables={BEDROCK_REGION=us-west-2,BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0,DDB_DOCUMENTS_TABLE=contrackt_documents,DDB_CONTRACTS_TABLE=contrackt_contracts}" 2>&1 | Out-Null
    Write-Output "  created function"
}
Start-Sleep -Seconds 5
$fnArn = aws lambda get-function --function-name $fn --query "Configuration.FunctionArn" --output text 2>&1
Write-Output "  function ARN: $fnArn"

Write-Output "=== allow S3 to invoke the function ==="
aws lambda add-permission --function-name $fn --statement-id s3invoke --action "lambda:InvokeFunction" --principal s3.amazonaws.com --source-arn "arn:aws:s3:::$bucket" --source-account $account 2>&1 | Out-Null
Write-Output "  permission added (or already present)"

Write-Output "=== configure S3 -> Lambda notification (prefix uploads/) ==="
$notif = @"
{
  "LambdaFunctionConfigurations": [
    {
      "LambdaFunctionArn": "$fnArn",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": { "Key": { "FilterRules": [ { "Name": "prefix", "Value": "uploads/" } ] } }
    }
  ]
}
"@
$notif | Out-File -Encoding ascii -NoNewline .\deploy\_notif.json
aws s3api put-bucket-notification-configuration --bucket $bucket --notification-configuration file://deploy/_notif.json 2>&1
Remove-Item .\deploy\_notif.json -ErrorAction SilentlyContinue

Write-Output "=== DONE. Verify: ==="
aws lambda get-function --function-name $fn --query "Configuration.[FunctionName,Runtime,State,LastUpdateStatus]" --output text 2>&1
