import json
import os
import logging
import urllib.request

logger = logging.getLogger()
logger.setLevel("INFO")

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

def lambda_handler(event, context):
    batch_item_failures = []
    for record in event["Records"]:
        message_id = record["messageId"]
        try:
            order = _parse_message(record["body"])
            _post_to_slack(order)
            logger.info("Slack alert sent for order %s", order.get("order_id"))
        except Exception as e:
            logger.error("Failed to process message %s: %s", message_id, e)
            batch_item_failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": batch_item_failures}

def _parse_message(body):
    outer = json.loads(body)
    if "Message" in outer:
        return json.loads(outer["Message"])
    return outer

def _post_to_slack(order):
    if not SLACK_WEBHOOK_URL:
        raise ValueError("SLACK_WEBHOOK_URL environment variable not set")
    payload = {
        "text": f":package: New Order #{order.get('order_id')} from {order.get('email')} — {len(order.get('items', []))} item(s)"
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