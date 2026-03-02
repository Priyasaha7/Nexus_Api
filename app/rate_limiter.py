# app/rate_limiter.py
import uuid
import logging
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def get_org_id(request: Request) -> str:
    if hasattr(request.state, "organisation_id"):
        return str(request.state.organisation_id)
    return get_remote_address(request)


def get_org_rate_key(request: Request) -> str:
    """Single shared bucket across ALL product endpoints per org"""
    if hasattr(request.state, "organisation_id"):
        return f"product:{request.state.organisation_id}"
    return f"product:{get_remote_address(request)}"


def _get_redis_uri() -> str:
    """Read Redis URL from settings — never hardcode"""
    from app.config import settings
    return settings.REDIS_URL


# general limiter
try:
    limiter = Limiter(
        key_func=get_org_id,
        storage_uri=_get_redis_uri(),
        strategy="fixed-window",
    )
except Exception as e:
    logger.warning(f"Redis unavailable for limiter. Failing open. Error: {e}")
    limiter = Limiter(key_func=get_org_id)


# product endpoints shared limiter — 60/min COMBINED across /analyse + /summarise
try:
    product_limiter = Limiter(
        key_func=get_org_rate_key,
        storage_uri=_get_redis_uri(),
        strategy="fixed-window",
    )
except Exception as e:
    logger.warning(f"Redis unavailable for product_limiter. Failing open. Error: {e}")
    product_limiter = Limiter(key_func=get_org_rate_key)


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