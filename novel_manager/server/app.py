from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import books, groups, health, incoming, issues, operations, pairing, repo, sync, updates
from .auth_middleware import AuthMiddleware
from .config import APP_NAME, APP_VERSION


def create_app(repo_path: str) -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION)
    app.state.repo_path = repo_path

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth middleware for device authorization
    app.add_middleware(AuthMiddleware)

    # API routers
    app.include_router(health.router)
    app.include_router(repo.router)
    app.include_router(pairing.router)
    app.include_router(books.router)
    app.include_router(groups.router)
    app.include_router(issues.router)
    app.include_router(updates.router)
    app.include_router(sync.router)
    app.include_router(incoming.router)
    app.include_router(operations.router)

    # Static files (must be last)
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
