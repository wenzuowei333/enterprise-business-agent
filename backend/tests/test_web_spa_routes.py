from unittest import TestCase

from fastapi.testclient import TestClient

from app.main import app


class WebSpaRouteTest(TestCase):
    def test_exception_center_direct_entry_serves_react_app(self) -> None:
        with TestClient(app) as client:
            response = client.get("/exceptions?view=ai")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn('<div id="app"></div>', response.text)
