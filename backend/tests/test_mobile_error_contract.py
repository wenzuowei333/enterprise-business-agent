import unittest

from app.api.mobile_errors import mobile_error_payload


class MobileErrorContractTest(unittest.TestCase):
    def test_error_payload_has_stable_business_contract(self):
        payload = mobile_error_payload(
            code="validation_error",
            message="请检查输入内容",
            request_id="req-001",
            field_errors=[{"field": "data_date", "message": "日期格式错误"}],
        )
        self.assertEqual(
            payload,
            {
                "code": "validation_error",
                "message": "请检查输入内容",
                "field_errors": [{"field": "data_date", "message": "日期格式错误"}],
                "request_id": "req-001",
            },
        )


if __name__ == "__main__":
    unittest.main()
