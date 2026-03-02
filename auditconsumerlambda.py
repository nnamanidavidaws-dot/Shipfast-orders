import json
import os
import logging
import datetime

logger = logging.getLogger()
logger.setLevel("INFO")

def lambda_handler(event, context):
    batch_item_failures = []
    for record in event["Records"]:
        message_id = record["messageId"]
        try:
            order = _parse_message(record["body"])
            _write_audit(order, record)
        except Exception as e:
            logger.error("Failed to audit message %s: %s", message_id, e)
            batch_item_failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": batch_item_failures}

def _parse_message(body):
    outer = json.loads(body)
    if "Message" in outer:
        return json.loads(outer["Message"])
    return outer

def _write_audit(order, record):
    entry = {
        "audit": {
            "event_type": "order.created",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "order_id": order.get("order_id"),
            "customer_email": order.get("email"),
            "item_count": len(order.get("items", [])),
            "items": order.get("items", []),
            "sqs_message_id": record.get("messageId"),
        }
    }
    print(json.dumps(entry))
    logger.info("Audit record written for order %s", order.get("order_id"))