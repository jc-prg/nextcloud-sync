"""Async WebDAV client built on httpx."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote, urlparse

import httpx

_DAV = "{DAV:}"


@dataclass
class DavEntry:
    href: str        # raw href from server (absolute URL path)
    rel_path: str    # path relative to the WebDAV base (e.g. "/Photos/2024/")
    name: str        # last path component
    is_dir: bool
    etag: str | None
    mtime: datetime | None
    size: int        # bytes; 0 for directories


class WebDAVClient:
    """Async context manager wrapping an httpx client for WebDAV operations."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._base_path = urlparse(self.base_url).path.rstrip("/")
        self._auth = (username, password)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "WebDAVClient":
        self._client = httpx.AsyncClient(
            auth=self._auth,
            # connect/pool timeouts are absolute; read/write are per-chunk so large
            # files don't time out as long as each chunk arrives within the window.
            timeout=httpx.Timeout(connect=30.0, read=120.0, write=120.0, pool=10.0),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def test_connection(self) -> bool:
        try:
            resp = await self._client.request(
                "PROPFIND",
                self.base_url + "/",
                headers={"Depth": "0", "Content-Type": "application/xml"},
                content=_PROPFIND_BODY,
            )
            return resp.status_code in (200, 207)
        except Exception:
            return False

    async def propfind(self, path: str, depth: int = 1) -> list[DavEntry]:
        """List entries at *path* with the given *depth* (0, 1, or 'infinity')."""
        url = self.base_url + _encode_path(path)
        resp = await self._client.request(
            "PROPFIND",
            url,
            headers={"Depth": str(depth), "Content-Type": "application/xml"},
            content=_PROPFIND_BODY,
        )
        resp.raise_for_status()
        return _parse_propfind(resp.text, self._base_path)

    async def copy_to(
        self,
        src_path: str,
        dst: "WebDAVClient",
        dst_path: str,
        size: int,
        chunk_size: int = 256 * 1024,
    ) -> None:
        """Stream-copy a file from this server to dst without buffering it in memory.

        Uses a chunked GET piped directly into a PUT so memory usage is bounded
        to one chunk at a time regardless of file size.
        """
        src_url = self.base_url + _encode_path(src_path)
        dst_url = dst.base_url + _encode_path(dst_path)
        async with self._client.stream("GET", src_url) as get_resp:
            get_resp.raise_for_status()
            put_resp = await dst._client.put(
                dst_url,
                content=get_resp.aiter_bytes(chunk_size=chunk_size),
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                },
            )
            put_resp.raise_for_status()

    async def get_bytes(self, path: str) -> bytes:
        resp = await self._client.get(self.base_url + _encode_path(path))
        resp.raise_for_status()
        return resp.content

    async def put_bytes(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        resp = await self._client.put(
            self.base_url + _encode_path(path),
            content=data,
            headers={"Content-Type": content_type},
        )
        resp.raise_for_status()

    async def delete(self, path: str) -> None:
        resp = await self._client.delete(self.base_url + _encode_path(path))
        resp.raise_for_status()

    async def mkcol(self, path: str) -> None:
        """Create a collection; silently ignore 405 (already exists)."""
        resp = await self._client.request("MKCOL", self.base_url + _encode_path(path))
        if resp.status_code not in (200, 201, 405):
            resp.raise_for_status()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _encode_path(path: str) -> str:
    """Percent-encode a decoded path for use in HTTP requests.
    Preserves '/' separators; encodes everything else including non-ASCII."""
    return quote(path, safe="/:@!$&'()*+,;=")


# ------------------------------------------------------------------
# PROPFIND XML helpers
# ------------------------------------------------------------------

_PROPFIND_BODY = b"""<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:resourcetype/>
    <d:getlastmodified/>
    <d:getcontentlength/>
    <d:getetag/>
  </d:prop>
</d:propfind>"""


def _parse_propfind(xml_text: str, base_path: str) -> list[DavEntry]:
    root = ET.fromstring(xml_text)
    entries: list[DavEntry] = []

    for response in root.iter(f"{_DAV}response"):
        href_el = response.find(f"{_DAV}href")
        if href_el is None or not href_el.text:
            continue
        href = unquote(href_el.text)

        # Find the 200-OK propstat block
        prop = None
        for ps in response.findall(f"{_DAV}propstat"):
            status_el = ps.find(f"{_DAV}status")
            if status_el is not None and "200" in (status_el.text or ""):
                prop = ps.find(f"{_DAV}prop")
                break
        if prop is None:
            continue

        resourcetype = prop.find(f"{_DAV}resourcetype")
        is_dir = (
            resourcetype is not None
            and resourcetype.find(f"{_DAV}collection") is not None
        )

        etag_el = prop.find(f"{_DAV}getetag")
        etag = etag_el.text.strip('"') if etag_el is not None and etag_el.text else None

        mtime: datetime | None = None
        mtime_el = prop.find(f"{_DAV}getlastmodified")
        if mtime_el is not None and mtime_el.text:
            try:
                mtime = parsedate_to_datetime(mtime_el.text)
            except Exception:
                pass

        size = 0
        size_el = prop.find(f"{_DAV}getcontentlength")
        if size_el is not None and size_el.text:
            try:
                size = int(size_el.text)
            except ValueError:
                pass

        # href is an absolute URL path like "/remote.php/dav/files/user/Photos/2024/"
        # Strip the base_path prefix to get a path relative to this account's DAV root
        rel_path = href
        if base_path and rel_path.startswith(base_path):
            rel_path = rel_path[len(base_path):]
        if not rel_path:
            rel_path = "/"

        name = rel_path.rstrip("/").rsplit("/", 1)[-1] or "/"

        entries.append(
            DavEntry(
                href=href,
                rel_path=rel_path,
                name=name,
                is_dir=is_dir,
                etag=etag,
                mtime=mtime,
                size=size,
            )
        )

    return entries
