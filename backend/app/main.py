from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import auth, dashboard, leads, outreach, reports, social, webhooks, workflows
from backend.app.config import get_settings
from backend.app.core.rate_limit import RateLimitExceeded, SlowAPIMiddleware, limiter, rate_limit_exceeded_handler
from backend.app.database import check_database_connection, init_db


settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    try:
        check_database_connection()
    except Exception:
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

    app.include_router(auth, prefix=settings.API_PREFIX)
    app.include_router(dashboard, prefix=settings.API_PREFIX)
    app.include_router(leads, prefix=settings.API_PREFIX)
    app.include_router(outreach, prefix=settings.API_PREFIX)
    app.include_router(reports, prefix=settings.API_PREFIX)
    app.include_router(social, prefix=settings.API_PREFIX)
    app.include_router(workflows, prefix=settings.API_PREFIX)
    app.include_router(webhooks, prefix=settings.API_PREFIX)

    @app.get("/health")
    def health_check() -> dict:
        return {"status": "ok", "app": settings.APP_NAME, "environment": settings.APP_ENV}

    return app


app = create_app()
