from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import books, groups, health, issues, repo, sync, updates
from .config import APP_NAME, APP_VERSION


def create_app(repo_path: str) -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION)
    app.state.repo_path = repo_path

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(repo.router)
    app.include_router(books.router)
    app.include_router(groups.router)
    app.include_router(issues.router)
    app.include_router(updates.router)
    app.include_router(sync.router)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
