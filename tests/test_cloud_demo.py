import base64
import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class CloudDemoAccessTests(unittest.TestCase):
    def test_cloud_demo_is_public_by_default(self):
        configured = replace(main.settings, cloud_deployment=True, cloud_require_login=False,
                             demo_access_password="sample-password")
        with patch.object(main, "settings", configured):
            client = TestClient(main.app)
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/api/zotero/status").status_code, 503)

    def test_optional_cloud_login_protects_pages_and_api(self):
        configured = replace(main.settings, cloud_deployment=True, cloud_require_login=True,
                             demo_access_password="sample-password")
        with patch.object(main, "settings", configured):
            client = TestClient(main.app)
            self.assertEqual(client.get("/").status_code, 401)
            self.assertEqual(client.get("/api/health").status_code, 401)
            self.assertEqual(client.get("/healthz").status_code, 200)
            auth = base64.b64encode(b"demo:sample-password").decode("ascii")
            response = client.get("/", headers={"Authorization": f"Basic {auth}"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get("/api/zotero/status", headers={"Authorization": f"Basic {auth}"}).status_code, 503)

    def test_cloud_demo_fails_closed_without_password(self):
        configured = replace(main.settings, cloud_deployment=True, cloud_require_login=True,
                             demo_access_password="")
        with patch.object(main, "settings", configured):
            self.assertEqual(TestClient(main.app).get("/").status_code, 503)


if __name__ == "__main__":
    unittest.main()
