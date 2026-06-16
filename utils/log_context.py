"""
Per-server logging context.

Holds the "currently active" Discord server (id + name) in a ``contextvars``
ContextVar so that logging output can be attributed to the right server/dashboard
without threading the server through every call site.

``contextvars`` is the correct primitive for BOTH runtime models in this system:

- The Flask dashboard is thread-per-request; ContextVars are isolated per thread.
- The bot is a single asyncio loop serving many guilds concurrently; each asyncio
  Task gets its own copy of the context, so concurrent guild handlers never clobber
  each other's server.

The companion ``ServerContextFilter`` in ``logging_config`` reads ``get_server()``
and stamps every log record with the active server.
"""

import contextvars
from contextlib import contextmanager
from typing import Optional, Tuple

# (server_id, server_name); either may be None when no server is in context.
_current_server: contextvars.ContextVar[Tuple[Optional[str], Optional[str]]] = contextvars.ContextVar(
    "current_server", default=(None, None)
)


def _norm(value) -> Optional[str]:
    """Normalize an id/name to a clean string or None (treats ""/None alike)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def set_server(server_id=None, server_name=None) -> contextvars.Token:
    """Set the active server for the current context. Returns a reset Token."""
    return _current_server.set((_norm(server_id), _norm(server_name)))


def clear_server(token: Optional[contextvars.Token] = None) -> None:
    """Clear the active server. Pass the Token from ``set_server`` to restore the
    previous value precisely; otherwise reset to ``(None, None)``."""
    if token is not None:
        try:
            _current_server.reset(token)
            return
        except (ValueError, LookupError):
            # Token came from a different context (e.g. thread reuse); fall through.
            pass
    _current_server.set((None, None))


def get_server() -> Tuple[Optional[str], Optional[str]]:
    """Return the active ``(server_id, server_name)`` for the current context."""
    return _current_server.get()


@contextmanager
def server_context(server_id=None, server_name=None):
    """Scope a block to a server. Sets the context on enter and restores the prior
    value on exit. Use this in the bot for per-event / per-task scopes::

        with server_context(guild_id, guild_name):
            handle_event(...)
    """
    token = set_server(server_id, server_name)
    try:
        yield
    finally:
        clear_server(token)
