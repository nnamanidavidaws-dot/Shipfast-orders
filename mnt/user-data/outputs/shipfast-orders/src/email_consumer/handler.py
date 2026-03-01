"""
email-consumer Lambda
Reads from email-queue and sends order confirmation emails via SES.
Uses ReportBatchItemFailures to handle partial batch failures correctly:
only failed messages are retried, not the whole batch.
"""
import json
import os
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

ses = boto3.client("ses")
FROM_ADDRESS = os.environ.get("SES_FROM_ADDRESS", "orders@shipfast.example.com")


def lambda_handler(event, context):
    """
    SQS trigger with ReportBatchItemFailures enabled.
    Must return {"batchItemFailures": [...]} for any failed records.
    This tells SQS to only re-queue the specific failed messages,
    not the entire batch.
    """
    batch_item_failures = []

    for record in event["Records"]:
        message_id = record["messageId"]
        try:
            order = _parse_sns_wrapped_message(record["body"])
            _send_confirmation_email(order)
            logger.info("Email sent for order %s", order.get("order_id"))
        except Exception as e:
            logger.error("Failed to process message %s: %s", message_id, e)
            # Report failure — SQS will retry this individual message
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}


def _parse_sns_wrapped_message(body: str) -> dict:
    """SNS wraps the original message in an envelope when delivering to SQS."""
    outer = json.loads(body)
    # SNS envelope has a "Message" field containing the actual payload
    if "Message" in outer:
        return json.loads(outer["Message"])
    return outer   # Direct SQS message (useful for local testing)


def _send_confirmation_email(order: dict):
    customer_email = order["email"]
    order_id = order["order_id"]
    items = order.get("items", [])
    items_text = "\n".join(f"  - {item}" for item in items)

    subject = f"Order Confirmed — #{order_id}"
    body_text = (
        f"Hi,\n\n"
        f"Your order #{order_id} has been received and is being processed.\n\n"
        f"Items ordered:\n{items_text}\n\n"
        f"Thank you for shopping with ShipFast!\n"
    )
    body_html = f"""
    <html><body>
      <h2>Order Confirmed — #{order_id}</h2>
      <p>Your order has been received and is being processed.</p>
      <ul>{"".join(f"<li>{item}</li>" for item in items)}</ul>
      <p>Thank you for shopping with ShipFast!</p>
    </body></html>
    """

    ses.send_email(
        Source=FROM_ADDRESS,
        Destination={"ToAddresses": [customer_email]},
        Message={
            "Subject": {"Data": subject},
            "Body": {
                "Text": {"Data": body_text},
                "Html": {"Data": body_html},
            },
        },
    )
