# NextSync

A self-hosted Nextcloud WebDAV sync manager running on a Raspberry Pi (or any Linux box).
Sync selected folders between a local Nextcloud instance and a remote one on a schedule — useful as an automated offsite backup.

## Features

- **WebDAV sync** between any two Nextcloud (or generic WebDAV) accounts
- **Visual folder picker** — browse and select source/destination folders from a live tree view
- **Scheduled sync** via cron expressions, configurable per rule
- **One-way or two-way** sync direction per rule
- **Delete orphans** option to mirror deletions
- **Job history** with per-file log viewer
- **Web UI** — Vue 3 SPA served by the backend
- **Single-user** with bcrypt password protection and JWT session tokens
- **Encrypted credentials** — WebDAV passwords stored with AES-Fernet encryption at rest

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), APScheduler |
| Database | SQLite (via aiosqlite) |
| WebDAV | httpx (async, no extra deps) |
| Frontend | Vue 3, Vite, Pinia, Vue Router |
| Auth | bcrypt + JWT (HS256) |
| Runtime | Docker / Docker Compose |

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url>
cd next-sync
cp .env.example .env
```

Edit `.env` and fill in the two required secrets (leave `APP_PASSWORD_HASH` empty — it is set via the web UI on first run):

```bash
# Generate SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"

# Generate FERNET_KEY (requires the cryptography package)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. Run with Docker Compose

**Production** (single container, frontend bundled):

```bash
docker compose up --build
```

**Development** (hot reload for both backend and frontend):

```bash
docker compose -f docker-compose.dev.yml up
```

| Service | URL |
|---|---|
| App (production) | http://localhost:8080 |
| Frontend dev server | http://localhost:5173 |
| Backend API | http://localhost:8080/api |

### 3. First-run setup

Open the app in your browser. You will be prompted to set a password on first run. This is stored as a bcrypt hash in `.env` and the endpoint locks itself permanently afterwards.

## Configuration

All configuration lives in `.env`:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Random hex string used to sign JWT tokens |
| `FERNET_KEY` | Fernet key used to encrypt WebDAV passwords at rest |
| `APP_PASSWORD_HASH` | bcrypt hash of the web UI password (set via setup screen) |
| `DATA_DIR` | Directory for SQLite database (default: `data/`) |
| `PORT` | Backend port (default: `8080`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime (default: `60`) |

### Reset the password

Clear `APP_PASSWORD_HASH` in `.env` and restart the backend:

```bash
# In .env:
APP_PASSWORD_HASH=

docker compose -f docker-compose.dev.yml restart backend
# or
docker compose restart app
```

The setup screen will reappear on next page load.

## Project Structure

```
next-sync/
├── backend/
│   ├── main.py          # FastAPI app, lifespan, static file serving
│   ├── config.py        # Settings from .env (pydantic-settings)
│   ├── database.py      # Async SQLAlchemy engine + session
│   ├── models.py        # ORM: Account, SyncRule, SyncJob, SyncLog
│   ├── auth.py          # JWT creation/validation, password verify
│   ├── crypto.py        # Fernet encrypt/decrypt for WebDAV passwords
│   ├── routers/         # FastAPI routers (auth, accounts, rules, browse, jobs)
│   └── sync/
│       ├── webdav.py    # Async WebDAV client (PROPFIND / GET / PUT / DELETE)
│       ├── engine.py    # Sync logic: tree diff, copy, delete orphans
│       └── scheduler.py # APScheduler wrapper, one cron job per rule
├── frontend/
│   └── src/
│       ├── views/       # Login, Setup, Dashboard, Accounts, RuleEditor, History
│       ├── components/  # AppLayout, FolderTree, StatusBadge, ConfirmModal
│       ├── api/         # Axios wrappers per resource
│       └── stores/      # Pinia auth store
├── Dockerfile           # Multi-stage: node build → python serve
├── docker-compose.yml   # Production
└── docker-compose.dev.yml # Development (hot reload)
```

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/auth/status` | Check if app password is configured |
| `POST` | `/api/auth/setup` | First-run password setup (locks after use) |
| `POST` | `/api/auth/login` | Login, returns JWT |
| `GET/POST` | `/api/accounts` | List / create WebDAV accounts |
| `GET/PATCH/DELETE` | `/api/accounts/{id}` | Get / update / delete account |
| `POST` | `/api/accounts/{id}/test` | Test WebDAV connectivity |
| `GET/POST` | `/api/rules` | List / create sync rules |
| `GET/PATCH/DELETE` | `/api/rules/{id}` | Get / update / delete rule |
| `POST` | `/api/rules/{id}/run` | Trigger immediate sync |
| `GET` | `/api/browse` | Browse WebDAV folder tree (`?account_id=&path=`) |
| `GET` | `/api/jobs` | List sync jobs (filterable by `rule_id`) |
| `GET` | `/api/jobs/{id}/logs` | Per-file log entries for a job |

## Nextcloud WebDAV URL

When adding a Nextcloud account, the WebDAV URL should point to the files root for the user:

```
https://<your-nextcloud>/remote.php/dav/files/<username>
```

Example: `https://cloud.example.com/remote.php/dav/files/alice`
