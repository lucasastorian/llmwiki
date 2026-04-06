import asyncio
import logging
from contextlib import asynccontextmanager

import asyncpg
import logfire
import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=True,
        traces_sample_rate=0.1,
        environment=settings.STAGE,
    )

if settings.LOGFIRE_TOKEN:
    logfire.configure(token=settings.LOGFIRE_TOKEN, service_name="supavault-api")
    logfire.instrument_asyncpg()

from routes.health import router as health_router
from routes.knowledge_bases import router as knowledge_bases_router
from routes.documents import router as documents_router
from routes.api_keys import router as api_keys_router
from routes.me import router as me_router
from routes.usage import router as usage_router
from routes.admin import router as admin_router
from infra.tus import router as tus_router, cleanup_stale_uploads


async def _recover_stuck_documents(pool: asyncpg.Pool, ocr_service):
    rows = await pool.fetch(
        "SELECT id::text, user_id::text FROM documents "
        "WHERE status IN ('pending', 'processing') AND NOT archived"
    )
    for row in rows:
        logger.info("Recovering stuck document %s", row["id"][:8])
        asyncio.create_task(ocr_service.process_document(row["id"], row["user_id"]))


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=2, max_size=10)
    app.state.pool = pool

    s3_service = None
    ocr_service = None
    if settings.AWS_ACCESS_KEY_ID and settings.S3_BUCKET:
        from services.s3 import S3Service
        s3_service = S3Service()
    if s3_service:
        from services.ocr import OCRService
        ocr_service = OCRService(s3_service, pool)

    app.state.s3_service = s3_service
    app.state.ocr_service = ocr_service

    cleanup_task = asyncio.create_task(cleanup_stale_uploads())

    if ocr_service:
        await _recover_stuck_documents(pool, ocr_service)

    yield

    cleanup_task.cancel()
    await pool.close()


app = FastAPI(title="Supavault API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.APP_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Location", "Upload-Offset", "Upload-Length",
        "Tus-Resumable", "Tus-Version", "Tus-Max-Size", "Tus-Extension",
        "X-Document-Id",
    ],
)

if settings.LOGFIRE_TOKEN:
    logfire.instrument_fastapi(app)

app.include_router(health_router)
app.include_router(knowledge_bases_router)
app.include_router(documents_router)
app.include_router(api_keys_router)
app.include_router(me_router)
app.include_router(usage_router)
app.include_router(admin_router)
app.include_router(tus_router)
