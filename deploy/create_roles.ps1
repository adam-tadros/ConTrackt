$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = "kiro-dev"
$env:AWS_REGION = "us-west-2"

$ec2Role = "contrackt-eb-ec2-role"
$instProfile = "contrackt-eb-ec2-profile"

# EC2 trust policy
'{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' |
    Out-File -Encoding ascii -NoNewline .\deploy\_ec2_trust.json

Write-Output "=== service-linked role for Elastic Beanstalk ==="
aws iam create-service-linked-role --aws-service-name elasticbeanstalk.amazonaws.com 2>&1 | Out-Null
Write-Output "  (created or already exists)"

Write-Output "=== EC2 instance role: $ec2Role ==="
aws iam create-role --role-name $ec2Role --assume-role-policy-document file://deploy/_ec2_trust.json 2>&1 | Out-Null
aws iam attach-role-policy --role-name $ec2Role --policy-arn arn:aws:iam::aws:policy/AWSElasticBeanstalkWebTier 2>&1 | Out-Null
# App runtime permissions (S3 / DynamoDB / Textract / Bedrock)
aws iam put-role-policy --role-name $ec2Role --policy-name ContracktRuntime --policy-document file://deploy/iam-policy.json 2>&1 | Out-Null
Write-Output "  role configured with WebTier + ContracktRuntime"

Write-Output "=== instance profile: $instProfile ==="
aws iam create-instance-profile --instance-profile-name $instProfile 2>&1 | Out-Null
aws iam add-role-to-instance-profile --instance-profile-name $instProfile --role-name $ec2Role 2>&1 | Out-Null
Write-Output "  instance profile ready"

Remove-Item .\deploy\_ec2_trust.json -ErrorAction SilentlyContinue

Write-Output "=== verify ==="
aws iam get-instance-profile --instance-profile-name $instProfile --query "InstanceProfile.Roles[].RoleName" --output text 2>&1
aws iam list-role-policies --role-name $ec2Role --query "PolicyNames" --output text 2>&1
aws iam list-attached-role-policies --role-name $ec2Role --query "AttachedPolicies[].PolicyName" --output text 2>&1
