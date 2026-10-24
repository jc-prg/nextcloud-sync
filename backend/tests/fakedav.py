"""In-memory WebDAV server served through httpx.MockTransport.

The real WebDAVClient talks to it over (mocked) HTTP, so request building,
PROPFIND XML parsing and the chunked upload flow are all exercised.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape

import httpx

NEXTCLOUD_FILES = "/remote.php/dav/files/"


class Clock:
    """Deterministic clock; every tick is a full second because getlastmodified has 1 s resolution."""

    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def tick(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


@dataclass
class Node:
    is_dir: bool
    mtime: datetime
    data: bytes = b""
    etag: int = 0


@dataclass
class Request:
    method: str
    path: str  # relative to the server's base path


@dataclass
class FakeDav:
    """One WebDAV server. Paths in the helper methods are relative to base_url."""

    base_url: str
    clock: Clock
    nodes: dict[str, Node] = field(default_factory=dict)  # absolute URL path → node
    requests: list[Request] = field(default_factory=list)
    failures: dict[tuple[str, str], int] = field(default_factory=dict)
    quota: tuple[int, int] = (1000, 9000)
    # When set, PROPFIND waits for it — lets tests catch a job while it is running
    gate: asyncio.Event | None = None
    # Nextcloud's cron.php at the server root (GET /cron.php)
    cron_response: dict = field(default_factory=lambda: {"status": "success"})
    cron_calls: int = 0

    def __post_init__(self) -> None:
        self.base_path = httpx.URL(self.base_url).path.rstrip("/")
        self._mkdirs(self.base_path or "/")
        if NEXTCLOUD_FILES in self.base_path:
            prefix, user = self.base_path.split(NEXTCLOUD_FILES, 1)
            self._mkdirs(f"{prefix}/remote.php/dav/uploads/{user.split('/')[0]}")
        self._etag = 0

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def mkdir(self, path: str) -> None:
        self._mkdirs(self._abs(path))

    def write(self, path: str, data: bytes | str) -> None:
        """Create or replace a file, creating missing parent dirs."""
        absolute = self._abs(path)
        self._mkdirs(_parent(absolute))
        self._put(absolute, data.encode() if isinstance(data, str) else data)

    def read(self, path: str) -> bytes:
        return self.nodes[self._abs(path)].data

    def rm(self, path: str) -> None:
        self._delete(self._abs(path))

    def exists(self, path: str) -> bool:
        return self._abs(path) in self.nodes

    def is_dir(self, path: str) -> bool:
        return self.nodes[self._abs(path)].is_dir

    def tree(self, root: str = "/") -> dict[str, bytes | None]:
        """Everything below root as {relative path: content, or None for dirs}."""
        base = self._abs(root).rstrip("/")
        return {
            p[len(base):]: (None if n.is_dir else n.data)
            for p, n in sorted(self.nodes.items())
            if p.startswith(base + "/")
        }

    def fail(self, method: str, path: str, status: int) -> None:
        """Answer the next and every later `method` request on path with status."""
        self.failures[(method, path)] = status

    def count(self, method: str) -> int:
        return sum(1 for r in self.requests if r.method == method)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        method = request.method
        rel = path[len(self.base_path):] if path.startswith(self.base_path) else path
        self.requests.append(Request(method, rel.rstrip("/") or "/"))

        status = self.failures.get((method, rel.rstrip("/") or "/"))
        if status is not None:
            return httpx.Response(status, text=f"injected {status}")

        path = path.rstrip("/") or "/"
        if path == "/cron.php" and method == "GET":
            self.cron_calls += 1
            return httpx.Response(200, json=self.cron_response)
        if method == "PROPFIND":
            if self.gate is not None:
                await self.gate.wait()
            return self._propfind(path, request.headers.get("Depth", "1"), request.content)
        if method == "GET":
            node = self.nodes.get(path)
            if node is None or node.is_dir:
                return httpx.Response(404)
            return httpx.Response(200, content=node.data)
        if method == "PUT":
            parent = self.nodes.get(_parent(path))
            if parent is None or not parent.is_dir:
                return httpx.Response(409)
            existed = path in self.nodes
            self._put(path, await request.aread())
            return httpx.Response(204 if existed else 201)
        if method == "DELETE":
            if path not in self.nodes:
                return httpx.Response(404)
            self._delete(path)
            return httpx.Response(204)
        if method == "MKCOL":
            if path in self.nodes:
                return httpx.Response(405)
            if _parent(path) not in self.nodes:
                return httpx.Response(409)
            self.nodes[path] = Node(is_dir=True, mtime=self.clock.tick())
            return httpx.Response(201)
        if method == "MOVE":
            return self._move(path, request.headers["Destination"])
        return httpx.Response(405)

    def _propfind(self, path: str, depth: str, body: bytes) -> httpx.Response:
        node = self.nodes.get(path)
        if node is None:
            return httpx.Response(404)
        if b"quota-used-bytes" in body:
            used, available = self.quota
            props = f"<d:quota-used-bytes>{used}</d:quota-used-bytes><d:quota-available-bytes>{available}</d:quota-available-bytes>"
            return _multistatus([_response(path + "/", props)])

        max_depth = None if depth == "infinity" else int(depth)
        prefix = path.rstrip("/") + "/"
        paths = [path] + [
            p for p in sorted(self.nodes)
            if p.startswith(prefix) and (max_depth is None or p[len(prefix):].count("/") < max_depth)
        ]
        responses = []
        for p in paths:
            n = self.nodes[p]
            props = (
                (f"<d:resourcetype><d:collection/></d:resourcetype>" if n.is_dir else "<d:resourcetype/>")
                + f"<d:getlastmodified>{format_datetime(n.mtime, usegmt=True)}</d:getlastmodified>"
                + f'<d:getetag>"{n.etag}"</d:getetag>'
                + ("" if n.is_dir else f"<d:getcontentlength>{len(n.data)}</d:getcontentlength>")
            )
            responses.append(_response(p + ("/" if n.is_dir else ""), props))
        return _multistatus(responses)

    def _move(self, path: str, destination: str) -> httpx.Response:
        dest = unquote(httpx.URL(destination).path).rstrip("/")
        if path.endswith("/.file"):
            # Nextcloud chunked upload: assemble the chunks into the destination file
            upload_dir = _parent(path)
            chunks = sorted(p for p in self.nodes if _parent(p) == upload_dir)
            if _parent(dest) not in self.nodes:
                return httpx.Response(409)
            self._put(dest, b"".join(self.nodes[p].data for p in chunks))
            self._delete(upload_dir)
            return httpx.Response(201)
        if path not in self.nodes:
            return httpx.Response(404)
        for p in [p for p in self.nodes if p == path or p.startswith(path + "/")]:
            self.nodes[dest + p[len(path):]] = self.nodes.pop(p)
        return httpx.Response(201)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _abs(self, path: str) -> str:
        return (self.base_path + "/" + path.strip("/")).rstrip("/") or "/"

    def _mkdirs(self, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        for i in range(len(parts) + 1):
            p = "/" + "/".join(parts[:i])
            if p not in self.nodes:
                self.nodes[p] = Node(is_dir=True, mtime=self.clock.tick())

    def _put(self, path: str, data: bytes) -> None:
        self._etag += 1
        self.nodes[path] = Node(is_dir=False, mtime=self.clock.tick(), data=data, etag=self._etag)

    def _delete(self, path: str) -> None:
        for p in [p for p in self.nodes if p == path or p.startswith(path + "/")]:
            del self.nodes[p]


def _parent(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[0] or "/"


def _response(href: str, props: str) -> str:
    return (
        f"<d:response><d:href>{escape(quote(href))}</d:href>"
        f"<d:propstat><d:prop>{props}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
        # Real servers report unsupported props in a separate 404 propstat
        "<d:propstat><d:prop><d:getcontenttype/></d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>"
        "</d:response>"
    )


def _multistatus(responses: list[str]) -> httpx.Response:
    body = '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">' + "".join(responses) + "</d:multistatus>"
    return httpx.Response(207, text=body, headers={"Content-Type": "application/xml; charset=utf-8"})
