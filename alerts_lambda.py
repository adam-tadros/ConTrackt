"""Scheduled Lambda entrypoint for sending expiry-alert emails.

Invoked once a day by an Amazon EventBridge rule -- NOT by anyone visiting the
site. It sends the 30-day and 14-day reminders for contracts crossing those
thresholds. Sending is idempotent per stage (the message id encodes the
contract's dates + stage), so running every day never double-sends: a contract
gets exactly one 30-day email and one 14-day email.
"""
import config
import notifications


def handler(event, context):
    results = notifications.notify_expiring(config.WEBSITE_URL)
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    # Surfaced in CloudWatch Logs for each daily run.
    print(f"[contrackt-alerts] processed={len(results)} summary={summary}")
    return {"ok": True, "processed": len(results), "summary": summary}
