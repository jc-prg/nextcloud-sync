"""/api/auth and token protection of the other routes."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jose import jwt

from backend.auth import ALGORITHM, hash_password
from backend.config import settings


async def test_status_reports_whether_setup_is_done(anon_api):
    assert (await anon_api.get("/api/auth/status")).json() == {"is_configured": False}
    settings.app_password_hash = hash_password("password1")
    assert (await anon_api.get("/api/auth/status")).json() == {"is_configured": True}


async def test_setup_sets_password_writes_env_and_returns_token(anon_api):
    Path(".env").write_text("SECRET_KEY=keep\nAPP_PASSWORD_HASH=\n")

    resp = await anon_api.post("/api/auth/setup", json={"password": "password1"})

    assert resp.status_code == 200
    token = resp.json()["access_token"]
    assert (await anon_api.get("/api/rules", headers={"Authorization": f"Bearer {token}"})).status_code == 200
    env = Path(".env").read_text().splitlines()
    assert env[0] == "SECRET_KEY=keep"
    assert env[1].startswith("APP_PASSWORD_HASH=$2")
    assert (await anon_api.post("/api/auth/login", json={"password": "password1"})).status_code == 200


async def test_setup_creates_env_when_missing(anon_api):
    await anon_api.post("/api/auth/setup", json={"password": "password1"})
    assert Path(".env").read_text().startswith("APP_PASSWORD_HASH=")


async def test_setup_rejects_short_password(anon_api):
    resp = await anon_api.post("/api/auth/setup", json={"password": "short"})
    assert resp.status_code == 422
    assert settings.app_password_hash == ""


async def test_setup_is_locked_once_configured(anon_api):
    settings.app_password_hash = hash_password("password1")
    resp = await anon_api.post("/api/auth/setup", json={"password": "password2"})
    assert resp.status_code == 403


async def test_login(anon_api):
    assert (await anon_api.post("/api/auth/login", json={"password": "x"})).status_code == 403  # not set up
    settings.app_password_hash = hash_password("password1")
    assert (await anon_api.post("/api/auth/login", json={"password": "wrong"})).status_code == 401
    resp = await anon_api.post("/api/auth/login", json={"password": "password1"})
    assert resp.status_code == 200 and resp.json()["token_type"] == "bearer"


def token(secret: str = "test-secret-key", minutes: int = 5, sub: str = "admin") -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return jwt.encode({"exp": exp, "sub": sub}, secret, algorithm=ALGORITHM)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer garbage"},
        {"Authorization": f"Bearer {token(minutes=-1)}"},
        {"Authorization": f"Bearer {token(secret='other')}"},
        {"Authorization": f"Bearer {token(sub='someone')}"},
    ],
    ids=["missing", "garbage", "expired", "wrong-signature", "wrong-subject"],
)
@pytest.mark.parametrize(
    "method, path",
    [("GET", "/api/accounts"), ("GET", "/api/rules"), ("GET", "/api/jobs"), ("GET", "/api/browse?account_id=1")],
)
async def test_protected_routes_reject_bad_tokens(anon_api, headers, method, path):
    resp = await anon_api.request(method, path, headers=headers)
    assert resp.status_code == 401


async def test_valid_token_is_accepted(anon_api):
    resp = await anon_api.get("/api/rules", headers={"Authorization": f"Bearer {token()}"})
    assert resp.status_code == 200
