"""AWS Lambda entrypoint for the web app behind API Gateway (HTTP API).

Bridges the existing WSGI app (app.app) to Lambda proxy events using apig-wsgi,
so every route continues to work while the app runs serverless instead of on a
long-running Flask/Elastic Beanstalk server.
"""
from apig_wsgi import make_lambda_handler

from app import app

# Auto-detects API Gateway payload format (v1/v2) and handles binary bodies
# (e.g. multipart uploads) via base64.
handler = make_lambda_handler(app)
