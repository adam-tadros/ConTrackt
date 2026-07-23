$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = "kiro-dev"
$env:AWS_REGION = "us-west-2"

$app = "contrackt"
$envName = "contrackt-env"
$bucket = "contrackt-docs-221889532759"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$label = "v-$stamp"
$zip = "deploy\bundle-$label.zip"

Write-Output "=== build bundle from committed code ==="
git archive --format=zip -o $zip HEAD
aws s3 cp $zip "s3://$bucket/eb-app/$label.zip" 2>&1 | Out-Null
aws elasticbeanstalk create-application-version --application-name $app --version-label $label --source-bundle "S3Bucket=$bucket,S3Key=eb-app/$label.zip" --process 2>&1 | Out-Null
Write-Output "  version: $label"

Write-Output "=== update environment (new version + ASYNC_PARSE=1) ==="
aws elasticbeanstalk update-environment `
    --environment-name $envName `
    --version-label $label `
    --option-settings "Namespace=aws:elasticbeanstalk:application:environment,OptionName=ASYNC_PARSE,Value=1" 2>&1 | Out-Null

Write-Output "=== polling until Ready ==="
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 15
    $desc = aws elasticbeanstalk describe-environments --application-name $app --environment-names $envName --query "Environments[0].[Status,Health,VersionLabel]" --output text 2>&1
    Write-Output ("[{0,3}s] {1}" -f ($i * 15), $desc)
    if ($desc -match "^Ready") { break }
}
Remove-Item $zip -ErrorAction SilentlyContinue
Write-Output "=== final ==="
aws elasticbeanstalk describe-environments --application-name $app --environment-names $envName --query "Environments[0].[Status,Health,VersionLabel,CNAME]" --output text 2>&1
