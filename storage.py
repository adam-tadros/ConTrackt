"""S3 storage helpers: upload bytes, presign for viewing, delete."""
import uuid

import config
from aws_clients import s3_client


def _safe_name(filename: str) -> str:
    keep = "-_.() "
    cleaned = "".join(c for c in (filename or "file") if c.isalnum() or c in keep)
    return cleaned.strip().replace(" ", "_") or "file"


def build_key(filename: str) -> str:
    return f"{config.S3_UPLOAD_PREFIX}{uuid.uuid4().hex}_{_safe_name(filename)}"


def upload_bytes(data: bytes, filename: str, content_type: str) -> str:
    """Upload raw bytes to S3 (or the in-memory store) and return the key."""
    key = build_key(filename)
    if config.DEMO_MODE:
        import memstore
        memstore.BLOBS[key] = (data, content_type or "application/octet-stream")
        return key
    s3_client().put_object(
        Bucket=config.S3_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type or "application/octet-stream",
    )
    return key


def presigned_url(key: str, expiry: int = None, download_name: str = None) -> str:
    """Return a time-limited GET URL for the object."""
    if config.DEMO_MODE:
        from urllib.parse import quote
        return "/demo/file/" + quote(key, safe="")
    params = {"Bucket": config.S3_BUCKET, "Key": key}
    if download_name:
        params["ResponseContentDisposition"] = f'inline; filename="{download_name}"'
    return s3_client().generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expiry or config.PRESIGN_EXPIRY,
    )


def get_bytes(key: str) -> bytes:
    if config.DEMO_MODE:
        import memstore
        return memstore.BLOBS.get(key, (b"", ""))[0]
    obj = s3_client().get_object(Bucket=config.S3_BUCKET, Key=key)
    return obj["Body"].read()


def delete_object(key: str):
    s3_client().delete_object(Bucket=config.S3_BUCKET, Key=key)
