"""
slack-consumer Lambda
Posts order alerts to the ShipFast ops Slack channel.
SLACK_WEBHOOK_URL is injected via environment variable — never hardcoded.
"""
import json
import os
import logging
import urllib.request
import urllib.error

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# NEVER hardcode webhook URLs — always read from environment
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")


def lambda_handler(event, context):
    batch_item_failures = []

    for record in event["Records"]:
        message_id = record["messageId"]
        try:
            order = _parse_sns_wrapped_message(record["body"])
            _post_to_slack(order)
            logger.info("Slack alert sent for order %s", order.get("order_id"))
        except Exception as e:
            logger.error("Failed to process message %s: %s", message_id, e)
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}


def _parse_sns_wrapped_message(body: str) -> dict:
    outer = json.loads(body)
    if "Message" in outer:
        return json.loads(outer["Message"])
    return outer


def _post_to_slack(order: dict):
    if not SLACK_WEBHOOK_URL:
        raise ValueError("SLACK_WEBHOOK_URL environment variable not set")

    order_id = order.get("order_id", "UNKNOWN")
    email = order.get("email", "unknown")
    item_count = len(order.get("items", []))

    payload = {
        "text": f":package: *New Order Received*",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":package: *New Order — #{order_id}*\n"
                        f"Customer: `{email}`\n"
                        f"Items: {item_count}"
                    ),
                },
            }
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Slack responded with HTTP {resp.status}")
