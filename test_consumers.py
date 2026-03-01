"""Unit tests for email, slack, and audit consumer Lambdas."""
import json, sys, os, types, importlib, importlib.util, io, unittest
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout

# ── boto3/botocore stub ──────────────────────────────────────────────────────
try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    class ClientError(Exception):
        def __init__(self, er, op): self.response = er; super().__init__(str(er))
    boto3 = MagicMock()
    bm = types.ModuleType("botocore"); be = types.ModuleType("botocore.exceptions")
    be.ClientError = ClientError; bm.exceptions = be
    sys.modules.setdefault("boto3", boto3); sys.modules.setdefault("botocore", bm)
    sys.modules.setdefault("botocore.exceptions", be)
# ─────────────────────────────────────────────────────────────────────────────

os.environ.setdefault("SES_FROM_ADDRESS", "orders@shipfast.example.com")
os.environ.setdefault("SLACK_WEBHOOK_URL", "https://hooks.slack.com/TEST")

BASE = os.path.dirname(__file__)
def load(name):
    path = os.path.join(BASE, f"../src/{name}/handler.py")
    spec = importlib.util.spec_from_file_location(f"{name}_h", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

ORDER = {"order_id":"ORD-1","email":"bob@example.com","items":["Keyboard","Mouse"]}

def sqs_event(order, msg_id="msg-001"):
    return {"Records":[{"messageId":msg_id,
        "body": json.dumps({"Message": json.dumps(order)}),
        "eventSourceARN":"arn:aws:sqs:us-east-1:123:email-queue"}]}


# ── Email Consumer ────────────────────────────────────────────────────────────
class TestEmailConsumer(unittest.TestCase):
    def setUp(self): self.mod = load("email_consumer"); self.mod.ses = MagicMock()

    def test_success_empty_failures(self):
        self.mod.ses.send_email.return_value = {"MessageId":"s1"}
        r = self.mod.lambda_handler(sqs_event(ORDER), {})
        self.assertEqual(r["batchItemFailures"], [])

    def test_ses_error_reports_failure(self):
        from botocore.exceptions import ClientError
        self.mod.ses.send_email.side_effect = ClientError({"Error":{"Code":"x","Message":"x"}},"SendEmail")
        r = self.mod.lambda_handler(sqs_event(ORDER), {})
        self.assertEqual(len(r["batchItemFailures"]), 1)
        self.assertEqual(r["batchItemFailures"][0]["itemIdentifier"], "msg-001")

    def test_partial_batch_only_fails_bad_message(self):
        from botocore.exceptions import ClientError
        order2 = {**ORDER, "order_id":"ORD-2"}
        event = {"Records":[
            {"messageId":"m1","body":json.dumps({"Message":json.dumps(ORDER)}),"eventSourceARN":""},
            {"messageId":"m2","body":json.dumps({"Message":json.dumps(order2)}),"eventSourceARN":""},
        ]}
        self.mod.ses.send_email.side_effect = [
            {"MessageId":"ok"},
            ClientError({"Error":{"Code":"T","Message":"throttle"}},"SendEmail"),
        ]
        r = self.mod.lambda_handler(event, {})
        self.assertEqual(len(r["batchItemFailures"]), 1)
        self.assertEqual(r["batchItemFailures"][0]["itemIdentifier"], "m2")

    def test_sends_to_customer_email(self):
        self.mod.ses.send_email.return_value = {"MessageId":"x"}
        self.mod.lambda_handler(sqs_event(ORDER), {})
        call = self.mod.ses.send_email.call_args
        self.assertIn(ORDER["email"], call.kwargs["Destination"]["ToAddresses"])


# ── Slack Consumer ────────────────────────────────────────────────────────────
class TestSlackConsumer(unittest.TestCase):
    def setUp(self): self.mod = load("slack_consumer")

    def test_success_empty_failures(self):
        mock_resp = MagicMock(); mock_resp.status = 200
        mock_resp.__enter__ = lambda s: mock_resp; mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(self.mod.urllib.request, "urlopen", return_value=mock_resp):
            r = self.mod.lambda_handler(sqs_event(ORDER), {})
        self.assertEqual(r["batchItemFailures"], [])

    def test_missing_webhook_url_reports_failure(self):
        orig = self.mod.SLACK_WEBHOOK_URL
        self.mod.SLACK_WEBHOOK_URL = None
        r = self.mod.lambda_handler(sqs_event(ORDER), {})
        self.mod.SLACK_WEBHOOK_URL = orig
        self.assertEqual(len(r["batchItemFailures"]), 1)

    def test_slack_non_200_reports_failure(self):
        mock_resp = MagicMock(); mock_resp.status = 500
        mock_resp.__enter__ = lambda s: mock_resp; mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(self.mod.urllib.request, "urlopen", return_value=mock_resp):
            r = self.mod.lambda_handler(sqs_event(ORDER), {})
        self.assertEqual(len(r["batchItemFailures"]), 1)


# ── Audit Consumer ────────────────────────────────────────────────────────────
class TestAuditConsumer(unittest.TestCase):
    def setUp(self): self.mod = load("audit_consumer")

    def test_success_empty_failures(self):
        f = io.StringIO()
        with redirect_stdout(f):
            r = self.mod.lambda_handler(sqs_event(ORDER), {})
        self.assertEqual(r["batchItemFailures"], [])

    def test_bad_json_reports_failure(self):
        event = {"Records":[{"messageId":"bad","body":"{{notjson","eventSourceARN":""}]}
        r = self.mod.lambda_handler(event, {})
        self.assertEqual(len(r["batchItemFailures"]), 1)

    def test_audit_log_structure(self):
        f = io.StringIO()
        with redirect_stdout(f):
            self.mod.lambda_handler(sqs_event(ORDER), {})
        logged = json.loads(f.getvalue().strip())
        self.assertEqual(logged["audit"]["order_id"], "ORD-1")
        self.assertEqual(logged["audit"]["event_type"], "order.created")
        self.assertIn("timestamp", logged["audit"])
        self.assertEqual(logged["audit"]["item_count"], 2)

    def test_direct_message_no_sns_envelope(self):
        """Handles direct SQS messages (no SNS wrapping) for local testing."""
        event = {"Records":[{"messageId":"d1","body":json.dumps(ORDER),"eventSourceARN":""}]}
        f = io.StringIO()
        with redirect_stdout(f):
            r = self.mod.lambda_handler(event, {})
        self.assertEqual(r["batchItemFailures"], [])

if __name__ == "__main__": unittest.main()
