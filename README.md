# ShipFast Order Notification Pipeline

Resilient, event-driven order notification system on AWS.

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

## Why 202 and not 200?
`200 OK` means the request was **fulfilled synchronously**.  
`202 Accepted` means the request was **received and queued** for async processing.  
Since we only publish to SNS — we don't wait for emails to send or Slack to post — 202 is semantically correct.

## Why visibility timeout = 30 seconds?
The visibility timeout hides a message from other consumers while one Lambda is processing it.  
If it's shorter than the Lambda timeout, the message becomes visible again before processing finishes — causing **duplicate processing**. Always set visibility timeout ≥ Lambda timeout.

## Project Structure
```
shipfast-orders/
├── template.yaml                  # SAM/CloudFormation — all infrastructure
├── samconfig.toml                 # SAM deploy defaults
├── src/
│   ├── publisher/handler.py       # Task 1 — API Gateway + SNS publisher
│   ├── email_consumer/handler.py  # Task 3 — SES email sender
│   ├── slack_consumer/handler.py  # Task 3 — Slack webhook poster
│   └── audit_consumer/handler.py  # Task 3 — CloudWatch structured logger
├── tests/
│   ├── test_publisher.py
│   └── test_consumers.py
└── .github/workflows/deploy.yml   # CI/CD pipeline
```

## Local Setup

### Prerequisites
- AWS CLI configured (`aws configure`)
- AWS SAM CLI (`brew install aws-sam-cli`)
- Python 3.12+

### Run tests locally
```bash
pip install pytest boto3
pytest tests/ -v
```

### Deploy manually (first time)
```bash
sam build
sam deploy --guided
# Answer the prompts — enter your on-call email and Slack webhook URL
```

### Deploy (subsequent times)
```bash
sam build && sam deploy
```

## GitHub Secrets Required
Add these in **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | IAM user access key (deploy permissions) |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `ONCALL_EMAIL` | Email for CloudWatch alarm notifications |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |

**Never commit credentials to the repository.**

## Testing DLQ Alarms (Task 4)
To deliberately trigger the DLQ alarm:
1. Temporarily add `raise Exception("test failure")` at the top of any consumer's `lambda_handler`.
2. Push 6+ messages to the corresponding SQS queue.
3. After 3 retries (`maxReceiveCount=3`), messages land in the DLQ.
4. CloudWatch alarm fires at depth > 5 → email sent to on-call engineer.
5. Remove the exception and redeploy to recover.

## Partial Batch Failure Handling
All consumers use `ReportBatchItemFailures`. This means:
- If message 3 of 10 fails, only message 3 is retried.
- Messages 1, 2, 4–10 are **not** re-processed.
- Without this, SQS retries all 10 messages → expensive and causes duplicate side effects.
