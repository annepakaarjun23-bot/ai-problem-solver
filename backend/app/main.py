"""FastAPI application: wiring, lifespan (resources) and error handling."""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.deps import get_db
from app.errors import ServiceError
from app.routers import auth, conversations, generations
from app.services.ai_service import AIService, build_client
from app.services.generation_manager import GenerationManager, mark_interrupted_generations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


class RequestTimingMiddleware:
    """Log API time-to-first-response-byte without logging query/body contents."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        logged = False

        async def timed_send(message):
            nonlocal logged
            if message["type"] == "http.response.start" and not logged:
                logged = True
                duration_ms = (time.perf_counter() - started) * 1000
                request = scope["method"], scope["path"]
                log.info(
                    "http.request method=%s path=%s status=%s duration_ms=%.1f",
                    request[0],
                    request[1],
                    message["status"],
                    duration_ms,
                )
            await send(message)

        await self.app(scope, receive, timed_send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_for_runtime()

    # The URL is also used by Psycopg for the LangGraph checkpointer, where
    # Neon libpq options (sslmode/channel_binding) are valid. The asyncpg
    # SQLAlchemy dialect expects SSL as `ssl`, so translate those options here.
    db_url = make_url(settings.DATABASE_URL)
    db_query = dict(db_url.query)
    sslmode = db_query.pop("sslmode", None)
    db_query.pop("channel_binding", None)
    engine = create_async_engine(
        db_url.set(query=db_query),
        pool_pre_ping=True,
        connect_args={"ssl": sslmode} if sslmode else {},
    )

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def start_query_timer(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_aips_query_starts", []).append(time.perf_counter())

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def log_slow_query(conn, cursor, statement, parameters, context, executemany):
        starts = conn.info.get("_aips_query_starts", [])
        if not starts:
            return
        started = starts.pop()
        duration_ms = (time.perf_counter() - started) * 1000
        if duration_ms >= 100:
            operation = statement.lstrip().split(None, 1)[0].upper()
            log.info("db.query operation=%s duration_ms=%.1f", operation, duration_ms)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # LangGraph checkpointer on its own psycopg pool; it manages its own tables.
    pool = AsyncConnectionPool(
        settings.checkpointer_dsn,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True, timeout=30)
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    await mark_interrupted_generations(session_factory)

    ai = AIService(settings, session_factory, checkpointer, client=build_client(settings))
    manager = GenerationManager(session_factory, ai)

    app.state.session_factory = session_factory
    app.state.checkpointer = checkpointer
    app.state.ai = ai
    app.state.manager = manager
    if not settings.ai_configured:
        log.warning("AI_ROUTER_API_KEY is not set: chat generation will report a clear error.")
    log.info("Started (model=%s)", settings.AI_ROUTER_MODEL)
    try:
        yield
    finally:
        await manager.shutdown()
        await pool.close()
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Problem Solver", version="1.0.0", lifespan=lifespan)
    app.add_middleware(RequestTimingMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )

    @app.exception_handler(ServiceError)
    async def service_error_handler(_: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.include_router(auth.router)
    app.include_router(conversations.router)
    app.include_router(generations.router)

    @app.get("/api/v1/health", tags=["health"])
    async def health(db: AsyncSession = Depends(get_db)):
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "ai_configured": settings.ai_configured}

    return app


app = create_app()
