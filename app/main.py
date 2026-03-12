"""
WebGenius — AI Kids Learning Platform
FastAPI application entry point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import engine, Base

# Import all models so Alembic/SQLAlchemy sees them
import app.models  # noqa: F401

# Routes
from app.api.routes import auth, dashboard, ai_proxy
from app.api.routes.api_keys import router as api_keys_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    if settings.DEBUG:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────────
    from app.services.rate_limiter import rate_limiter
    await rate_limiter.close()
    await engine.dispose()


app = FastAPI(
    title="WebGenius API",
    description="Backend for the WebGenius AI kids learning platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routes ───────────────────────────────────────────────────────────
app.include_router(auth.router,      prefix="/api/v1")
app.include_router(api_keys_router,  prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(ai_proxy.router,  prefix="/api/v1")

# Try to include classes route (may need schema fixes from older session)
try:
    from app.api.routes import classes
    app.include_router(classes.router, prefix="/api/v1")
except Exception:
    pass


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": "0.1.0", "env": settings.APP_ENV}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    if settings.DEBUG:
        raise exc
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
