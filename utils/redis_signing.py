"""HMAC authentication for Redis pub/sub messages (shared secret: REDIS_MSG_SECRET).

The Redis channels between the dashboard and the bot carry state-changing commands
(points, raffles, settings, simulated chat) and trust ``discord_server_id`` straight
from the message body. Anyone able to PUBLISH to the Redis instance could otherwise
forge those commands for any guild. Publishers call :func:`sign_payload` before
publishing; the subscriber calls :func:`verify_payload` on receipt and drops
anything that fails.

Rollout is designed to be safe: when ``REDIS_MSG_SECRET`` is unset both functions
are no-ops (signing adds nothing, verification accepts everything). Deploy this code
to both services first, then set the SAME secret on both and restart them together.
"""

import hashlib
import hmac
import json
import os

_SIG_FIELD = "sig"


def _secret():
    return os.getenv("REDIS_MSG_SECRET")


def _canonical(payload):
    """Deterministic byte serialization of the payload excluding the signature."""
    body = {k: v for k, v in payload.items() if k != _SIG_FIELD}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign_payload(payload):
    """Return ``payload`` with an HMAC-SHA256 ``sig`` field added.

    Returns the payload unchanged when no secret is configured.
    """
    secret = _secret()
    if not secret:
        return payload
    sig = hmac.new(secret.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()
    signed = dict(payload)
    signed[_SIG_FIELD] = sig
    return signed


def verify_payload(payload):
    """Return True if the payload's signature is valid.

    Returns True when no secret is configured (unauthenticated/compat mode).
    Returns False when a secret is set but the ``sig`` field is missing or wrong.
    """
    secret = _secret()
    if not secret:
        return True
    provided = payload.get(_SIG_FIELD)
    if not provided:
        return False
    expected = hmac.new(secret.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(str(provided), expected)


def signing_enabled():
    """True when a shared secret is configured (used for startup logging)."""
    return bool(_secret())
