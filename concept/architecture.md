# Architecture: Nextcloud WebDAV Sync Manager

## Overview

A lightweight daemon + web UI running on Raspberry Pi that manages scheduled one-way (or bidirectional) sync between any number of WebDAV-capable Nextcloud accounts.

---

## Conceptual Model

```
┌─────────────────────────────────────────────────────────┐
│                   Raspberry Pi                          │
│                                                         │
│  ┌──────────────┐      ┌─────────────────────────────┐  │
│  │  Web UI      │◄──── │  REST API (FastAPI)         │  │
│  │  (Vue 3 SPA) │      │  - JWT auth                 │  │
│  └──────────────┘      │  - Account CRUD             │  │
│                        │  - SyncRule CRUD            │  │
│                        │  - Job history              │  │
│                        │  - Manual trigger           │  │
│                        │  - WebDAV Browse API        │  │
│                        └────────────┬────────────────┘  │
│                                     │                   │
│                        ┌────────────▼────────────────┐  │
│                        │  SQLite DB                  │  │
│                        │  accounts / sync_rules /    │  │
│                        │  sync_jobs / sync_logs      │  │
│                        └────────────▲────────────────┘  │
│                                     │                   │
│                        ┌────────────┴────────────────┐  │
│                        │  Sync Engine + Scheduler    │  │
│                        │  (APScheduler + httpx)      │  │
│                        └──────┬───────────────┬──────┘  │
└─────────────────────────────────────────────────────────┘
                                │               │
                   WebDAV/HTTPS │               │ WebDAV/HTTPS
                                │               │
                  ┌─────────────▼───┐   ┌───────▼──────────┐
                  │  Local          │   │  Remote          │
                  │  Nextcloud      │   │  Nextcloud       │
                  │  (same Pi)      │   │  (internet)      │
                  └─────────────────┘   └──────────────────┘
```

---

## Data Model

```
Account
  id, label, webdav_url, username, password_enc, created_at
  # Both local and remote are just "accounts" — no distinction at model level

SyncRule
  id, label, enabled
  source_account_id → Account
  source_path        (e.g. /remote.php/dav/files/user/Photos)
  dest_account_id   → Account
  dest_path
  direction          ENUM(one_way, two_way)
  schedule_cron      (e.g. "0 3 * * *")
  delete_orphans     BOOL   # mirror deletions or not
  last_run_at, next_run_at

SyncJob
  id, sync_rule_id, started_at, finished_at
  status             ENUM(running, success, error, partial)
  files_added, files_updated, files_deleted, bytes_transferred

SyncLog
  id, sync_job_id, timestamp, level, message, path
```

---

## Component Breakdown

### 1. Backend — Python / FastAPI

- **Auth**: single bcrypt-hashed password stored in config; issues JWT on login
- **Account Manager**: CRUD for accounts; passwords AES-encrypted at rest (Fernet key from env/secret file)
- **Rule Manager**: CRUD for sync rules; validates WebDAV connectivity on save
- **Job Runner**: exposes endpoint to manually trigger a rule
- **History API**: paginated job + log queries
- **Browse API**: on-demand WebDAV proxy that lists a directory's immediate children for a given account; used by the frontend tree picker

### 2. Scheduler — APScheduler (in-process)

- Reads enabled `SyncRule` rows at startup and on every change
- Rebuilds cron triggers dynamically
- Hands jobs to the Sync Engine, writes results back to DB
- Persists job state to SQLite so reboots don't lose history

### 3. Sync Engine

```
for each SyncRule:
  1. LIST source tree  (WebDAV PROPFIND depth=∞, get path + ETag + mtime + size)
  2. LIST dest tree    (same)
  3. DIFF             → added / modified / deleted (compare ETag or mtime+size)
  4. COPY/PUT missing or changed files source→dest
  5. DELETE orphans on dest  (if delete_orphans=true)
  6. Write SyncLog entries per file operation
  7. Write SyncJob summary
```

Key library choices:
- `httpx` (async HTTP for WebDAV calls — lightweight, no extra deps)
- Or `webdavclient3` if PROPFIND parsing becomes complex

### 4. Frontend — Vue 3 + Vite (served as static files by FastAPI)

Pages:
- **Login** — password form, stores JWT in localStorage
- **Accounts** — list/add/edit/delete WebDAV accounts; test connection button
- **Sync Rules** — list rules, enable/disable toggle, run now button
- **Rule Editor** — pick source account, then use the interactive folder tree to select the source path; same for destination account + path; set cron schedule and options
- **History** — table of past jobs per rule, expandable log lines
- **Dashboard** — last run status per rule, next scheduled run

### 5. Directory Tree Browser

This is the primary UX for defining sync paths. Once an account is saved, the user never types a path manually — they navigate a visual folder tree.

**API endpoint:**
```
GET /api/browse?account_id=<id>&path=<encoded_path>
→ returns immediate children: [ { name, path, type: dir|file, size, mtime } ]
```

The backend issues a `PROPFIND depth=1` against the WebDAV URL for the given path and forwards the parsed result. Credentials are never exposed to the frontend.

**Frontend tree component (Rule Editor):**

```
Rule Editor
  ┌─ Source ──────────────────────────────────────────┐
  │  Account: [Local Nextcloud ▼]                     │
  │                                                   │
  │  ▼ /                                              │
  │    ▼ Files/                                       │
  │      ▶ Documents/                                 │
  │      ▼ Photos/          ← selected                │
  │          ▶ 2024/                                  │
  │          ▶ 2025/                                  │
  │      ▶ Music/                                     │
  └───────────────────────────────────────────────────┘
  ┌─ Destination ─────────────────────────────────────┐
  │  Account: [Remote Backup ▼]                       │
  │                                                   │
  │  ▼ /                                              │
  │    ▼ Files/                                       │
  │      ▶ Backups/         ← selected                │
  └───────────────────────────────────────────────────┘
```

**Behavior:**
- Tree nodes are **lazy-loaded**: expanding a folder triggers `GET /api/browse` for that path only — no full tree scan on open
- Directories only are shown (files are greyed out / hidden) since the unit of sync is a folder
- The selected path is stored as the `source_path` / `dest_path` on the SyncRule
- A **refresh** button re-fetches the current node in case the remote changed
- If the account credentials are invalid or the server is unreachable, the tree shows an inline error instead of failing silently

---

## Security

| Concern | Solution |
|---|---|
| Web UI access | JWT (HS256), short expiry + refresh token in httpOnly cookie |
| WebDAV credentials | AES-Fernet encrypted in SQLite; key in env var or `/etc/next-sync/secret.key` |
| HTTPS | Nginx reverse proxy with Let's Encrypt (or self-signed for LAN-only) |
| Pi exposure | Bind to localhost + Nginx, or use Tailscale for remote access |

---

## Deployment on Raspberry Pi

```
/opt/next-sync/
  backend/        # Python package
  frontend/dist/  # built Vue app (served by FastAPI as static)
  data/
    app.db        # SQLite
    secret.key    # Fernet key
  .env            # SECRET_KEY, PORT, etc.
```

**Process management**: single `systemd` unit that starts the FastAPI app (via `uvicorn`). APScheduler runs inside the same process.

```
[Unit]
Description=NextSync
After=network.target

[Service]
WorkingDirectory=/opt/next-sync
EnvironmentFile=/opt/next-sync/.env
ExecStart=/opt/next-sync/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8080
Restart=always
```

Nginx proxies `https://pi.local/` → `http://127.0.0.1:8080/`.

---

## Tech Stack Summary

| Layer | Choice | Reason |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Excellent WebDAV/HTTP libs, async I/O, lightweight |
| DB | SQLite + SQLAlchemy | Zero-config, sufficient for single-user |
| Scheduler | APScheduler 4 | In-process, cron syntax, SQLite job store |
| HTTP/WebDAV | httpx | Async, no heavy deps |
| Frontend | Vue 3 + Vite | Lightweight, fast to build |
| Auth | JWT + bcrypt | Standard, stateless |
| Process | systemd + uvicorn | Native Pi service management |
| TLS termination | Nginx | Keeps app simple |

---

## Key Design Decisions & Trade-offs

- **No agent on remote side** — pure WebDAV means any Nextcloud (or ownCloud, or generic WebDAV) works as destination
- **One-way default** — backup semantics are clear; two-way is opt-in per rule with explicit conflict handling (last-write-wins or skip)
- **ETag-first, mtime+size fallback** — works with Nextcloud's chunked upload responses
- **Lazy tree loading** — `PROPFIND depth=1` per node instead of depth=∞ keeps the browser snappy even for large accounts; full depth=∞ is reserved for the sync engine at job time
- **Single process** — simpler than a task queue (Celery/Redis) for this scale; replace with a proper queue only if sync jobs become parallel or very long
- **SQLite over Postgres** — perfectly adequate for one user's audit logs; easy to back up with `cp`
