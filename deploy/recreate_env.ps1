$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = "kiro-dev"
$env:AWS_REGION = "us-west-2"

$app = "contrackt"
$envName = "contrackt-env"
$label = (Get-Content .\deploy\_version_label.txt).Trim()
$stack = "64bit Amazon Linux 2023 v4.13.4 running Python 3.13"

Write-Output "=== terminating failed environment ==="
aws elasticbeanstalk terminate-environment --environment-name $envName 2>&1 | Out-Null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 15
    $st = aws elasticbeanstalk describe-environments --application-name $app --environment-names $envName --query "Environments[0].Status" --output text 2>&1
    Write-Output ("  term [{0,3}s] {1}" -f ($i * 15), $st)
    if ($st -match "Terminated" -or $st -match "None" -or [string]::IsNullOrWhiteSpace($st)) { break }
}

Write-Output "=== recreating environment with VPC settings ==="
aws elasticbeanstalk create-environment `
    --application-name $app `
    --environment-name $envName `
    --solution-stack-name $stack `
    --version-label $label `
    --option-settings file://deploy/options.json 2>&1 | Out-Null

Write-Output "=== polling until Ready + Green (up to ~15 min) ==="
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 15
    $desc = aws elasticbeanstalk describe-environments --application-name $app --environment-names $envName --query "Environments[0].[Status,Health,CNAME]" --output text 2>&1
    Write-Output ("[{0,3}s] {1}" -f ($i * 15), $desc)
    if ($desc -match "^Ready") { break }
    if ($desc -match "^Terminated") { Write-Output "FAILED - terminated"; break }
}

Write-Output "=== final ==="
aws elasticbeanstalk describe-environments --application-name $app --environment-names $envName --query "Environments[0].[Status,Health,CNAME]" --output text 2>&1
Write-Output "=== last events ==="
aws elasticbeanstalk describe-events --application-name $app --environment-name $envName --max-items 12 --query "Events[].[Severity,Message]" --output text 2>&1
