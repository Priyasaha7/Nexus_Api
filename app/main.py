# app/main.py
import uuid
import time
import logging
import json
from contextlib import asynccontextmanager

from fastapi import HTTPException

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text

from app.database import engine, AsyncSessionLocal
from app.routers import auth, credits, api, users
from app.config import settings
from app.rate_limiter import limiter, rate_limit_exceeded_handler

from starlette.middleware.sessions import SessionMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware


# ─────────────────────────────────────────────
# JSON Structured Logging Configuration
# ─────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "timestamp": self.formatTime(record, self.datefmt),
        }

        if isinstance(record.msg, dict):
            log_record.update(record.msg)

        return json.dumps(log_record)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())

logging.basicConfig(
    level=logging.INFO,
    handlers=[handler],
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Application Lifespan
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info({"event": "startup", "service": "NexusAPI"})
    yield
    await engine.dispose()
    logger.info({"event": "shutdown", "service": "NexusAPI"})


app = FastAPI(title="NexusAPI", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, tags=["users"])
app.include_router(credits.router, prefix="/credits", tags=["credits"])
app.include_router(api.router, prefix="/api", tags=["api"])


# ─────────────────────────────────────────────
# Request Logging Middleware
# ─────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    # Default values
    request.state.organisation_id = "anonymous"
    request.state.user_id = "anonymous"

    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            from jose import jwt as jose_jwt

            payload = jose_jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
            )

            request.state.organisation_id = payload.get("org_id", "anonymous")
            request.state.user_id = payload.get("sub", "anonymous")

    except Exception:
        # Fail closed but safely
        request.state.organisation_id = "anonymous"
        request.state.user_id = "anonymous"

    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)

    logger.info({
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "organisation_id": request.state.organisation_id,
        "user_id": request.state.user_id,
        "status": response.status_code,
        "duration_ms": duration_ms,
    })

    return response


# ─────────────────────────────────────────────
# Validation Error Handler
# ─────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    errors = exc.errors()
    first_error = errors[0] if errors else {}

    field = " -> ".join(str(x) for x in first_error.get("loc", []))
    message = first_error.get("msg", "Validation error")

    logger.warning({
        "event": "validation_error",
        "request_id": request_id,
        "field": field,
        "message": message,
        "user_id": getattr(request.state, "user_id", "anonymous"),
        "organisation_id": getattr(request.state, "organisation_id", "anonymous"),
    })

    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": f"{field}: {message}",
            "request_id": request_id,
        },
    )


# ── Custom HTTP Exception Handler ──
# Removes FastAPI's default "detail" wrapper
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # if detail is already our structured shape, return it directly
    if isinstance(exc.detail, dict):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
        )

    # fallback for plain string errors
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "http_error",
            "message": str(exc.detail),
            "request_id": request_id,
        }
    )
    
# ─────────────────────────────────────────────
# Root Endpoint
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "NexusAPI is running", "docs": "/docs"}


# ─────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))

        return {"status": "healthy", "database": "connected"}

    except Exception as e:
        logger.error({
            "event": "health_check_failed",
            "error": str(e),
        })

        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "unreachable",
                "error": str(e),
            },
        )


# ─────────────────────────────────────────────
# Global Exception Handler
# ─────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    logger.error({
        "event": "unhandled_exception",
        "request_id": request_id,
        "error": str(exc),
        "user_id": getattr(request.state, "user_id", "anonymous"),
        "organisation_id": getattr(request.state, "organisation_id", "anonymous"),
    }, exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred.",
            "request_id": request_id,
        },
    )