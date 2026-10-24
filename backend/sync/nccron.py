"""Periodic call of a Nextcloud server's cron.php (background jobs in "Webcron" mode)."""

import logging
from datetime import datetime, timezone

import httpx

from backend.database import SessionLocal
from backend.models import Account

logger = logging.getLogger(__name__)


async def call_cron(url: str) -> tuple[bool, str | None]:
    """GET cron.php; returns (ok, error). Nextcloud answers {"status": "success"} on success."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0), follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        return False, "Timeout"
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return False, "Unexpected response (not JSON) – is this a Nextcloud cron.php URL?"
    if data.get("status") != "success":
        # e.g. {"data": {"message": "Backgroundjobs are using system cron!"}, "status": "error"}
        details = data.get("data")
        message = details.get("message") if isinstance(details, dict) else None
        return False, message or f"status: {data.get('status')!r}"
    return True, None


async def run_cron(account_id: int) -> Account | None:
    """Call cron.php for the account and store the outcome on it."""
    async with SessionLocal() as db:
        account = await db.get(Account, account_id)
        if account is None:
            return None
        url = account.cron_effective_url
        if url is None:
            ok, error = False, "No cron URL: WebDAV URL is not a Nextcloud URL, set the cron URL explicitly"
        else:
            ok, error = await call_cron(url)
        if not ok:
            logger.warning("cron.php for account %d (%s) failed: %s", account_id, url, error)
        account.cron_last_run_at = datetime.now(timezone.utc)
        account.cron_last_ok = ok
        account.cron_last_error = error
        await db.commit()
        await db.refresh(account)
        return account
