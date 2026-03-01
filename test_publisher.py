"""
Unit tests for order-publisher Lambda.
Run with: python -m unittest tests.test_publisher -v
"""
import json, sys, os, types, importlib, importlib.util, unittest
from unittest.mock import MagicMock

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

os.environ["SNS_TOPIC_ARN"] = "arn:aws:sns:us-east-1:123456789:order-events"
HANDLER = os.path.join(os.path.dirname(__file__), "../src/publisher/handler.py")

def load():
    spec = importlib.util.spec_from_file_location("pub_handler", HANDLER)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

class TestValidate(unittest.TestCase):
    def setUp(self): self.v = load().validate_order

    def test_valid(self):
        self.assertEqual(self.v({"order_id":"O1","email":"a@b.com","items":["x"]}), [])
    def test_missing_order_id(self):
        self.assertTrue(any("order_id" in e for e in self.v({"email":"a@b.com","items":["x"]})))
    def test_missing_email(self):
        self.assertTrue(any("email" in e for e in self.v({"order_id":"O1","items":["x"]})))
    def test_missing_items(self):
        self.assertTrue(any("items" in e for e in self.v({"order_id":"O1","email":"a@b.com"})))
    def test_blank_order_id(self):
        self.assertGreater(len(self.v({"order_id":"  ","email":"a@b.com","items":["x"]})), 0)
    def test_invalid_email(self):
        self.assertTrue(any("email" in e for e in self.v({"order_id":"O1","email":"bad","items":["x"]})))
    def test_empty_items(self):
        self.assertGreater(len(self.v({"order_id":"O1","email":"a@b.com","items":[]})), 0)

class TestHandler(unittest.TestCase):
    def setUp(self): self.mod = load(); self.mod.sns = MagicMock()
    def ev(self, b): return {"body": json.dumps(b) if isinstance(b,dict) else b}

    def test_valid_returns_202(self):
        self.mod.sns.publish.return_value = {"MessageId":"x"}
        r = self.mod.lambda_handler(self.ev({"order_id":"O1","email":"a@b.com","items":["x"]}), {})
        self.assertEqual(r["statusCode"], 202)

    def test_202_not_200(self):
        self.mod.sns.publish.return_value = {"MessageId":"x"}
        r = self.mod.lambda_handler(self.ev({"order_id":"O1","email":"a@b.com","items":["x"]}), {})
        self.assertNotEqual(r["statusCode"], 200)

    def test_missing_field_returns_400(self):
        r = self.mod.lambda_handler(self.ev({"order_id":"O1"}), {})
        self.assertEqual(r["statusCode"], 400)

    def test_bad_json_returns_400(self):
        r = self.mod.lambda_handler({"body":"{{not-json"}, {})
        self.assertEqual(r["statusCode"], 400)

    def test_sns_error_returns_502(self):
        from botocore.exceptions import ClientError
        self.mod.sns.publish.side_effect = ClientError({"Error":{"Code":"500","Message":"x"}},"Publish")
        r = self.mod.lambda_handler(self.ev({"order_id":"O1","email":"a@b.com","items":["x"]}), {})
        self.assertEqual(r["statusCode"], 502)

    def test_publishes_to_correct_topic(self):
        self.mod.sns.publish.return_value = {"MessageId":"x"}
        self.mod.lambda_handler(self.ev({"order_id":"O1","email":"a@b.com","items":["x"]}), {})
        self.assertEqual(self.mod.sns.publish.call_args.kwargs["TopicArn"], os.environ["SNS_TOPIC_ARN"])

if __name__ == "__main__": unittest.main()
