"""
Twitch Official API Integration Module
Uses the official Twitch Helix API and EventSub.

Mirrors the structure of core/kick_official_api.py so the bot's stream-platform
adapter (core/stream_provider.py) can treat Kick and Twitch uniformly.

Official endpoints:
- OAuth Server:  https://id.twitch.tv/oauth2
- Helix API:     https://api.twitch.tv/helix
- Documentation: https://dev.twitch.tv/docs/api/

Token kinds (see https://dev.twitch.tv/docs/authentication/):
- App access token  (client_credentials grant) — used to create EventSub
  subscriptions for stream.online/offline + channel.update. No user scopes.
  https://dev.twitch.tv/docs/authentication/getting-tokens-client-credentials/
- User access token (authorization_code grant) — the bot account that reads /
  sends chat (user:read:chat, user:bot, user:write:chat) and the broadcaster
  token that grants channel:bot + channel:read:subscriptions.
  https://dev.twitch.tv/docs/authentication/getting-tokens-oidc/

EventSub webhook subscription types we use
(https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/):
- stream.online (v1)            — app token, no scope
- stream.offline (v1)           — app token, no scope
- channel.update (v2)           — app token, no scope
- channel.chat.message (v1)     — user token: user:read:chat + user:bot + channel:bot
- channel.subscribe (v1)        — channel:read:subscriptions
- channel.subscription.gift (v1)— channel:read:subscriptions
- channel.subscription.message (v1) — channel:read:subscriptions

Signature verification (https://dev.twitch.tv/docs/eventsub/handling-webhook-events/):
HMAC-SHA256 over (message_id + message_timestamp + raw_body), keyed by the
per-subscription secret, compared against the "Twitch-Eventsub-Message-Signature"
header (prefixed "sha256="). NOTE: Twitch uses HMAC, unlike Kick's RSA scheme.
"""

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

# -------------------------
# Configuration
# -------------------------
TWITCH_OAUTH_SERVER = "https://id.twitch.tv/oauth2"
TWITCH_API_SERVER = "https://api.twitch.tv/helix"

# OAuth endpoints
TWITCH_AUTHORIZE_URL = f"{TWITCH_OAUTH_SERVER}/authorize"
TWITCH_TOKEN_URL = f"{TWITCH_OAUTH_SERVER}/token"
TWITCH_REVOKE_URL = f"{TWITCH_OAUTH_SERVER}/revoke"
TWITCH_VALIDATE_URL = f"{TWITCH_OAUTH_SERVER}/validate"

# Helix endpoints
TWITCH_USERS_URL = f"{TWITCH_API_SERVER}/users"
TWITCH_STREAMS_URL = f"{TWITCH_API_SERVER}/streams"
TWITCH_CHANNELS_URL = f"{TWITCH_API_SERVER}/channels"
TWITCH_CHAT_MESSAGES_URL = f"{TWITCH_API_SERVER}/chat/messages"
TWITCH_EVENTSUB_URL = f"{TWITCH_API_SERVER}/eventsub/subscriptions"

# EventSub headers (https://dev.twitch.tv/docs/eventsub/handling-webhook-events/)
HDR_MESSAGE_ID = "Twitch-Eventsub-Message-Id"
HDR_MESSAGE_TIMESTAMP = "Twitch-Eventsub-Message-Timestamp"
HDR_MESSAGE_SIGNATURE = "Twitch-Eventsub-Message-Signature"
HDR_MESSAGE_TYPE = "Twitch-Eventsub-Message-Type"
HDR_SUBSCRIPTION_TYPE = "Twitch-Eventsub-Subscription-Type"

# Message types delivered on the webhook callback
MSG_TYPE_VERIFICATION = "webhook_callback_verification"
MSG_TYPE_NOTIFICATION = "notification"
MSG_TYPE_REVOCATION = "revocation"

# Scopes a chat bot account needs (https://dev.twitch.tv/docs/chat/authenticating/)
BOT_CHAT_SCOPES = ["user:read:chat", "user:write:chat", "user:bot"]
# Scopes the broadcaster grants (channel:bot authorizes the bot for chat EventSub)
BROADCASTER_SCOPES = ["channel:bot", "channel:read:subscriptions", "moderator:read:followers"]

# EventSub subscription type -> version. Keep version explicit per Twitch docs.
EVENTSUB_VERSIONS = {
    "stream.online": "1",
    "stream.offline": "1",
    "channel.update": "2",
    "channel.chat.message": "1",
    "channel.subscribe": "1",
    "channel.subscription.gift": "1",
    "channel.subscription.message": "1",
}

# Stream events registrable with an app access token (no user scope required).
APP_TOKEN_STREAM_EVENTS = ["stream.online", "stream.offline", "channel.update"]


@dataclass
class TwitchTokens:
    """OAuth token response data (https://dev.twitch.tv/docs/authentication/)."""

    access_token: str
    expires_in: int
    token_type: str = "bearer"
    refresh_token: Optional[str] = None
    scope: Any = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    @property
    def is_expired(self) -> bool:
        """True if the access token is at/near expiry (60s safety margin)."""
        age = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return age >= max(self.expires_in - 60, 0)

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "scope": self.scope,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TwitchAPI:
    """
    Twitch Helix + EventSub client.

    Holds a single token. For stream EventSub registration construct it with an
    app token (see get_app_token / ensure_app_token). For chat send/read pass a
    user access token. All Helix calls send the required Client-Id header plus the
    Bearer token (https://dev.twitch.tv/docs/authentication/).
    """

    def __init__(
        self,
        client_id: str = None,
        client_secret: str = None,
        redirect_uri: str = None,
        access_token: str = None,
        refresh_token: str = None,
    ):
        self.client_id = client_id or os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("TWITCH_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("TWITCH_REDIRECT_URI")
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # -------------------------
    # OAuth — app access token (client_credentials)
    # -------------------------

    async def get_app_token(self) -> TwitchTokens:
        """
        Fetch an app access token via the client_credentials grant.
        Used for EventSub stream.online/offline + channel.update (no user scope).
        https://dev.twitch.tv/docs/authentication/getting-tokens-client-credentials/
        """
        session = await self._get_session()
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        async with session.post(TWITCH_TOKEN_URL, data=data) as response:
            response.raise_for_status()
            token_data = await response.json()
            tokens = TwitchTokens(
                access_token=token_data["access_token"],
                expires_in=token_data.get("expires_in", 0),
                token_type=token_data.get("token_type", "bearer"),
                scope=token_data.get("scope"),
            )
            self.access_token = tokens.access_token
            self.refresh_token = None  # app tokens have no refresh token
            return tokens

    # -------------------------
    # OAuth — user access token (authorization_code)
    # -------------------------

    def get_authorization_url(self, scopes: List[str] = None, state: str = None) -> str:
        """
        Build the OAuth authorization URL for user consent.
        https://dev.twitch.tv/docs/authentication/getting-tokens-oidc/
        """
        from urllib.parse import urlencode

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes or []),
        }
        if state:
            params["state"] = state
        return f"{TWITCH_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> TwitchTokens:
        """Exchange an authorization code for user access + refresh tokens."""
        session = await self._get_session()
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        async with session.post(TWITCH_TOKEN_URL, data=data) as response:
            response.raise_for_status()
            token_data = await response.json()
            tokens = TwitchTokens(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                expires_in=token_data.get("expires_in", 0),
                token_type=token_data.get("token_type", "bearer"),
                scope=token_data.get("scope"),
            )
            self.access_token = tokens.access_token
            self.refresh_token = tokens.refresh_token
            return tokens

    async def refresh_user_token(self) -> TwitchTokens:
        """
        Refresh a user access token using the refresh token.
        https://dev.twitch.tv/docs/authentication/refresh-tokens/
        """
        if not self.refresh_token:
            raise ValueError("No refresh token available")
        session = await self._get_session()
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        async with session.post(TWITCH_TOKEN_URL, data=data) as response:
            response.raise_for_status()
            token_data = await response.json()
            tokens = TwitchTokens(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token", self.refresh_token),
                expires_in=token_data.get("expires_in", 0),
                token_type=token_data.get("token_type", "bearer"),
                scope=token_data.get("scope"),
            )
            self.access_token = tokens.access_token
            if token_data.get("refresh_token"):
                self.refresh_token = tokens.refresh_token
            return tokens

    async def revoke_token(self, token: str = None):
        """Revoke an access token (https://dev.twitch.tv/docs/authentication/revoking-access-tokens/)."""
        session = await self._get_session()
        data = {"client_id": self.client_id, "token": token or self.access_token}
        async with session.post(TWITCH_REVOKE_URL, data=data) as response:
            response.raise_for_status()

    async def validate_token(self, token: str = None) -> Dict[str, Any]:
        """Validate a token, returning {user_id, login, scopes, expires_in, ...}.
        https://dev.twitch.tv/docs/authentication/validate-tokens/"""
        session = await self._get_session()
        headers = {"Authorization": f"OAuth {token or self.access_token}"}
        async with session.get(TWITCH_VALIDATE_URL, headers=headers) as response:
            response.raise_for_status()
            return await response.json()

    # -------------------------
    # Request helpers
    # -------------------------

    async def _request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make an authenticated Helix request. Retries once after refreshing a
        user token on 401. App tokens (no refresh token) just re-raise."""
        session = await self._get_session()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        headers["Client-Id"] = self.client_id
        headers.setdefault("Accept", "application/json")

        async with session.request(method, url, headers=headers, **kwargs) as response:
            if response.status == 401 and self.refresh_token:
                await self.refresh_user_token()
                headers["Authorization"] = f"Bearer {self.access_token}"
                async with session.request(method, url, headers=headers, **kwargs) as retry:
                    retry.raise_for_status()
                    return await self._json_or_empty(retry)
            response.raise_for_status()
            return await self._json_or_empty(response)

    @staticmethod
    async def _json_or_empty(response) -> Dict[str, Any]:
        # Some Helix endpoints (e.g. DELETE eventsub) return 204 with no body.
        if response.status == 204 or response.content_length == 0:
            return {}
        text_body = await response.text()
        if not text_body:
            return {}
        import json

        return json.loads(text_body)

    async def _get(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self._request("GET", url, **kwargs)

    async def _post(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self._request("POST", url, **kwargs)

    async def _delete(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self._request("DELETE", url, **kwargs)

    # -------------------------
    # Users / Channels / Streams
    # -------------------------

    async def get_user(self, login: str = None, user_id: str = None) -> Optional[Dict[str, Any]]:
        """
        Resolve a Twitch user by login (username) or id.
        https://dev.twitch.tv/docs/api/reference/#get-users

        Returns the first user object {id, login, display_name, ...} or None.
        """
        params = {}
        if login:
            params["login"] = login
        if user_id:
            params["id"] = user_id
        response = await self._get(TWITCH_USERS_URL, params=params)
        data = response.get("data", [])
        return data[0] if data else None

    async def get_streams(self, login: str = None, user_id: str = None) -> List[Dict[str, Any]]:
        """
        Get live stream(s). Empty list == offline.
        https://dev.twitch.tv/docs/api/reference/#get-streams
        """
        params = {}
        if login:
            params["user_login"] = login
        if user_id:
            params["user_id"] = user_id
        response = await self._get(TWITCH_STREAMS_URL, params=params)
        return response.get("data", [])

    async def is_live(self, login: str = None, user_id: str = None) -> bool:
        """True if the channel currently has a live stream."""
        streams = await self.get_streams(login=login, user_id=user_id)
        return len(streams) > 0

    async def get_channel(self, broadcaster_id: str) -> Optional[Dict[str, Any]]:
        """
        Channel info incl. title and game/category.
        https://dev.twitch.tv/docs/api/reference/#get-channel-information
        """
        response = await self._get(TWITCH_CHANNELS_URL, params={"broadcaster_id": broadcaster_id})
        data = response.get("data", [])
        return data[0] if data else None

    # -------------------------
    # Chat
    # -------------------------

    async def send_chat_message(
        self,
        broadcaster_id: str,
        sender_id: str,
        message: str,
        reply_parent_message_id: str = None,
    ) -> Dict[str, Any]:
        """
        Send a chat message as the bot account.
        Requires a user token with user:write:chat + user:bot.
        https://dev.twitch.tv/docs/chat/send-receive-messages/
        https://dev.twitch.tv/docs/api/reference/#send-chat-message

        Returns {message_id, is_sent, drop_reason?}.
        """
        payload = {
            "broadcaster_id": str(broadcaster_id),
            "sender_id": str(sender_id),
            "message": message,
        }
        if reply_parent_message_id:
            payload["reply_parent_message_id"] = reply_parent_message_id
        response = await self._post(TWITCH_CHAT_MESSAGES_URL, json=payload)
        data = response.get("data", [{}])
        return data[0] if data else {}

    # -------------------------
    # EventSub
    # -------------------------

    async def create_eventsub_subscription(
        self,
        sub_type: str,
        condition: Dict[str, Any],
        callback_url: str,
        secret: str,
        version: str = None,
    ) -> Dict[str, Any]:
        """
        Create a webhook EventSub subscription.
        https://dev.twitch.tv/docs/eventsub/manage-subscriptions/

        sub_type:   e.g. "stream.online", "channel.chat.message"
        condition:  e.g. {"broadcaster_user_id": "123"} or, for chat,
                    {"broadcaster_user_id": "123", "user_id": "<bot id>"}
        secret:     per-subscription HMAC secret (10-100 chars) used to verify
                    incoming notifications.

        NOTE: stream events use an APP access token; channel.chat.message and the
        subscription events use a USER token with the right scopes — set the
        token on this client accordingly before calling.
        """
        payload = {
            "type": sub_type,
            "version": version or EVENTSUB_VERSIONS.get(sub_type, "1"),
            "condition": condition,
            "transport": {
                "method": "webhook",
                "callback": callback_url,
                "secret": secret,
            },
        }
        response = await self._post(TWITCH_EVENTSUB_URL, json=payload)
        logger.info(f"[Twitch API] Created EventSub {sub_type}: {response.get('data', response)}")
        return response

    async def list_eventsub_subscriptions(self, status: str = None) -> List[Dict[str, Any]]:
        """List EventSub subscriptions for this client_id (paginates).
        https://dev.twitch.tv/docs/eventsub/manage-subscriptions/"""
        subs: List[Dict[str, Any]] = []
        params = {}
        if status:
            params["status"] = status
        cursor = None
        while True:
            if cursor:
                params["after"] = cursor
            response = await self._get(TWITCH_EVENTSUB_URL, params=params)
            subs.extend(response.get("data", []))
            cursor = (response.get("pagination") or {}).get("cursor")
            if not cursor:
                break
        return subs

    async def delete_eventsub_subscription(self, subscription_id: str) -> bool:
        """Delete an EventSub subscription. 404 (already gone) is non-fatal."""
        try:
            await self._delete(TWITCH_EVENTSUB_URL, params={"id": subscription_id})
            return True
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e):
                return False
            raise


# -------------------------
# Signature verification (module-level: the webhook handler has no client)
# -------------------------


def build_eventsub_hmac_message(message_id: str, timestamp: str, raw_body: bytes) -> bytes:
    """Concatenate the values Twitch signs: message_id + timestamp + raw_body."""
    body = raw_body if isinstance(raw_body, bytes) else str(raw_body).encode("utf-8")
    return message_id.encode("utf-8") + timestamp.encode("utf-8") + body


def verify_eventsub_signature(
    secret: str,
    message_id: str,
    timestamp: str,
    raw_body: bytes,
    signature_header: str,
) -> bool:
    """
    Verify the Twitch-Eventsub-Message-Signature header.
    https://dev.twitch.tv/docs/eventsub/handling-webhook-events/

    The header is "sha256=<hex>" where the hex is the HMAC-SHA256 of
    (message_id + timestamp + raw_body) keyed by the subscription secret.
    """
    if not secret or not signature_header:
        return False
    msg = build_eventsub_hmac_message(message_id, timestamp, raw_body)
    digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature_header)
