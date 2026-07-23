$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = "kiro-dev"
$env:AWS_REGION = "us-west-2"

$app = "contrackt"
$bucket = "contrackt-docs-221889532759"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$label = "v-$stamp"
$zip = "deploy\bundle-$label.zip"

Write-Output "=== build source bundle (tracked files only) ==="
# git archive => only committed files, so .venv/.env/etc are excluded automatically
git archive --format=zip -o $zip HEAD
if (-not (Test-Path $zip)) { Write-Output "BUNDLE FAILED"; exit 1 }
$sizeMB = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Output "  bundle: $zip ($sizeMB MB)"

Write-Output "=== upload bundle to S3 ==="
$key = "eb-app/$label.zip"
aws s3 cp $zip "s3://$bucket/$key" 2>&1 | Out-Null
Write-Output "  s3://$bucket/$key"

Write-Output "=== create EB application (idempotent) ==="
aws elasticbeanstalk create-application --application-name $app 2>&1 | Out-Null
Write-Output "  application: $app"

Write-Output "=== create application version $label ==="
aws elasticbeanstalk create-application-version --application-name $app --version-label $label --source-bundle "S3Bucket=$bucket,S3Key=$key" --process 2>&1 | Out-Null
Write-Output "  version: $label"

# hand the label to the next step
$label | Out-File -Encoding ascii -NoNewline .\deploy\_version_label.txt
Write-Output "DONE label=$label"
