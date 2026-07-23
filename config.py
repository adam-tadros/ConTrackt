"""Central configuration for the ConTrackt MVP.

All values are read from environment variables (optionally loaded from a local
.env file) so the same code runs locally and, later, in a deployed environment.
"""
import os

try:
    # python-dotenv is optional at runtime but recommended for local dev.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv simply not installed
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Demo / offline mode --------------------------------------------------
# When enabled, AWS (DynamoDB/S3/Bedrock) is replaced by an in-memory backend
# so the app runs with no credentials. Set CONTRACKT_DEMO=1 to enable.
DEMO_MODE = os.environ.get("CONTRACKT_DEMO", "").lower() in ("1", "true", "yes")

# --- AWS core -------------------------------------------------------------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# --- S3 -------------------------------------------------------------------
S3_BUCKET = os.environ.get("S3_BUCKET", "contrackt-documents")
S3_UPLOAD_PREFIX = os.environ.get("S3_UPLOAD_PREFIX", "uploads/")
PRESIGN_EXPIRY = _int("PRESIGN_EXPIRY", 3600)  # seconds

# --- DynamoDB -------------------------------------------------------------
DDB_CONTRACTS_TABLE = os.environ.get("DDB_CONTRACTS_TABLE", "contrackt_contracts")
DDB_DOCUMENTS_TABLE = os.environ.get("DDB_DOCUMENTS_TABLE", "contrackt_documents")
DDB_MESSAGES_TABLE = os.environ.get("DDB_MESSAGES_TABLE", "contrackt_messages")

# --- Bedrock / AI ---------------------------------------------------------
# Model must support the Converse API with document input blocks and must be
# enabled for your account in BEDROCK_REGION.
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", AWS_REGION)
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

# --- Textract (fallback path) --------------------------------------------
TEXTRACT_REGION = os.environ.get("TEXTRACT_REGION", AWS_REGION)

# --- SES email alerts -----------------------------------------------------
SES_REGION = os.environ.get("SES_REGION", AWS_REGION)
# Verified SES sender identity (in sandbox, must be verified).
SES_FROM_EMAIL = os.environ.get("SES_FROM_EMAIL", "")
# For testing: if set, ALL alert emails are delivered here instead of the
# contract head's real address (the head's address is still recorded).
ALERT_TEST_RECIPIENT = os.environ.get("ALERT_TEST_RECIPIENT", "")
# Public base URL used in email links; falls back to the request host.
WEBSITE_URL = os.environ.get("WEBSITE_URL", "")

# --- App behaviour --------------------------------------------------------
# When true (and not demo), uploads are parsed asynchronously by the Lambda
# triggered on S3 upload; the app returns immediately and the UI polls.
ASYNC_PARSE = os.environ.get("ASYNC_PARSE", "").lower() in ("1", "true", "yes")

MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 20)
ALERT_WINDOW_DAYS = _int("ALERT_WINDOW_DAYS", 30)
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "tiff", "tif"}

# Flask
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
