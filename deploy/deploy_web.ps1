$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = "kiro-dev"
$env:AWS_REGION = "us-west-2"

$fn = "contrackt-web"
$role = "contrackt-web-role"
$bucket = "contrackt-docs-221889532759"
$account = "221889532759"
$region = "us-west-2"
$apiName = "contrackt-api"
$build = "deploy\web_build"
$zip = "deploy\web.zip"
$model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

Write-Output "=== build package ==="
if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Path $build | Out-Null
Copy-Item app.py, config.py, db.py, storage.py, parser.py, notifications.py, aws_clients.py, memstore.py, web_lambda.py $build
Copy-Item -Recurse templates $build\templates
Copy-Item -Recurse static $build\static
.\.venv\Scripts\python.exe -m pip install flask apig-wsgi boto3 python-dotenv -t $build --quiet --disable-pip-version-check
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$build\*" -DestinationPath $zip
Write-Output ("  package: {0} ({1} MB)" -f $zip, [math]::Round((Get-Item $zip).Length / 1MB, 1))
aws s3 cp $zip "s3://$bucket/eb-app/web.zip" 2>&1 | Out-Null

Write-Output "=== IAM role ==="
'{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' |
    Out-File -Encoding ascii -NoNewline .\deploy\_web_trust.json
aws iam create-role --role-name $role --assume-role-policy-document file://deploy/_web_trust.json 2>&1 | Out-Null
aws iam attach-role-policy --role-name $role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>&1 | Out-Null
aws iam put-role-policy --role-name $role --policy-name ContracktWeb --policy-document file://deploy/iam-policy.json 2>&1 | Out-Null
Remove-Item .\deploy\_web_trust.json -ErrorAction SilentlyContinue
$roleArn = "arn:aws:iam::${account}:role/$role"
Write-Output "  $roleArn"
Start-Sleep -Seconds 15

$envVars = "Variables={ASYNC_PARSE=1,BEDROCK_MODEL_ID=$model,BEDROCK_REGION=$region,S3_BUCKET=$bucket,DDB_CONTRACTS_TABLE=contrackt_contracts,DDB_DOCUMENTS_TABLE=contrackt_documents,DDB_MESSAGES_TABLE=contrackt_messages,SES_FROM_EMAIL=user79490@gmail.com,ALERT_TEST_RECIPIENT=user79490@gmail.com,SES_REGION=$region,MAX_UPLOAD_MB=8,SECRET_KEY=ck-prod-2f9c1a7b4e6d8093}"

Write-Output "=== create/update function ==="
$exists = aws lambda get-function --function-name $fn 2>&1
if ($LASTEXITCODE -eq 0) {
    aws lambda update-function-code --function-name $fn --s3-bucket $bucket --s3-key eb-app/web.zip 2>&1 | Out-Null
    Start-Sleep -Seconds 6
    aws lambda update-function-configuration --function-name $fn --handler web_lambda.handler --timeout 30 --memory-size 1024 --environment $envVars 2>&1 | Out-Null
    Write-Output "  updated"
}
else {
    aws lambda create-function --function-name $fn --runtime python3.13 --role $roleArn --handler web_lambda.handler --timeout 30 --memory-size 1024 --code "S3Bucket=$bucket,S3Key=eb-app/web.zip" --environment $envVars 2>&1 | Out-Null
    Write-Output "  created"
}
Start-Sleep -Seconds 8
$lambdaArn = aws lambda get-function --function-name $fn --query "Configuration.FunctionArn" --output text 2>&1

Write-Output "=== HTTP API Gateway ==="
$apiId = aws apigatewayv2 get-apis --query "Items[?Name=='$apiName'].ApiId | [0]" --output text 2>&1
if ($apiId -and $apiId -ne "None") {
    Write-Output "  reusing API $apiId"
}
else {
    # quick-create: HTTP API + catch-all $default route + integration + invoke permission
    $apiId = aws apigatewayv2 create-api --name $apiName --protocol-type HTTP --target $lambdaArn --query "ApiId" --output text 2>&1
    Write-Output "  created API $apiId"
}
$url = "https://$apiId.execute-api.$region.amazonaws.com"

# Ensure API Gateway may invoke the Lambda (quick-create doesn't always add it).
aws lambda add-permission --function-name $fn --statement-id apigw-invoke --action lambda:InvokeFunction --principal apigateway.amazonaws.com --source-arn "arn:aws:execute-api:${region}:${account}:$apiId/*/*" 2>&1 | Out-Null

Write-Output "=== set WEBSITE_URL and finalize env ==="
$envWithUrl = $envVars.Substring(0, $envVars.Length - 1) + ",WEBSITE_URL=$url}"
aws lambda update-function-configuration --function-name $fn --environment $envWithUrl 2>&1 | Out-Null

$apiId | Out-File -Encoding ascii -NoNewline .\deploy\_web_api_id.txt
Write-Output ""
Write-Output "=== DONE ==="
Write-Output "API URL: $url"
