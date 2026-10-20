# Test suite for next-sync

## Context
The repo has no tests. The sync engine just got a large rework (two-way state file, conflicts, folder-deletion fix), which was only verified with a throwaway script. The goal is a permanent backend + frontend suite that runs with one Docker command per side, so regressions are caught after future changes. No GitHub Actions, no local venv setup (user's choice).

## Approach

### Backend — pytest (`backend/tests/`)

**Config (`pyproject.toml`)**
- `[project.optional-dependencies] test = ["pytest>=8", "pytest-asyncio>=0.24"]`
- `[tool.pytest.ini_options]`: `testpaths = ["backend/tests"]`, `asyncio_mode = "auto"`
- Exclude `backend.tests*` from `[tool.setuptools.packages.find]`, so the tests aren't included in the production image.

**`conftest.py`: isolation**
- `settings` (`backend/config.py`) and `engine` (`backend/database.py`) are created when the modules are imported. So before any `backend` import, conftest does the following:
  - sets `os.environ`: `SECRET_KEY`, a freshly generated `FERNET_KEY`, `APP_PASSWORD_HASH=""`, `DATA_DIR=<tmp dir>`
  - `chdir`s to a temp dir, so the real `.env` is never read or written (`_write_env_var` in `routers/auth.py` writes `.env` in the cwd).
- An autouse async fixture runs `init_db()` before each test. After the test it drops and recreates all tables and calls `await engine.dispose()`, so no aiosqlite connection outlives a test's event loop.
- `api` fixture:
  - `httpx.AsyncClient(transport=ASGITransport(app))`
  - The app lifespan is entered via `app.router.lifespan_context(app)`, so `app.state.scheduler` exists and stale-job marking runs.
  - Login is done by setting `settings.app_password_hash` and adding a Bearer header from `create_access_token()`.
  - An `anon_api` variant has no token.
- Helper factories `make_account(server, ...)` and `make_rule(...)` insert rows directly through `SessionLocal`. Account passwords are encrypted with `backend/crypto.encrypt`.

**`fakedav.py`: in-memory WebDAV server**
- An `httpx.MockTransport` handler, so the real `WebDAVClient` (`backend/sync/webdav.py`) runs end to end, including XML parsing.
- The fixture monkeypatches `backend.sync.webdav.httpx.AsyncClient` to inject the transport. Requests are routed by host (`http://src.test/dav`, `http://dst.test/dav`).
- Supports:
  - `PROPFIND`, depth `0`/`1`/`infinity`: multistatus with `resourcetype`, RFC 1123 `getlastmodified`, `getcontentlength`, `getetag`, and quota props
  - `GET`, plus `PUT` with an async body via `aread()`: `409` if the parent is missing
  - `DELETE`: recursive, `404` if missing
  - `MKCOL`: `405` if it exists, `409` if the parent is missing
  - The Nextcloud chunked upload flow: `MKCOL` and chunk `PUT`s under `/remote.php/dav/uploads/…`, then `MOVE`
- A controllable clock that advances 1 s per write, since `getlastmodified` has 1-second resolution.
- Helpers: `mkdir`, `write`, `rm`, `files()`, and `fail(method, path, status)` for error injection.

**Test modules**
- **`test_webdav.py`:**
  - propfind parsing: dirs vs files, base-path stripping, percent-encoded and umlaut names, non-200 propstat skipped
  - `copy_to`
  - `mkcol` ignores 405
  - `get_quota`: negative values become `None`
  - `_encode_path`
  - chunked upload, with `CHUNKED_UPLOAD_THRESHOLD`/`UPLOAD_CHUNK_SIZE` monkeypatched small, and cleanup on failure
- **`test_engine_helpers.py`** (pure functions in `backend/sync/engine.py`):
  - `_is_changed`, `_build_map`
  - `_Exclusion`: patterns, sizes, hidden, subfolders, folder names, `is_ignored`
  - `_two_way_action` truth table, `_dirty_paths`
  - `_known_entries`: a side missing, paths changed
  - `_under_any`
  - `_exc_detail` / `_body_excerpt`: Sabre XML, HTML page, redirects
- **`test_engine_one_way.py`** (through `run_sync(rule_id)` with the real DB, asserting on the `SyncJob` status/counters and the `SyncLog` messages):
  - add, update, unchanged
  - `delete_orphans` on and off
  - **a deleted folder's contents are not deleted again** (regression for today's fix)
  - excluded folder roots are removed from the destination
  - a folder that can't be created skips its contents with a warning
  - a per-file error makes the job `partial`
  - no `.next-sync` is written in one-way mode
- **`test_engine_two_way.py`** (the scratch scenarios, made permanent):
  - first run merges both sides without deleting
  - deletions propagate both ways, folders included
  - edits propagate both ways, with no re-upload afterwards and an idle run transferring nothing
  - conflicts:
    - both sides changed: reported on every run until resolved, and resolved by deleting one version
    - identical content: no conflict
    - file vs folder of the same name
  - deleted on one side but modified on the other: kept
  - a missing or corrupt state file: nothing deleted
  - two rules sharing a root keep separate state
  - without `delete_orphans`, nothing is ever deleted
- **`test_api_auth.py`:**
  - `/status`
  - `/setup`: min length, writes `.env` in the cwd, locked afterwards
  - `/login`: correct and wrong password
  - protected routes return 401 with no token, an expired token, or a token with the wrong signature
- **`test_api_accounts.py`:**
  - CRUD
  - the password is encrypted and never returned
  - partial update; `storage_limit_bytes` can be cleared to null
  - `/test` and `/quota` against the fake server, plus their error path
  - 404s
- **`test_api_rules.py`:**
  - CRUD, with the JSON list fields round-tripping
  - create, update and delete add, replace and remove the scheduler job (`rule_<id>`)
  - a disabled rule is unscheduled
  - an invalid cron is stored without crashing the app
  - `/run` queues `manual_<id>`
  - 404s
- **`test_api_browse.py`:**
  - lists entries and excludes the requested path itself
  - depth validation
  - 404 for an unknown account
  - 502 on a WebDAV error
- **`test_api_jobs.py`:**
  - list with `rule_id` filter and pagination
  - get, logs
  - abort returns 409 when the job isn't running
  - abort cancels a running job: the fake server blocks on PROPFIND, and the job ends as `aborted`
- **`test_scheduler.py`:**
  - `SyncScheduler` add/replace/remove, disabled rule, invalid cron, `load_rules` only loads enabled rules
  - `main._mark_stale_jobs_failed` turns `running` into `error`

### Frontend — Vitest (`frontend/src/**/*.spec.js`)
- devDependencies: `vitest@^2` (matches Vite 5), `@vue/test-utils`, `jsdom`. Script `"test": "vitest run"`.
- A `test: { environment: 'jsdom' }` block in `frontend/vite.config.js`, so the existing `@` alias and Vue plugin are reused.
- **`stores/auth.spec.js`:**
  - `isTokenExpired`: missing, malformed, expired, valid, base64url
  - an expired stored token is dropped on load
  - setup/login/logout persist to localStorage, with `authApi` mocked
- **`api/client.spec.js`** (with a stub axios adapter):
  - Bearer header added
  - on 401: logout and redirect only when the sent token equals the current one and the URL isn't `/auth/`
  - network error leads to `markOffline`, a response to `markOnline`
- **`router/index.spec.js`:**
  - public routes pass
  - unauthenticated users go to `/setup` or `/login` depending on `checkSetup`
  - a `checkSetup` failure is tolerated
  - `reloadOnce` reloads only once per session
- **`components/FolderTree.spec.js`** (`browseApi` mocked):
  - root shows folders only
  - expand inserts children at depth + 1
  - collapse removes all descendants, including nested expanded ones
  - refresh reloads
  - clicking a folder emits `update:modelValue`
  - root error with Retry, and per-node error
- **`stores/connectivity.spec.js`** (fake timers): offline starts the probe, online stops it.

### Running: Docker (`docker-compose.dev.yml`)
Add two services under `profiles: [test]`, so `up` doesn't start them:
- `backend-test`: `python:3.12-slim`, mounts `.` and pip-cache. Runs `pip install -e .[test] -q && pytest`. No `env_file`.
- `frontend-test`: `node:20-alpine`, mounts `./frontend` and npm-cache. Runs `npm install && npm test`.

Commands:
```bash
docker compose -f docker-compose.dev.yml run --rm backend-test
docker compose -f docker-compose.dev.yml run --rm frontend-test
```
Extra pytest args can be passed via `run --rm backend-test pytest -k two_way`.

### Docs and housekeeping
- Add the two commands to the Development Commands section in `CLAUDE.md`, with a line saying engine/API changes should come with tests in `backend/tests/`. Add a short "Tests" section to `README.md`.
- Add `.pytest_cache/` to `.gitignore`.

## Critical files
- New: `backend/tests/{conftest.py, fakedav.py, test_*.py}`, `frontend/src/**/*.spec.js`
- Modified: `pyproject.toml`, `frontend/package.json` (+ lockfile), `frontend/vite.config.js`, `docker-compose.dev.yml`, `.gitignore`, `CLAUDE.md`, `README.md`
- No production code changes planned. If a test exposes a real bug, I'll report it rather than fold a fix in silently.

## Verification
1. Run both Docker commands; all tests pass.
2. Sanity check that the tests actually catch regressions: temporarily revert the deleted-folder skip in `engine.py` and the conflict branch, confirm the matching tests fail, then restore.
3. Confirm `docker compose -f docker-compose.dev.yml up` still starts only backend and frontend.
4. Commit on the current branch (`two-way-sync-state`) when the user asks.
