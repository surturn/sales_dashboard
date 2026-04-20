from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings
from backend.app.core.observability import init_logging, init_sentry
from backend.app.core.rate_limit import RateLimitExceeded, SlowAPIMiddleware, limiter, rate_limit_exceeded_handler
from backend.app.database import check_database_connection, init_db


# Initialize logging and observability early so modules imported below
# can use `get_logger()` safely during import-time.
settings = get_settings()
init_logging()
init_sentry()

from backend.app.api import approvals, auth, dashboard, hubspot, leads, outreach, reports, social, webhooks, workflows


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    try:
        check_database_connection()
    except Exception:
        if settings.APP_ENV == "production":
            raise
    # Ensure agent checkpoint backend is available in production.
    try:
        from backend.app.agents.base import get_checkpointer
        from backend.app.core.observability import get_logger

        logger = get_logger("startup")
        try:
            # Attempt to acquire and initialize the checkpointer. If this
            # fails in production we raise to stop the service from starting
            # without durable checkpoints for agents.
            await get_checkpointer()
            logger.info("agent_checkpointer_ready")
        except Exception as exc:
            logger.exception("agent_checkpointer_unavailable", error=str(exc))
            if settings.APP_ENV == "production":
                raise
    except Exception:
        # Importing the checkpointer module can fail if langgraph is not
        # installed; above we will raise in production, otherwise continue.
        if settings.APP_ENV == "production":
            raise
    try:
        from backend.app.core.observability import get_logger
        from backend.app.services.qdrant_client import ensure_collections, get_qdrant

        logger = get_logger("startup")
        client = await get_qdrant()
        try:
            await ensure_collections(client)
            logger.info("qdrant_collections_ready")
        finally:
            await client.close()
    except Exception as exc:
        try:
            from backend.app.core.observability import get_logger

            get_logger("startup").exception("qdrant_unavailable", error=str(exc))
        except Exception:
            pass
        if settings.APP_ENV == "production":
            raise
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(approvals, prefix=settings.API_PREFIX)
    app.include_router(auth, prefix=settings.API_PREFIX)
    app.include_router(dashboard, prefix=settings.API_PREFIX)
    app.include_router(hubspot, prefix=settings.API_PREFIX)
    app.include_router(leads, prefix=settings.API_PREFIX)
    app.include_router(outreach, prefix=settings.API_PREFIX)
    app.include_router(reports, prefix=settings.API_PREFIX)
    app.include_router(social, prefix=settings.API_PREFIX)
    app.include_router(workflows, prefix=settings.API_PREFIX)
    app.include_router(webhooks, prefix=settings.API_PREFIX)

    @app.get("/health")
    def health_check() -> dict:
        return {"status": "ok", "app": settings.APP_NAME, "environment": settings.APP_ENV}

    @app.get("/ready")
    async def readiness_check() -> dict:
        """Readiness probe for orchestration dependencies."""
        details: dict = {}
        healthy = True

        # Database check (run in thread to avoid blocking)
        try:
            await asyncio.to_thread(check_database_connection)
            details["database"] = "ok"
        except Exception as exc:
            details["database"] = f"error: {str(exc)}"
            healthy = False

        # Agent checkpointer (LangGraph AsyncRedisSaver)
        try:
            from backend.app.agents.base import get_checkpointer

            cp = await get_checkpointer()
            details["checkpointer"] = "ok"
            # Try to close any resources the checkpointer opened
            try:
                if hasattr(cp, "aclose"):
                    await cp.aclose()
                elif hasattr(cp, "close"):
                    cp.close()
            except Exception:
                # non-fatal, we've verified it can be constructed
                pass
        except Exception as exc:
            details["checkpointer"] = f"error: {str(exc)}"
            healthy = False

        try:
            from backend.app.services.qdrant_client import get_qdrant

            client = await get_qdrant()
            try:
                await client.get_collections()
                details["qdrant"] = "ok"
            finally:
                await client.close()
        except Exception as exc:
            details["qdrant"] = f"error: {str(exc)}"
            healthy = False

        status = "ok" if healthy else "unhealthy"
        return {"status": status, "details": details}

    return app


app = create_app()
