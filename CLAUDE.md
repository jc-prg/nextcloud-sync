# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Start dev stack (hot reload):**
```bash
docker compose -f docker-compose.dev.yml up
```
- Backend (FastAPI + uvicorn --reload): http://localhost:8080
- Frontend (Vite dev server): http://localhost:5173

**Start production stack:**
```bash
docker compose up --build
```

**Restart backend only (e.g. after .env changes):**
```bash
docker compose -f docker-compose.dev.yml restart backend
```

**Frontend only (without Docker):**
```bash
cd frontend && npm install && npm run dev
```

**Build frontend:**
```bash
cd frontend && npm run build
```

## Architecture

### Request Flow
Browser → Vite dev proxy (`/api/*` → `localhost:8080`) → FastAPI → SQLite

In production, FastAPI serves the built frontend from `frontend/dist/` as static files (no separate web server needed).

### Backend (`backend/`)

Single Python process running FastAPI + APScheduler in the same event loop.

- **`main.py`** — app factory, lifespan hook (calls `init_db()` and boots the scheduler)
- **`config.py`** — `Settings` loaded from `.env` via pydantic-settings; imported as `settings` singleton
- **`database.py`** — async SQLAlchemy engine + `SessionLocal`; `get_db()` is the FastAPI dependency
- **`models.py`** — four ORM models: `Account`, `SyncRule`, `SyncJob`, `SyncLog`
- **`crypto.py`** — Fernet encrypt/decrypt; key comes from `settings.fernet_key`
- **`auth.py`** — `verify_password` / `hash_password` (bcrypt), `create_access_token` / `get_current_user` (JWT via python-jose)

**Routers** (`backend/routers/`): each file maps to one resource group (`/api/auth`, `/api/accounts`, `/api/rules`, `/api/browse`, `/api/jobs`). Routers access the scheduler via `request.app.state.scheduler`.

**Sync layer** (`backend/sync/`):
- `webdav.py` — `WebDAVClient` async context manager; `propfind(path, depth)` parses multistatus XML and returns `DavEntry` list with `rel_path` (relative to the account's WebDAV base)
- `engine.py` — `run_sync(rule_id)` opens its own `SessionLocal`, lists both trees with `depth=infinity`, diffs by ETag then mtime+size, streams files with GET→PUT, marks job `partial` on per-file errors
- `scheduler.py` — `SyncScheduler` wraps `AsyncIOScheduler`; `add_rule(rule)` uses `replace_existing=True` so it doubles as reschedule; scheduler instance lives on `app.state.scheduler`

### Frontend (`frontend/src/`)

Vue 3 SPA with `<script setup>` throughout.

- **`api/client.js`** — axios instance with JWT request interceptor and 401 redirect interceptor. The 401 interceptor skips `/auth/` URLs to avoid redirecting during login failures.
- **`stores/auth.js`** — Pinia store; holds JWT token (persisted in localStorage), `isConfigured` flag, setup/login/logout actions
- **`router/index.js`** — navigation guard checks `auth.token`; if missing, calls `auth.checkSetup()` to decide between `/login` and `/setup`
- **`components/FolderTree.vue`** — key component; maintains a flat ordered list of visible nodes (no recursive component). Expand calls `GET /api/browse?account_id=&path=` (depth=1). Collapse splices descendants from the list by depth comparison.
- **`views/RuleEditorView.vue`** — uses `FolderTree` with `v-model` for both source and destination path selection; shows the tree until a path is selected, then shows the selected path with a "Change" button

### Data Model

```
Account ──< SyncRule (source_account_id, dest_account_id)
SyncRule ──< SyncJob ──< SyncLog
```

`SyncRule.schedule_cron` is a standard 5-field UTC cron expression fed directly to `CronTrigger.from_crontab()`.

### Password / Auth Flow

- First run: `POST /api/auth/setup` hashes password with bcrypt, writes hash to `.env` via `_write_env_var()`, updates `settings.app_password_hash` in-process, returns JWT
- Subsequent runs: `POST /api/auth/login` verifies against stored hash
- Reset: clear `APP_PASSWORD_HASH=` in `.env`, restart backend

### Environment

`.env` is required (copy from `.env.example`). The two secrets that must be pre-generated:
- `SECRET_KEY` — JWT signing key (`python3 -c "import secrets; print(secrets.token_hex(32))"`)
- `FERNET_KEY` — WebDAV credential encryption (`python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
