"""FastAPI application entry.

Run with:  python -m gateway.app
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway import config


def _configure_logging() -> None:
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def create_app() -> FastAPI:
    _configure_logging()
    config.ensure_dirs()
    config.get_or_create_jwt_secret()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Startup
        from gateway.async_runner import get_queue
        from gateway.db import repo
        repo.init_db()
        logging.getLogger(__name__).info("DB initialized at %s", config.db_path_str())
        queue = get_queue()
        await queue.start()
        try:
            yield
        finally:
            await queue.stop()

    app = FastAPI(
        title="Agent Platform",
        version="0.1.0",
        description="User-facing gateway on top of TaskAgent.",
        lifespan=lifespan,
    )

    # CORS — open in dev; tighten in production via env
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "service": "agent-platform", "version": "0.1.0"}

    # Mount routers
    from gateway.routes import auth as auth_routes
    from gateway.routes import uploads as uploads_routes
    from gateway.routes import agents as agents_routes
    from gateway.routes import tasks as tasks_routes
    from gateway.routes import tools as tools_routes
    from gateway.routes import user_agents as user_agents_routes
    from gateway.routes import teams as teams_routes
    app.include_router(auth_routes.router)
    app.include_router(uploads_routes.router)
    app.include_router(agents_routes.router)
    app.include_router(tasks_routes.router)
    app.include_router(tools_routes.router)
    app.include_router(user_agents_routes.router)
    app.include_router(teams_routes.router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "gateway.app:app",
        host=config.HOST,
        port=config.PORT,
        log_level=config.LOG_LEVEL.lower(),
    )
