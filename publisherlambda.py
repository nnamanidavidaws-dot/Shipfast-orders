import json
import os
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel("INFO")

sns = boto3.client("sns")
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]

REQUIRED_FIELDS = {"order_id", "email", "items"}

def validate_order(body):
    errors = []
    missing = REQUIRED_FIELDS - body.keys()
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")
        return errors
    if not isinstance(body["order_id"], str) or not body["order_id"].strip():
        errors.append("order_id must be a non-empty string")
    if not isinstance(body["email"], str) or "@" not in body["email"]:
        errors.append("email must be a valid email address")
    if not isinstance(body["items"], list) or len(body["items"]) == 0:
        errors.append("items must be a non-empty list")
    return errors

def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Request body must be valid JSON"})
    errors = validate_order(body)
    if errors:
        return _response(400, {"error": "Validation failed", "details": errors})
    try:
        result = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(body),
            Subject="new-order"
        )
        logger.info("Published to SNS. MessageId: %s", result["MessageId"])
    except ClientError as e:
        logger.error("SNS publish failed: %s", e)
        return _response(502, {"error": "Failed to queue order event"})
    return _response(202, {"message": "Order accepted", "order_id": body["order_id"]})

def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }