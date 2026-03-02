# ShipFast Order Notification Pipeline

A resilient, event-driven order notification system built on AWS. This project is being built manually through the AWS console as a learning exercise before moving to infrastructure as code.

```
POST /orders
     │
     ▼
API Gateway
     │
     ▼
Lambda: order-publisher
 (validates payload)
     │
     ▼
SNS: order-events
     │
 ┌───┼───────────┐
 ▼   ▼           ▼
SQS  SQS        SQS
email-queue  slack-queue  audit-queue
 │   │           │
 ▼   ▼           ▼
Lambda  Lambda  Lambda
email   slack   audit
consumer consumer consumer
 │   │           │
 ▼   ▼           ▼
DLQ  DLQ        DLQ  ──► CloudWatch Alarm ──► SNS ──► On-Call Email
```

---

## What This System Does

When a customer places an order, it hits the API Gateway endpoint. A Lambda validates the payload and publishes it to an SNS topic. SNS fans that message out to three independent SQS queues simultaneously. Three separate Lambda functions each consume from their own queue — one sends a confirmation email via SES, one posts an alert to the ops Slack channel, and one writes a structured audit log to CloudWatch Logs. If any consumer fails after 3 retries, the message lands in a Dead Letter Queue and a CloudWatch alarm fires, emailing the on-call engineer before any customer complains.

---

## Why This Architecture

The old system was a single script on a single server. When it went down, everything went down — no emails, no Slack alerts, no audit trail, and nobody knew until Trustpilot reviews started coming in. This pipeline is decoupled — each consumer is independent, so if the email Lambda has a problem the Slack and audit consumers keep running. Nothing is silently lost. Failures are visible.

---

## Key Concepts

**Why 202 and not 200?**
The API returns 202 Accepted because processing is asynchronous. The order has been received and queued — the email hasn't been sent yet, Slack hasn't been posted yet. 200 OK would imply the work is already done, which it isn't.

**Why visibility timeout = 30 seconds?**
When a Lambda picks up a message from SQS, SQS hides that message from other consumers for the duration of the visibility timeout. If the timeout is shorter than the Lambda's execution time, SQS makes the message visible again before the Lambda finishes — causing duplicate processing. Visibility timeout must always be equal to or greater than the Lambda timeout.

**Why partial batch failure handling?**
Each consumer Lambda uses ReportBatchItemFailures. Without this, if one message in a batch of ten fails, SQS retries all ten — causing duplicate emails and Slack posts for customers whose orders processed successfully. With it, only the failed message gets retried.

**Why does Lambda poll SQS?**
AWS does the polling automatically through an event source mapping configured on each Lambda trigger. You don't write polling code. When a message arrives in the queue, AWS invokes the Lambda and hands it the message. The alternative — a server polling in a loop 24/7 — is exactly what ShipFast's old monolith was doing, and it's expensive, fragile, and doesn't scale.

---

## Lambda Functions

### order-publisher
Triggered by API Gateway POST /orders. Validates that order_id, email, and items are all present and correctly formatted. If validation fails, returns 400 with a clear error message. If valid, publishes the order to the order-events SNS topic and returns 202.

Environment variables required:
- SNS_TOPIC_ARN — the ARN of your order-events SNS topic

IAM permissions required:
- sns:Publish on the order-events topic

### email-consumer
Triggered by the email-queue SQS queue. Parses the SNS-wrapped message, extracts the order, and sends a confirmation email to the customer via SES.

Environment variables required:
- SES_FROM_ADDRESS — the verified sender email address

IAM permissions required:
- ses:SendEmail

### slack-consumer
Triggered by the slack-queue SQS queue. Parses the SNS-wrapped message and posts an order alert to the ops Slack channel via an incoming webhook.

Environment variables required:
- SLACK_WEBHOOK_URL — your Slack incoming webhook URL. Never hardcode this.

### audit-consumer
Triggered by the audit-queue SQS queue. Parses the SNS-wrapped message and writes a structured JSON audit record to CloudWatch Logs for every order that passes through the system.

No environment variables or special IAM permissions required beyond the default Lambda execution role.

---

## Build Order in the AWS Console

Always build from the inside out — create dependencies before the things that depend on them.

1. Create SNS topic (order-events)
2. Create three SQS queues (email-queue, slack-queue, audit-queue) with visibility timeout 30s, retention 4 days, encryption enabled
3. Create three Dead Letter Queues (email-dlq, slack-dlq, audit-dlq) and attach them to their main queues with maxReceiveCount=3
4. Subscribe all three main queues to the SNS topic and update each queue's access policy to allow SNS to write to it
5. Verify your sender and recipient email addresses in SES
6. Create your Slack incoming webhook and copy the URL
7. Create four Lambda functions (Python 3.12), paste in the code, and configure environment variables and IAM permissions for each
8. Add SQS triggers to the three consumer Lambdas, one queue per Lambda, with ReportBatchItemFailures enabled
9. Create API Gateway REST API, add POST /orders resource, point it at the publisher Lambda, and deploy to a stage
10. Create three CloudWatch alarms watching ApproximateNumberOfMessagesVisible on each DLQ, threshold greater than 5, and point them at an SNS topic that emails you

---

## Testing

**Happy path** — send a POST request to your API Gateway URL with a valid body:

```json
{
  "order_id": "ORD-001",
  "email": "your-verified-email@example.com",
  "items": ["Widget A", "Widget B"]
}
```

You should get a 202 back. Within 30 seconds all three consumer Lambdas should fire — check CloudWatch Logs to confirm.

**Validation failure** — send a request with a missing field and confirm you get a 400 back with a clear error message.

**DLQ and alarm test** — temporarily add `raise Exception("test failure")` at the top of a consumer Lambda handler, send 6+ orders, and watch the messages fail, retry three times each, land in the DLQ, and trigger your CloudWatch alarm email. Remove the exception when done.

---

## Project Structure

```
shipfast-orders/
├── README.md
└── src/
    ├── publisher/handler.py        — API Gateway + SNS publisher
    ├── email_consumer/handler.py   — SES email sender
    ├── slack_consumer/handler.py   — Slack webhook poster
    └── audit_consumer/handler.py   — CloudWatch structured audit logger
```

The infrastructure is being built manually in the AWS console. Infrastructure as code using SAM and CloudFormation will be introduced in a later phase once the architecture is fully understood.