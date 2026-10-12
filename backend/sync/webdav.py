"""Async WebDAV client built on httpx."""

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote, urlparse

import httpx

_DAV = "{DAV:}"

# Files larger than this are uploaded in pieces via Nextcloud's chunked upload API,
# so servers/proxies with a per-request body limit don't reject them (HTTP 413).
CHUNKED_UPLOAD_THRESHOLD = 8 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024


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
            if get_resp.status_code >= 400:
                # Read the error body before raising so _exc_detail can access .text
                await get_resp.aread()
            get_resp.raise_for_status()
            if size > CHUNKED_UPLOAD_THRESHOLD and dst._uploads_url is not None:
                await dst._put_chunked(dst_url, get_resp.aiter_bytes(chunk_size=chunk_size), size)
                return
            put_resp = await dst._client.put(
                dst_url,
                content=get_resp.aiter_bytes(chunk_size=chunk_size),
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                },
            )
            put_resp.raise_for_status()

    @property
    def _uploads_url(self) -> str | None:
        """Nextcloud chunked-upload endpoint, or None if base_url isn't a Nextcloud files URL."""
        marker = "/remote.php/dav/files/"
        idx = self.base_url.find(marker)
        if idx < 0:
            return None
        user = self.base_url[idx + len(marker):].split("/", 1)[0]
        return f"{self.base_url[:idx]}/remote.php/dav/uploads/{user}"

    async def _put_chunked(self, dst_url: str, stream, size: int) -> None:
        """Upload *stream* to *dst_url* using Nextcloud's chunked upload protocol."""
        upload_dir = f"{self._uploads_url}/next-sync-{uuid.uuid4().hex}"
        resp = await self._client.request("MKCOL", upload_dir, headers={"Destination": dst_url})
        resp.raise_for_status()
        try:
            buf = bytearray()
            index = 0

            async def flush() -> None:
                nonlocal index
                index += 1
                r = await self._client.put(
                    f"{upload_dir}/{index:05d}",
                    content=bytes(buf),
                    headers={"Content-Type": "application/octet-stream", "OC-Total-Length": str(size)},
                )
                r.raise_for_status()
                buf.clear()

            async for piece in stream:
                buf.extend(piece)
                while len(buf) >= UPLOAD_CHUNK_SIZE:
                    rest = bytes(buf[UPLOAD_CHUNK_SIZE:])
                    del buf[UPLOAD_CHUNK_SIZE:]
                    await flush()
                    buf.extend(rest)
            if buf or index == 0:
                await flush()

            r = await self._client.request(
                "MOVE",
                f"{upload_dir}/.file",
                headers={"Destination": dst_url, "OC-Total-Length": str(size), "Overwrite": "T"},
            )
            r.raise_for_status()
        except BaseException:
            try:
                await self._client.delete(upload_dir)
            except Exception:
                pass
            raise

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

    async def get_quota(self) -> tuple[int | None, int | None]:
        """Return (used_bytes, available_bytes) via RFC 4331 quota props.

        Returns None for a value when the server doesn't report it or
        returns a sentinel (negative number means unlimited/unknown).
        """
        resp = await self._client.request(
            "PROPFIND",
            self.base_url + "/",
            headers={"Depth": "0", "Content-Type": "application/xml"},
            content=_QUOTA_BODY,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        prop = None
        for response in root.iter(f"{_DAV}response"):
            for ps in response.findall(f"{_DAV}propstat"):
                status_el = ps.find(f"{_DAV}status")
                if status_el is not None and "200" in (status_el.text or ""):
                    prop = ps.find(f"{_DAV}prop")
                    break
            if prop is not None:
                break
        if prop is None:
            return None, None

        def _quota_int(tag: str) -> int | None:
            el = prop.find(tag)
            if el is not None and el.text:
                try:
                    v = int(el.text)
                    return v if v >= 0 else None
                except ValueError:
                    pass
            return None

        return (
            _quota_int(f"{_DAV}quota-used-bytes"),
            _quota_int(f"{_DAV}quota-available-bytes"),
        )


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

_QUOTA_BODY = b"""<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:quota-used-bytes/>
    <d:quota-available-bytes/>
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
