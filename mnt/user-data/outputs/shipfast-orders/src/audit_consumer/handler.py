"""
audit-consumer Lambda
Writes structured JSON audit records to CloudWatch Logs.
Every order event produces a machine-parseable log entry that can be
queried with CloudWatch Logs Insights.
"""
import json
import os
import logging
import datetime

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def lambda_handler(event, context):
    batch_item_failures = []

    for record in event["Records"]:
        message_id = record["messageId"]
        try:
            order = _parse_sns_wrapped_message(record["body"])
            _write_audit_log(order, record)
        except Exception as e:
            logger.error("Failed to audit message %s: %s", message_id, e)
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}


def _parse_sns_wrapped_message(body: str) -> dict:
    outer = json.loads(body)
    if "Message" in outer:
        return json.loads(outer["Message"])
    return outer


def _write_audit_log(order: dict, record: dict):
    """
    Emit a structured JSON audit entry.
    Using print() here ensures it goes directly to stdout → CloudWatch Logs
    as a single log line, making it easy to query with Logs Insights.

    Example query:
      fields @timestamp, audit.order_id, audit.email
      | filter audit.event_type = "order.created"
      | sort @timestamp desc
    """
    audit_entry = {
        "audit": {
            "event_type": "order.created",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "order_id": order.get("order_id"),
            "customer_email": order.get("email"),
            "item_count": len(order.get("items", [])),
            "items": order.get("items", []),
            "sqs_message_id": record.get("messageId"),
            "sqs_queue": record.get("eventSourceARN", "").split(":")[-1],
        }
    }
    # Single-line JSON → CloudWatch Logs Insights can parse it
    print(json.dumps(audit_entry))
    logger.info("Audit record written for order %s", order.get("order_id"))
