"""/api/browse"""

from backend.tests.factories import make_account


async def test_lists_folder_contents_without_the_folder_itself(api, dav):
    s = dav("src")
    s.write("/Docs/a.txt", "abc")
    s.write("/Docs/Sub/deep.txt", "x")
    acc = await make_account(s)

    resp = await api.get("/api/browse", params={"account_id": acc.id, "path": "/Docs"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "/Docs"
    entries = {e["path"]: e for e in data["entries"]}
    assert set(entries) == {"/Docs/a.txt", "/Docs/Sub/"}
    assert entries["/Docs/a.txt"]["size"] == 3 and not entries["/Docs/a.txt"]["is_dir"]
    assert entries["/Docs/Sub/"]["is_dir"] and entries["/Docs/Sub/"]["name"] == "Sub"


async def test_root_is_the_default_path(api, dav):
    s = dav("src")
    s.mkdir("/Top")
    acc = await make_account(s)
    data = (await api.get("/api/browse", params={"account_id": acc.id})).json()
    assert [e["path"] for e in data["entries"]] == ["/Top/"]


async def test_depth_2(api, dav):
    s = dav("src")
    s.write("/a/b/c.txt", "x")
    acc = await make_account(s)
    data = (await api.get("/api/browse", params={"account_id": acc.id, "path": "/a", "depth": 2})).json()
    assert {e["path"] for e in data["entries"]} == {"/a/b/", "/a/b/c.txt"}


async def test_depth_is_limited(api, dav):
    acc = await make_account(dav("src"))
    for depth in (0, 3):
        resp = await api.get("/api/browse", params={"account_id": acc.id, "depth": depth})
        assert resp.status_code == 422


async def test_unknown_account_is_404(api):
    assert (await api.get("/api/browse", params={"account_id": 99})).status_code == 404


async def test_webdav_error_is_502(api, dav):
    acc = await make_account(dav("src"))
    resp = await api.get("/api/browse", params={"account_id": acc.id, "path": "/missing"})
    assert resp.status_code == 502
    assert resp.json()["detail"].startswith("WebDAV error:")
