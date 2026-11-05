import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.mobile_errors import install_mobile_error_contract, web_error_payload


class WebErrorContractTest(unittest.TestCase):
    def test_payload_preserves_context_and_legacy_detail(self):
        payload = web_error_payload(
            code="inventory_conflict",
            message="Inventory evidence changed",
            request_id="req-001",
            module="exceptions",
            resource_type="inventory_snapshot",
            resource_id="17",
            case_no="EXC-001",
            retryable=True,
            action_path="/exceptions?case_no=EXC-001",
        )

        self.assertEqual(payload["error_code"], "inventory_conflict")
        self.assertEqual(payload["request_id"], "req-001")
        self.assertEqual(payload["case_no"], "EXC-001")
        self.assertEqual(payload["detail"], "Inventory evidence changed")

    def test_http_error_uses_web_contract_and_request_id_header(self):
        app = FastAPI()
        install_mobile_error_contract(app)

        @app.get("/api/v1/exceptions/example")
        def example():
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "exception_evidence_changed",
                    "message": "Evidence changed",
                    "resource_type": "inventory_snapshot",
                    "resource_id": 17,
                    "case_no": "EXC-001",
                    "retryable": True,
                    "action_path": "/exceptions?case_no=EXC-001",
                },
            )

        with TestClient(app) as client:
            response = client.get("/api/v1/exceptions/example", headers={"X-Request-ID": "req-002"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "exception_evidence_changed")
        self.assertEqual(response.headers["X-Request-ID"], "req-002")
        self.assertEqual(response.json()["module"], "exceptions")
        self.assertEqual(response.json()["resource_id"], "17")
        self.assertEqual(response.json()["detail"]["message"], "Evidence changed")

    def test_validation_detail_is_json_serializable(self):
        app = FastAPI()
        install_mobile_error_contract(app)

        @app.get("/api/v1/examples/{value}")
        def example(value: int):
            return {"value": value}

        with TestClient(app) as client:
            response = client.get("/api/v1/examples/not-an-integer")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error_code"], "validation_error")
        self.assertEqual(response.json()["field_errors"][0]["field"], "value")


if __name__ == "__main__":
    unittest.main()
