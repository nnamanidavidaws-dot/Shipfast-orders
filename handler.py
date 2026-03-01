"""
order-publisher Lambda
Validates POST /orders payload and publishes to SNS.
Returns 202 Accepted (not 200) because processing is async —
the message is accepted for processing, not yet processed.
"""
import json
import os
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

sns = boto3.client("sns")
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]

REQUIRED_FIELDS = {"order_id", "email", "items"}


def validate_order(body: dict) -> list[str]:
    """Return list of validation error messages. Empty list = valid."""
    errors = []

    missing = REQUIRED_FIELDS - body.keys()
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")
        return errors   # No point checking types if fields are absent

    if not isinstance(body["order_id"], str) or not body["order_id"].strip():
        errors.append("order_id must be a non-empty string")

    if not isinstance(body["email"], str) or "@" not in body["email"]:
        errors.append("email must be a valid email address")

    if not isinstance(body["items"], list) or len(body["items"]) == 0:
        errors.append("items must be a non-empty list")

    return errors


def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))

    # Parse body
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Request body must be valid JSON"})

    # Validate
    errors = validate_order(body)
    if errors:
        logger.warning("Validation failed: %s", errors)
        return _response(400, {"error": "Validation failed", "details": errors})

    # Publish to SNS
    try:
        result = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(body),
            Subject="new-order",
            MessageAttributes={
                "event_type": {
                    "DataType": "String",
                    "StringValue": "order.created",
                }
            },
        )
        logger.info("Published to SNS. MessageId: %s", result["MessageId"])
    except ClientError as e:
        logger.error("SNS publish failed: %s", e)
        return _response(502, {"error": "Failed to queue order event"})

    # 202 = Accepted for async processing (not 200 = synchronously fulfilled)
    return _response(202, {"message": "Order accepted", "order_id": body["order_id"]})


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
