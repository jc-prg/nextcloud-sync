"""/api/accounts"""

from backend.crypto import decrypt
from backend.database import SessionLocal
from backend.models import Account


def body(**kw):
    values = dict(label="Cloud", webdav_url="http://src.test/dav/", username="user", password="pw")
    values.update(kw)
    return values


async def test_create_and_read_account(api):
    resp = await api.post("/api/accounts", json=body(storage_limit_bytes=100))

    assert resp.status_code == 201
    data = resp.json()
    assert data["webdav_url"] == "http://src.test/dav"  # trailing slash stripped
    assert data["storage_limit_bytes"] == 100
    assert "password" not in data and "password_enc" not in data
    async with SessionLocal() as db:
        stored = await db.get(Account, data["id"])
        assert stored.password_enc != "pw" and decrypt(stored.password_enc) == "pw"
    assert (await api.get(f"/api/accounts/{data['id']}")).json() == data


async def test_list_is_sorted_by_label(api):
    for label in ["b", "a", "c"]:
        await api.post("/api/accounts", json=body(label=label))
    assert [a["label"] for a in (await api.get("/api/accounts")).json()] == ["a", "b", "c"]


async def test_partial_update(api):
    acc = (await api.post("/api/accounts", json=body(storage_limit_bytes=100))).json()

    resp = await api.patch(f"/api/accounts/{acc['id']}", json={"label": "New", "password": "new-pw"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["label"] == "New" and data["username"] == "user" and data["storage_limit_bytes"] == 100
    async with SessionLocal() as db:
        assert decrypt((await db.get(Account, acc["id"])).password_enc) == "new-pw"


async def test_storage_limit_can_be_cleared(api):
    acc = (await api.post("/api/accounts", json=body(storage_limit_bytes=100))).json()
    data = (await api.patch(f"/api/accounts/{acc['id']}", json={"storage_limit_bytes": None})).json()
    assert data["storage_limit_bytes"] is None


async def test_delete(api):
    acc = (await api.post("/api/accounts", json=body())).json()
    assert (await api.delete(f"/api/accounts/{acc['id']}")).status_code == 204
    assert (await api.get(f"/api/accounts/{acc['id']}")).status_code == 404


async def test_unknown_account_is_404(api):
    assert (await api.get("/api/accounts/99")).status_code == 404
    assert (await api.patch("/api/accounts/99", json={})).status_code == 404
    assert (await api.delete("/api/accounts/99")).status_code == 404
    assert (await api.post("/api/accounts/99/test")).status_code == 404
    assert (await api.get("/api/accounts/99/quota")).status_code == 404


async def test_connection_test(api, dav):
    dav("src")
    ok = (await api.post("/api/accounts", json=body())).json()
    bad = (await api.post("/api/accounts", json=body(webdav_url="http://down.test/dav"))).json()

    assert (await api.post(f"/api/accounts/{ok['id']}/test")).json() == {"ok": True, "error": None}
    assert (await api.post(f"/api/accounts/{bad['id']}/test")).json()["ok"] is False


async def test_quota(api, dav):
    dav("src").quota = (10, 20)
    ok = (await api.post("/api/accounts", json=body())).json()
    bad = (await api.post("/api/accounts", json=body(webdav_url="http://down.test/dav"))).json()

    assert (await api.get(f"/api/accounts/{ok['id']}/quota")).json() == {"used": 10, "available": 20}
    data = (await api.get(f"/api/accounts/{bad['id']}/quota")).json()
    assert data["used"] is None and data["available"] is None and data["error"]
