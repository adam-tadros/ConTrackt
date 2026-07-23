"""Connectivity smoke test for the three AWS services ConTrackt uses.

    python aws_smoke.py

Prints a checklist so you can confirm credentials + resources are wired up
before running the app.
"""
import sys
import uuid

import config
from aws_clients import bedrock_runtime, dynamodb_resource, s3_client


def check_s3():
    s3 = s3_client()
    key = f"_smoke/{uuid.uuid4().hex}.txt"
    s3.put_object(Bucket=config.S3_BUCKET, Key=key, Body=b"contrackt smoke")
    body = s3.get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read()
    s3.delete_object(Bucket=config.S3_BUCKET, Key=key)
    assert body == b"contrackt smoke"


def check_dynamodb():
    ddb = dynamodb_resource()
    table = ddb.Table(config.DDB_CONTRACTS_TABLE)
    item_id = f"_smoke_{uuid.uuid4().hex}"
    table.put_item(Item={"id": item_id, "vendor": "smoke"})
    got = table.get_item(Key={"id": item_id}).get("Item")
    table.delete_item(Key={"id": item_id})
    assert got and got["vendor"] == "smoke"


def check_bedrock():
    br = bedrock_runtime()
    resp = br.converse(
        modelId=config.BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": "Reply with: ok"}]}],
        inferenceConfig={"maxTokens": 10, "temperature": 0},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    assert text.strip() != ""


def main():
    checks = [
        ("S3", check_s3),
        ("DynamoDB", check_dynamodb),
        ("Bedrock", check_bedrock),
    ]
    ok = True
    for name, fn in checks:
        try:
            fn()
            print(f"{name} \u2713")
        except Exception as e:
            ok = False
            print(f"{name} \u2717  {type(e).__name__}: {e}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
