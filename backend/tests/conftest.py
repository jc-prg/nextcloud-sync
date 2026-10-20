"""Shared fixtures.

`settings` and the database engine are created when backend modules are first
imported, so the environment is prepared here at import time — before any test
module imports `backend.*`. `settings` is created inside a temp dir so the real
`.env` is never read, and every test runs in its own cwd so it is never written.
"""

import os
import tempfile

from cryptography.fernet import Fernet

_TMP = tempfile.mkdtemp(prefix="next-sync-tests-")
os.environ.update(
    SECRET_KEY="test-secret-key",
    FERNET_KEY=Fernet.generate_key().decode(),
    APP_PASSWORD_HASH="",
    DATA_DIR=os.path.join(_TMP, "data"),
)
_cwd = os.getcwd()
os.chdir(_TMP)
from backend.config import settings  # noqa: E402

os.chdir(_cwd)

import httpx  # noqa: E402
import pytest  # noqa: E402

from backend.auth import create_access_token  # noqa: E402
from backend.database import Base, engine, init_db  # noqa: E402
from backend.sync import engine as sync_engine  # noqa: E402
from backend.sync import webdav  # noqa: E402
from backend.tests.fakedav import Clock, FakeDav  # noqa: E402


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Empty database for every test; connections never outlive the test's event loop."""
    await init_db()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    settings.app_password_hash = ""
    sync_engine._running.clear()


@pytest.fixture(autouse=True)
def _workdir(tmp_path, monkeypatch):
    """Each test gets its own cwd, so `.env` written by /api/auth/setup stays isolated."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def dav(monkeypatch):
    """Factory for in-memory WebDAV servers that every WebDAVClient talks to.

    dav("src") → server at http://src.test/dav
    dav("nc", nextcloud=True) → Nextcloud-style URL, enabling chunked uploads
    """
    servers: dict[str, FakeDav] = {}
    clock = Clock()

    async def handler(request: httpx.Request) -> httpx.Response:
        server = servers.get(request.url.host)
        if server is None:
            raise httpx.ConnectError(f"unknown host {request.url.host}", request=request)
        return await server.handle(request)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(webdav.httpx, "AsyncClient", client_factory)

    def make(name: str, nextcloud: bool = False) -> FakeDav:
        host = f"{name}.test"
        path = "/remote.php/dav/files/user" if nextcloud else "/dav"
        servers[host] = FakeDav(f"http://{host}{path}", clock)
        return servers[host]

    return make


# ----------------------------------------------------------------------
# API clients
# ----------------------------------------------------------------------

@pytest.fixture
async def app():
    """The FastAPI app with its lifespan running (DB init, scheduler on app.state)."""
    from backend.main import app as fastapi_app

    async with fastapi_app.router.lifespan_context(fastapi_app):
        yield fastapi_app


@pytest.fixture
async def anon_api(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app.test") as client:
        yield client


@pytest.fixture
async def api(app):
    """Client logged in with a valid token."""
    headers = {"Authorization": f"Bearer {create_access_token()}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://app.test", headers=headers
    ) as client:
        yield client
