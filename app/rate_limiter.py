# app/rate_limiter.py
import uuid
import logging
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)


# ── Rate limiting strategy: enforce limits per organisation (org_id) instead of per IP ──
def get_org_id(request: Request) -> str:
    if hasattr(request.state, "organisation_id"):
        return str(request.state.organisation_id)
    return get_remote_address(request)


# ── Initialize Redis-backed rate limiter (gracefully degrades if Redis is unavailable) ──
try:
    limiter = Limiter(
        key_func=get_org_id,
        storage_uri="redis://localhost:6379",
        strategy="fixed-window",
    )
    logger.info("Rate limiter using Redis storage.")
except Exception as e:
    logger.warning(f"Redis unavailable for rate limiting. Failing open. Error: {e}")
    limiter = Limiter(key_func=get_org_id)


# ── Custom exception handler to return structured response when rate limit is exceeded ──
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    retry_after = getattr(exc, "retry_after", 60)

    response = JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. You have exceeded 60 requests per minute.",
            "request_id": request_id,
        },
    )
    response.headers["Retry-After"] = str(retry_after)
    return response