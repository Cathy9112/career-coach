import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


TEST_JWT_SECRET = "test-only-jwt-secret-key-with-at-least-sixty-four-characters-123456"
os.environ.setdefault("JWT_SECRET_KEY", TEST_JWT_SECRET)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth
import main


class AuthenticationIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        auth.Base.metadata.create_all(bind=self.engine)
        self.original_session_local = auth.SessionLocal
        auth.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

        self.cleanup_patcher = patch.object(main, "cleanup_retained_data", return_value=None)
        self.rate_limit_patcher = patch.object(main.rate_limiter, "enforce", return_value=None)
        self.cleanup_patcher.start()
        self.rate_limit_patcher.start()
        main.app.dependency_overrides.clear()
        self.client = TestClient(main.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        self.rate_limit_patcher.stop()
        self.cleanup_patcher.stop()
        auth.SessionLocal = self.original_session_local
        auth.Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_register_logout_login_and_current_user(self):
        register_response = self.client.post(
            "/api/auth/register",
            json={"username": "integration_user", "password": "password123"},
        )
        self.assertEqual(register_response.status_code, 200)
        self.assertTrue(register_response.cookies.get("access_token"))

        me_response = self.client.get("/api/auth/me")
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["data"]["username"], "integration_user")

        logout_response = self.client.post("/api/auth/logout")
        self.assertEqual(logout_response.status_code, 200)

        invalid_response = self.client.post(
            "/api/auth/login",
            json={"username": "integration_user", "password": "wrongpass"},
        )
        self.assertEqual(invalid_response.status_code, 401)

        login_response = self.client.post(
            "/api/auth/login",
            json={"username": "integration_user", "password": "password123"},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.cookies.get("access_token"))

    def test_duplicate_registration_is_rejected(self):
        payload = {"username": "duplicate_user", "password": "password123"}
        first_response = self.client.post("/api/auth/register", json=payload)
        second_response = self.client.post("/api/auth/register", json=payload)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 409)
        self.assertEqual(second_response.json()["detail"], "username already exists")


if __name__ == "__main__":
    unittest.main()
