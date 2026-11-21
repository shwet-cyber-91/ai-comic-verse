"""FastAPI application.

Run it with:

    python -m app.main                 # from backend/
    uvicorn app.main:app --reload      # the same thing, with reload

``/static`` serves everything the pipeline wrote (panel art, page composites and
exports), so the frontend never needs a second server in development.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router, shutdown_pool
from .config import get_settings
from .db import count_projects, init_db
from .logging_config import configure_logging, get_logger
from .nodes.base import NodeError
from .providers.registry import provider_info

log = get_logger("main")

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    settings.ensure_dirs()
    init_db()

    info = provider_info()
    log.info("%s v%s (%s)", settings.app_name, APP_VERSION, settings.environment)
    log.info(
        "providers -> llm=%s image=%s stt=%s embedding=%s memory=%s",
        info.llm,
        info.image,
        info.stt,
        info.embedding,
        info.vector_store,
    )
    if info.llm == "mock" and info.image == "mock":
        log.warning(
            "MOCK MODE: no API keys configured, so panels are drawn locally with "
            "Pillow and the story is analysed with the built-in engine. "
            "Everything works end to end - the art is just placeholder."
        )
    log.info("projects in the database: %d", count_projects())

    try:
        yield
    except asyncio.CancelledError:
        log.info("shutdown requested; stopping gracefully")
    finally:
        shutdown_pool(wait=False)
        log.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title=settings.app_name,
        version=APP_VERSION,
        description=(
            "Reference-image-conditioned comic generation. Story in, comic out: "
            "characters keep their design across every panel via CLIP-scored "
            "continuity checking with a bounded regeneration loop."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    app.include_router(router)

    static_dir = Path(settings.storage_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "app": settings.app_name,
            "version": APP_VERSION,
            "docs": "/docs",
            "health": "/api/health",
        }

    @app.exception_handler(NodeError)
    async def node_error_handler(request: Request, exc: NodeError) -> JSONResponse:
        log.error("pipeline node failed on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": exc.message, "node": exc.node, "path": request.url.path},
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    try:
        uvicorn.run(
            "app.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.debug,
            log_level="info",
        )
    except KeyboardInterrupt:
        log.info("shutdown requested via keyboard interrupt")


if __name__ == "__main__":
    main()
