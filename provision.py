"""Provision the AWS resources ConTrackt needs.

Creates (idempotently):
  * the S3 bucket for uploaded documents
  * the DynamoDB `contracts` table
  * the DynamoDB `documents` table (with a contract_id GSI)

Run once after configuring AWS credentials:

    python provision.py

Bedrock model access must be enabled separately in the AWS console
(Bedrock -> Model access) for the model in config.BEDROCK_MODEL_ID.
"""
import sys
import time

import botocore

import config
from aws_clients import dynamodb_client, s3_client


def create_bucket():
    s3 = s3_client()
    bucket = config.S3_BUCKET
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"S3 bucket already exists: {bucket}")
        return
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code not in ("404", "NoSuchBucket", "NotFound"):
            # 403 etc. -> surface it
            print(f"Could not verify bucket {bucket}: {e}")

    kwargs = {"Bucket": bucket}
    if config.AWS_REGION != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {
            "LocationConstraint": config.AWS_REGION
        }
    s3.create_bucket(**kwargs)
    # Block public access - documents are served via presigned URLs only.
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    print(f"Created S3 bucket: {bucket}")


def _table_exists(ddb, name):
    try:
        ddb.describe_table(TableName=name)
        return True
    except ddb.exceptions.ResourceNotFoundException:
        return False


def create_contracts_table():
    ddb = dynamodb_client()
    name = config.DDB_CONTRACTS_TABLE
    if _table_exists(ddb, name):
        print(f"DynamoDB table already exists: {name}")
        return
    ddb.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
    )
    print(f"Creating DynamoDB table: {name} ...")


def create_documents_table():
    ddb = dynamodb_client()
    name = config.DDB_DOCUMENTS_TABLE
    if _table_exists(ddb, name):
        print(f"DynamoDB table already exists: {name}")
        return
    ddb.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "contract_id", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "contract_id-index",
                "KeySchema": [
                    {"AttributeName": "contract_id", "KeyType": "HASH"}
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    print(f"Creating DynamoDB table: {name} ...")


def wait_active():
    ddb = dynamodb_client()
    for name in (config.DDB_CONTRACTS_TABLE, config.DDB_DOCUMENTS_TABLE):
        for _ in range(30):
            try:
                desc = ddb.describe_table(TableName=name)
                if desc["Table"]["TableStatus"] == "ACTIVE":
                    break
            except ddb.exceptions.ResourceNotFoundException:
                pass
            time.sleep(2)
        print(f"Table active: {name}")


def main():
    print(f"Region: {config.AWS_REGION}")
    create_bucket()
    create_contracts_table()
    create_documents_table()
    wait_active()
    print("\nProvisioning complete.")
    print(
        "Reminder: enable Bedrock model access for "
        f"'{config.BEDROCK_MODEL_ID}' in region {config.BEDROCK_REGION}."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # pragma: no cover
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
