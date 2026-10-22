import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware as _BaseCORSMiddleware
from starlette.types import Receive, Scope, Send


class CORSMiddleware(_BaseCORSMiddleware):
    """CORS that passes WebSockets through; they authenticate by JWT in the handler, not by origin."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

from config import settings

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=True,
        traces_sample_rate=0.1,
        environment=settings.STAGE,
    )

if settings.LOGFIRE_TOKEN:
    import logfire
    logfire.configure(token=settings.LOGFIRE_TOKEN, service_name="supavault-api")
    logfire.instrument_asyncpg()

from routes.documents import router as documents_router
from routes.events import router as events_router
from routes.health import router as health_router
from routes.knowledge_bases import router as knowledge_bases_router
from routes.me import router as me_router
from routes.usage import router as usage_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.MODE == "local":
        async with _local_lifespan(app):
            yield
        return

    # Prefetch so a JWKS outage surfaces at boot, not behind the first auth error.
    from auth import prefetch_jwks
    await prefetch_jwks()

    import asyncpg
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=2, max_size=10)
    app.state.pool = pool
    app.state.mode = "hosted"

    s3_service = None
    ocr_service = None
    if settings.S3_BUCKET:
        from services.s3 import S3Service
        s3_service = S3Service()
    if s3_service:
        from services.ocr import OCRService
        ocr_service = OCRService(s3_service, pool)

    app.state.s3_service = s3_service
    app.state.ocr_service = ocr_service
    app.state.auth_provider = None  # None selects Supabase JWKS auth

    from services.hosted import HostedServiceFactory
    app.state.factory = HostedServiceFactory(pool, s3_service, ocr_service)

    from routes.ws import setup_listener
    listener_task = await setup_listener(settings.listen_database_url)

    from infra.tus import cleanup_stale_uploads
    cleanup_task = asyncio.create_task(cleanup_stale_uploads())

    if ocr_service:
        rows = await pool.fetch(
            "SELECT id::text, user_id::text FROM documents "
            "WHERE status IN ('pending', 'processing') AND NOT archived"
        )
        for row in rows:
            logger.info("Recovering stuck document %s", row["id"][:8])
            asyncio.create_task(ocr_service.process_document(row["id"], row["user_id"]))

    yield

    cleanup_task.cancel()
    listener_task.cancel()
    await pool.close()


async def _local_lifespan_inner(app: FastAPI):
    """Local mode: SQLite + local filesystem + single-user auth."""
    import uuid
    from pathlib import Path

    from infra.auth.local import LocalAuthProvider
    from infra.db.sqlite import create_pool as create_sqlite_pool

    workspace = Path(settings.WORKSPACE_PATH).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "wiki").mkdir(exist_ok=True)
    (workspace / ".llmwiki").mkdir(exist_ok=True)
    (workspace / ".llmwiki" / "cache").mkdir(exist_ok=True)

    db_path = str(workspace / ".llmwiki" / "index.db")
    db = await create_sqlite_pool(db_path)

    local_user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "local"))
    auth_provider = LocalAuthProvider(local_user_id)

    cursor = await db.execute("SELECT id FROM workspace LIMIT 1")
    if not await cursor.fetchone():
        ws_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workspace (id, name, description, user_id) VALUES (?, ?, '', ?)",
            (ws_id, workspace.name, local_user_id),
        )
        await db.commit()
        logger.info("Initialized local workspace: %s", workspace)

    app.state.mode = "local"
    app.state.pool = None
    app.state.sqlite_db = db
    app.state.s3_service = None
    app.state.ocr_service = None
    app.state.auth_provider = auth_provider
    app.state.workspace_path = str(workspace)

    from services.local import LocalServiceFactory
    app.state.factory = LocalServiceFactory(db)

    logger.info("Local mode — workspace: %s", workspace)
    return db


@asynccontextmanager
async def _local_lifespan(app: FastAPI):
    db = await _local_lifespan_inner(app)
    from pathlib import Path

    from infra.db.sqlite import create_pool as create_sqlite_pool
    workspace = Path(app.state.workspace_path)
    db_path = str(workspace / ".llmwiki" / "index.db")

    # Own connections, so a background commit can't flush a request's open transaction.
    reconcile_db = await create_sqlite_pool(db_path, init_schema=False)
    watcher_db = await create_sqlite_pool(db_path, init_schema=False)

    from domain.local_processor import reconcile_workspace
    reconcile_task = asyncio.create_task(reconcile_workspace(reconcile_db, workspace))

    watcher_task = None
    try:
        from domain.watcher import watch_workspace
        watcher_task = asyncio.create_task(watch_workspace(watcher_db, workspace))
        logger.info("File watcher started")
    except ImportError:
        logger.warning("watchfiles not installed — file watcher disabled")

    try:
        yield
    finally:
        reconcile_task.cancel()
        with suppress(asyncio.CancelledError):
            await reconcile_task
        if watcher_task:
            watcher_task.cancel()
            with suppress(asyncio.CancelledError):
                await watcher_task
        await reconcile_db.close()
        await watcher_db.close()
        await db.close()


app = FastAPI(title="LLM Wiki API", lifespan=lifespan)

# Broad ceiling on every route; hot endpoints add tighter `@limiter.limit(...)`.
if settings.MODE != "local":
    from infra.rate_limit import limiter
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

local_extension_origin_regex = None
if settings.MODE == "local":
    from infra.local_http import LocalHTTPBoundaryMiddleware, extension_origin_regex

    local_extension_origin_regex = extension_origin_regex(
        settings.local_extension_origins,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.APP_URL],
    # Local clips can come from the extension popup or its background worker.
    allow_origin_regex=local_extension_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Location", "Upload-Offset", "Upload-Length",
        "Tus-Resumable", "Tus-Version", "Tus-Max-Size", "Tus-Extension",
        "X-Document-Id",
    ],
    # Default is 600s; browsers clamp to their own cap (Chrome 7200s, Firefox 86400s).
    max_age=86400,
)

if settings.MODE == "local":
    # Outermost (added after CORS) so Host validation also covers preflights.
    app.add_middleware(
        LocalHTTPBoundaryMiddleware,
        app_origin=settings.APP_URL,
        extension_origins=settings.local_extension_origins,
    )

if settings.LOGFIRE_TOKEN:
    import logfire
    logfire.instrument_fastapi(app)

app.include_router(health_router)
app.include_router(me_router)
app.include_router(usage_router)
app.include_router(knowledge_bases_router)
app.include_router(documents_router)
app.include_router(events_router)

if settings.MODE == "local":
    from routes.files import router as files_router
    from routes.files import set_workspace_root
    from routes.local_graph import router as local_graph_router
    from routes.local_upload import router as local_upload_router
    app.include_router(local_upload_router)
    app.include_router(files_router)
    app.include_router(local_graph_router)
    set_workspace_root(settings.WORKSPACE_PATH)
else:
    from infra.tus import router as tus_router
    from routes.graph import router as graph_router
    from routes.public import router as public_router
    from routes.quiz import router as quiz_router
    from routes.ws import router as ws_router
    app.include_router(tus_router)
    app.include_router(graph_router)
    app.include_router(ws_router)
    app.include_router(public_router)
    app.include_router(quiz_router)
