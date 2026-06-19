"""FastAPI application factory and entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import SessionLocal, init_db
from backend.routers import accounts, auth, browse, jobs, rules
from backend.sync.scheduler import SyncScheduler


async def _mark_stale_jobs_failed() -> None:
    """Mark any jobs left in 'running' state (from a previous crash) as 'error'."""
    from datetime import datetime, timezone

    from sqlalchemy import update

    from backend.models import JobStatus, SyncJob

    async with SessionLocal() as db:
        await db.execute(
            update(SyncJob)
            .where(SyncJob.status == JobStatus.running)
            .values(status=JobStatus.error, finished_at=datetime.now(timezone.utc))
        )
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await _mark_stale_jobs_failed()

    scheduler = SyncScheduler()
    scheduler.start()
    await scheduler.load_rules()
    app.state.scheduler = scheduler

    yield

    # Shutdown
    scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="jc://next-sync/",
        description="Nextcloud WebDAV sync manager",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tighten in production via env
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(accounts.router)
    app.include_router(rules.router)
    app.include_router(browse.router)
    app.include_router(jobs.router)

    # Serve the built frontend from frontend/dist if it exists
    from pathlib import Path

    from fastapi.responses import FileResponse

    dist = Path(__file__).parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            file = dist / full_path
            if file.is_file():
                return FileResponse(str(file))
            return FileResponse(str(dist / "index.html"))

    return app


app = create_app()


def cli() -> None:
    """Entry point for `next-sync` command."""
    import argparse

    import uvicorn

    from backend.config import settings

    parser = argparse.ArgumentParser(prog="next-sync")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    cli()
