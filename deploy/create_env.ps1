$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = "kiro-dev"
$env:AWS_REGION = "us-west-2"

$app = "contrackt"
$envName = "contrackt-env"
$label = (Get-Content .\deploy\_version_label.txt).Trim()
$stack = "64bit Amazon Linux 2023 v4.13.4 running Python 3.13"

Write-Output "Creating environment '$envName' with version '$label'..."
$create = aws elasticbeanstalk create-environment `
    --application-name $app `
    --environment-name $envName `
    --solution-stack-name $stack `
    --version-label $label `
    --option-settings file://deploy/options.json 2>&1
Write-Output ($create | Out-String)

Write-Output "=== polling until Ready (up to ~15 min) ==="
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 15
    $desc = aws elasticbeanstalk describe-environments --application-name $app --environment-names $envName --query "Environments[0].[Status,Health,CNAME]" --output text 2>&1
    Write-Output ("[{0,3}s] {1}" -f ($i * 15), $desc)
    if ($desc -match "^Ready") { break }
    if ($desc -match "^Terminated") { Write-Output "Environment terminated - creation failed"; break }
}

Write-Output "=== final status ==="
aws elasticbeanstalk describe-environments --application-name $app --environment-names $envName --query "Environments[0].[Status,Health,CNAME,EndpointURL]" --output text 2>&1
