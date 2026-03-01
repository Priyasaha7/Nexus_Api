# app/main.py
import uuid
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.database import engine, AsyncSessionLocal
from app.routers import auth, credits, api


from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routers import auth, credits, api, users


from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.rate_limiter import limiter, rate_limit_exceeded_handler


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    logger.info("NexusAPI starting up")
    yield
    # shutdown
    await engine.dispose()
    logger.info("NexusAPI shut down")

app = FastAPI(title="NexusAPI", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, tags=["users"])
app.include_router(credits.router, prefix="/credits", tags=["credits"])
app.include_router(api.router, prefix="/api", tags=["api"])


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            from jose import jwt as jose_jwt
            from app.config import settings
            payload = jose_jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM]
            )
            request.state.organisation_id = payload.get("org_id", "anonymous")
        else:
            request.state.organisation_id = "anonymous"
    except Exception:
        request.state.organisation_id = "anonymous"

    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)

    logger.info({
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "organisation_id": getattr(request.state, "organisation_id", "anonymous"),
        "status": response.status_code,
        "duration_ms": duration_ms,
    })
    return response

# ── home endpoint ──
@app.get("/")
async def root():
    return {"message": "NexusAPI is running", "docs": "/docs"}


# ── health endpoint ──
@app.get("/health")
async def health():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "unreachable", "error": str(e)}
        )

# ── global error handler ──
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.error(f"Unhandled error [{request_id}]: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred.",
            "request_id": request_id,
        }
    )