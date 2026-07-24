"""Redirect OAuth completions to the public React result page."""

import json
import logging
import os
import secrets
from urllib.parse import urlencode

import redis
from flask import redirect

from utils.server_urls import PUBLIC_BASE_DOMAIN

logger = logging.getLogger(__name__)

_RESULT_TTL_SECONDS = 5 * 60
_VALID_PLATFORMS = {"kick", "twitch"}
_VALID_FLOWS = {"user", "bot"}


def _result_page_url(**query: str) -> str:
    scheme = "http" if PUBLIC_BASE_DOMAIN.startswith("localhost") else "https"
    base_url = f"{scheme}://{PUBLIC_BASE_DOMAIN}/oauth/result"
    return f"{base_url}?{urlencode(query)}" if query else base_url


def _store_result(payload: dict[str, str]) -> str:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL is not configured")
    if "://" not in redis_url:
        redis_url = f"redis://{redis_url}"

    result_token = secrets.token_urlsafe(32)
    client = redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        client.setex(
            f"oauth_result:{result_token}",
            _RESULT_TTL_SECONDS,
            json.dumps(payload, separators=(",", ":")),
        )
    finally:
        client.close()
    return result_token


def _redirect_with_result(payload: dict[str, str]):
    try:
        result_token = _store_result(payload)
        return redirect(_result_page_url(result=result_token), code=303)
    except Exception as exc:
        logger.warning("[OAuth Result] Could not store callback result: %s", exc)
        return redirect(_result_page_url(status="error", code="result_unavailable"), code=303)


def redirect_service_page():
    """Send the callback-service root to its React landing state."""
    return redirect(_result_page_url(), code=302)


def redirect_oauth_success(username: str, platform: str = "kick", flow: str = "user"):
    """Store and redirect to a successful account-connection result."""
    safe_platform = platform if platform in _VALID_PLATFORMS else "kick"
    safe_flow = flow if flow in _VALID_FLOWS else "user"
    return _redirect_with_result(
        {
            "status": "success",
            "platform": safe_platform,
            "flow": safe_flow,
            "username": str(username).strip()[:100],
        }
    )


def redirect_oauth_error(message: str, platform: str = "kick", flow: str = "user"):
    """Store and redirect to a user-safe account-connection error."""
    safe_platform = platform if platform in _VALID_PLATFORMS else "kick"
    safe_flow = flow if flow in _VALID_FLOWS else "user"
    return _redirect_with_result(
        {
            "status": "error",
            "platform": safe_platform,
            "flow": safe_flow,
            "message": str(message).strip()[:240],
        }
    )
