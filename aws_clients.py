"""Lazy, cached boto3 client/resource factories.

Keeping construction lazy means the app (and unit tests) can import modules
without immediately requiring AWS credentials. Clients are created on first
use and reused afterwards.
"""
from functools import lru_cache

import boto3

import config


@lru_cache(maxsize=1)
def s3_client():
    # Force the regional endpoint + SigV4 so presigned URLs point at
    # bucket.s3.<region>.amazonaws.com. Without this, buckets outside
    # us-east-1 return a redirect that presigned URLs can't follow.
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name=config.AWS_REGION,
        endpoint_url=f"https://s3.{config.AWS_REGION}.amazonaws.com",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


@lru_cache(maxsize=1)
def dynamodb_resource():
    return boto3.resource("dynamodb", region_name=config.AWS_REGION)


@lru_cache(maxsize=1)
def dynamodb_client():
    return boto3.client("dynamodb", region_name=config.AWS_REGION)


@lru_cache(maxsize=1)
def bedrock_runtime():
    return boto3.client("bedrock-runtime", region_name=config.BEDROCK_REGION)


@lru_cache(maxsize=1)
def textract_client():
    return boto3.client("textract", region_name=config.TEXTRACT_REGION)


@lru_cache(maxsize=1)
def ses_client():
    return boto3.client("ses", region_name=config.SES_REGION)


def reset_caches():
    """Clear cached clients (used by tests that inject fakes)."""
    for fn in (
        s3_client,
        dynamodb_resource,
        dynamodb_client,
        bedrock_runtime,
        textract_client,
        ses_client,
    ):
        fn.cache_clear()
