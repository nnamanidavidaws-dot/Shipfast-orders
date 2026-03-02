import json
import os
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel("INFO")

ses = boto3.client("ses")
FROM_ADDRESS = os.environ.get("SES_FROM_ADDRESS", "orders@shipfast.example.com")

def lambda_handler(event, context):
    batch_item_failures = []
    for record in event["Records"]:
        message_id = record["messageId"]
        try:
            order = _parse_message(record["body"])
            _send_email(order)
            logger.info("Email sent for order %s", order.get("order_id"))
        except Exception as e:
            logger.error("Failed to process message %s: %s", message_id, e)
            batch_item_failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": batch_item_failures}

def _parse_message(body):
    outer = json.loads(body)
    if "Message" in outer:
        return json.loads(outer["Message"])
    return outer

def _send_email(order):
    ses.send_email(
        Source=FROM_ADDRESS,
        Destination={"ToAddresses": [order["email"]]},
        Message={
            "Subject": {"Data": f"Order Confirmed — #{order['order_id']}"},
            "Body": {
                "Text": {"Data": f"Your order #{order['order_id']} has been received.\nItems: {order.get('items')}"}
            },
        },
    )