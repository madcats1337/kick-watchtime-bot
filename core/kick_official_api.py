"""
Kick.com Official API Integration Module
Uses the official Kick API endpoints from https://docs.kick.com

Official API Endpoints:
- OAuth Server: https://id.kick.com
- API Server: https://api.kick.com
- Documentation: https://docs.kick.com
- OpenAPI Spec: https://api.kick.com/swagger/v1/doc.yaml

Available Scopes:
- user:read - Read user profile information
- channel:read - Read channel information
- channel:write - Modify channel settings
- chat:write - Send chat messages
- streamkey:read - Read stream key
- events:subscribe - Subscribe to webhooks
- moderation:ban - Ban users from chat
- kicks:read - Read Tips (Kicks) data

Webhook Events:
- chat.message.sent - Chat messages
- channel.followed - New followers
- channel.subscription.new - New subscriptions
- channel.subscription.renewal - Subscription renewals
- channel.subscription.gifts - Gifted subscriptions
- livestream.status.updated - Stream live/offline events
- moderation.banned - User banned from chat
- kicks.gifted - Tips (Kicks) received
"""

import asyncio
import os
import secrets
import hashlib
import base64
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass
import aiohttp

# -------------------------
# Configuration
# -------------------------
KICK_OAUTH_SERVER = "https://id.kick.com"
KICK_API_SERVER = "https://api.kick.com"
KICK_API_PUBLIC_V1 = f"{KICK_API_SERVER}/public/v1"
KICK_API_V2 = f"{KICK_API_SERVER}/v2"

# OAuth endpoints
KICK_AUTHORIZE_URL = f"{KICK_OAUTH_SERVER}/oauth/authorize"
KICK_TOKEN_URL = f"{KICK_OAUTH_SERVER}/oauth/token"
KICK_REVOKE_URL = f"{KICK_OAUTH_SERVER}/oauth/revoke"
KICK_USER_INFO_URL = f"{KICK_OAUTH_SERVER}/oauth/userinfo"

# API endpoints
KICK_USERS_URL = f"{KICK_API_PUBLIC_V1}/users"
KICK_CHANNELS_URL = f"{KICK_API_PUBLIC_V1}/channels"
KICK_CHAT_URL = f"{KICK_API_SERVER}/api/v1/chat-messages"  # v1 messages endpoint
KICK_CATEGORIES_URL = f"{KICK_API_PUBLIC_V1}/categories"
KICK_WEBHOOKS_URL = f"{KICK_API_PUBLIC_V1}/events/subscriptions"
KICK_MODERATION_URL = f"{KICK_API_PUBLIC_V1}/channels/{{broadcaster_user_id}}/moderation"
KICK_KICKS_LEADERBOARD = f"{KICK_API_PUBLIC_V1}/channels/{{broadcaster_user_id}}/kicks/leaderboard"

# Available OAuth scopes
OAUTH_SCOPES = [
    "user:read",
    "channel:read",
    "channel:write",
    "chat:write",
    "streamkey:read",
    "events:subscribe",
    "moderation:ban",
    "kicks:read",
]

# Webhook event types
WEBHOOK_EVENTS = [
    "chat.message.sent",
    "channel.followed",
    "channel.subscription.new",
    "channel.subscription.renewal",
    "channel.subscription.gifts",
    "livestream.status.updated",
    "moderation.banned",
    "kicks.gifted",
]

@dataclass
class OAuthTokens:
    """OAuth token response data"""
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    scope: str
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    @property
    def is_expired(self) -> bool:
        """Check if the access token is expired"""
        age = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return age >= self.expires_in

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "scope": self.scope,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class WebhookSubscription:
    """Webhook subscription data - fully permissive constructor"""
    def __init__(
        self,
        *,
        id=None,
        app_id=None,
        event=None,
        version=None,
        broadcaster_user_id=None,
        method=None,
        status=None,
        callback_url=None,
        created_at=None,
        updated_at=None,
        **kwargs  # Accept any other fields Kick might add
    ):
        self.id = id
        self.app_id = app_id
        self.event = event
        self.version = version
        self.broadcaster_user_id = broadcaster_user_id
        self.method = method
        self.status = status
        self.callback_url = callback_url
        self.created_at = created_at
        self.updated_at = updated_at
        # Store any extra fields
        for key, value in kwargs.items():
            setattr(self, key, value)

class KickOfficialAPI:
    """
    Official Kick API client using OAuth 2.1 with PKCE.

    This client provides access to all official Kick API endpoints including:
    - User information
    - Channel data and management
    - Chat messaging (with chat:write scope)
    - Webhook subscriptions
    - Moderation actions
    - Kicks (tips) leaderboard
    """

    def __init__(
        self,
        client_id: str = None,
        client_secret: str = None,
        redirect_uri: str = None,
        access_token: str = None,
        refresh_token: str = None,
    ):
        self.client_id = client_id or os.getenv("KICK_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("KICK_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("KICK_REDIRECT_URI")
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()

    # -------------------------
    # OAuth 2.1 PKCE Flow
    # -------------------------

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """
        Generate PKCE code_verifier and code_challenge for OAuth 2.1.

        Returns:
            Tuple of (code_verifier, code_challenge)
        """
        # Generate random 32 bytes for code verifier
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')

        # Create SHA256 hash of verifier for challenge
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')

        return code_verifier, code_challenge

    def get_authorization_url(
        self,
        scopes: List[str] = None,
        state: str = None,
        code_challenge: str = None,
    ) -> tuple[str, str]:
        """
        Generate the OAuth authorization URL for user consent.

        Args:
            scopes: List of OAuth scopes to request
            state: Random state for CSRF protection
            code_challenge: PKCE code challenge

        Returns:
            Tuple of (authorization_url, state)
        """
        if state is None:
            state = secrets.token_urlsafe(32)

        if scopes is None:
            scopes = ["user:read", "channel:read", "chat:write"]

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
        }

        # Add PKCE challenge if provided
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{KICK_AUTHORIZE_URL}?{query}", state

    async def exchange_code(
        self,
        code: str,
        code_verifier: str = None,
    ) -> OAuthTokens:
        """
        Exchange authorization code for access tokens.

        Args:
            code: Authorization code from callback
            code_verifier: PKCE code verifier (required if PKCE was used)

        Returns:
            OAuthTokens object with access and refresh tokens
        """
        session = await self._get_session()

        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }

        if code_verifier:
            data["code_verifier"] = code_verifier

        async with session.post(KICK_TOKEN_URL, data=data) as response:
            response.raise_for_status()
            token_data = await response.json()

            tokens = OAuthTokens(
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                token_type=token_data["token_type"],
                expires_in=token_data["expires_in"],
                scope=token_data.get("scope", ""),
            )

            self.access_token = tokens.access_token
            self.refresh_token = tokens.refresh_token

            return tokens

    async def refresh_tokens(self) -> OAuthTokens:
        """
        Refresh the access token using the refresh token.

        Note: As of 25/11/2025, refresh tokens are now reusable and won't be rotated
        on each use. This makes them safe to use multiple times.

        Returns:
            New OAuthTokens object
        """
        if not self.refresh_token:
            raise ValueError("No refresh token available")

        session = await self._get_session()

        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }

        async with session.post(KICK_TOKEN_URL, data=data) as response:
            response.raise_for_status()
            token_data = await response.json()

            tokens = OAuthTokens(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token", self.refresh_token),
                token_type=token_data["token_type"],
                expires_in=token_data["expires_in"],
                scope=token_data.get("scope", ""),
            )

            self.access_token = tokens.access_token
            if token_data.get("refresh_token"):
                self.refresh_token = tokens.refresh_token

            return tokens

    async def revoke_token(self, token: str = None):
        """
        Revoke an access or refresh token.

        Args:
            token: Token to revoke (defaults to current access token)
        """
        session = await self._get_session()

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "token": token or self.access_token,
        }

        async with session.post(KICK_REVOKE_URL, data=data) as response:
            response.raise_for_status()

    # -------------------------
    # API Request Helpers
    # -------------------------

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Make an authenticated API request"""
        session = await self._get_session()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        headers["Accept"] = "application/json"

        async with session.request(method, url, headers=headers, **kwargs) as response:
            if response.status == 401:
                # Try to refresh token and retry (only if we have a refresh token)
                if self.refresh_token:
                    await self.refresh_tokens()
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    async with session.request(method, url, headers=headers, **kwargs) as retry_response:
                        retry_response.raise_for_status()
                        return await retry_response.json()
                else:
                    # No refresh token (e.g., Client Credentials flow) - just raise the error
                    response.raise_for_status()

            response.raise_for_status()
            return await response.json()

    async def _get(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self._request("GET", url, **kwargs)

    async def _post(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self._request("POST", url, **kwargs)

    async def _delete(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self._request("DELETE", url, **kwargs)

    # -------------------------
    # User API
    # -------------------------

    async def get_user(self) -> Dict[str, Any]:
        """
        Get the authenticated user's information.
        Requires: user:read scope

        Returns:
            User data including user_id, name, email (if available)
        """
        return await self._get(KICK_USER_INFO_URL)

    async def get_users(self, user_ids: List[int] = None) -> Dict[str, Any]:
        """
        Get user information by IDs.
        Requires: user:read scope

        Args:
            user_ids: List of user IDs to fetch (max 100)

        Returns:
            List of user data
        """
        params = {}
        if user_ids:
            params["id"] = user_ids
        return await self._get(KICK_USERS_URL, params=params)

    # -------------------------
    # Channel API
    # -------------------------

    async def get_channels(self, broadcaster_user_ids: List[int] = None) -> Dict[str, Any]:
        """
        Get channel information.
        Requires: channel:read scope

        Args:
            broadcaster_user_ids: List of broadcaster user IDs

        Returns:
            Channel data including stream status, viewer count, etc.
        """
        params = {}
        if broadcaster_user_ids:
            params["broadcaster_user_id"] = broadcaster_user_ids
        return await self._get(KICK_CHANNELS_URL, params=params)

    async def update_channel(
        self,
        broadcaster_user_id: int,
        title: str = None,
        category_id: int = None,
        language: str = None,
    ) -> Dict[str, Any]:
        """
        Update channel information.
        Requires: channel:write scope

        Args:
            broadcaster_user_id: The broadcaster's user ID
            title: New stream title
            category_id: New category ID
            language: Stream language (ISO 639-1 code)

        Returns:
            Updated channel data
        """
        data = {}
        if title:
            data["title"] = title
        if category_id:
            data["category_id"] = category_id
        if language:
            data["language"] = language

        return await self._request(
            "PATCH",
            KICK_CHANNELS_URL,
            params={"broadcaster_user_id": broadcaster_user_id},
            json=data
        )

    # -------------------------
    # Chat API
    # -------------------------

    async def send_chat_message(
        self,
        content: str,
        broadcaster_user_id: int = None,
        chatroom_id: int = None,
        reply_to_message_id: str = None,
    ) -> Dict[str, Any]:
        """
        Send a chat message to a channel.
        Requires: chat:write scope or valid application token

        Uses v2 endpoint: POST /v2/messages/send/{chatroomId}

        Args:
            content: Message content (max 500 chars)
            broadcaster_user_id: Target channel's broadcaster ID (for looking up chatroom_id if not provided)
            chatroom_id: Target chatroom ID (required, will be looked up if not provided)
            reply_to_message_id: Message ID to reply to (optional)

        Returns:
            Message data including message_id
        """
        # Get chatroom_id if not provided
        if not chatroom_id:
            if broadcaster_user_id:
                # Try to look up chatroom_id from bot_settings
                from bot import engine
                from sqlalchemy import text
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT value FROM bot_settings 
                        WHERE key = 'kick_chatroom_id'
                        LIMIT 1
                    """)).fetchone()
                    
                    if result and result[0]:
                        chatroom_id = int(result[0])
            
            if not chatroom_id:
                raise ValueError("chatroom_id is required for sending chat messages")
        
        # v1 endpoint doesn't use chatroom_id in path, uses it in payload
        url = KICK_CHAT_URL
        
        payload = {
            "content": content,
            "chatroom_id": chatroom_id,
        }

        if reply_to_message_id:
            payload["reply_to_original_message"] = {
                "original_message_id": reply_to_message_id
            }
        
        print(f"[Kick API] 📤 Sending chat message:")
        print(f"[Kick API]   URL: {url}")
        print(f"[Kick API]   Payload: {payload}")
        print(f"[Kick API]   Content length: {len(content)}")
        print(f"[Kick API]   Chatroom ID: {chatroom_id}")
        
        headers = {"Content-Type": "application/json"}
        try:
            result = await self._post(url, json=payload, headers=headers)
            print(f"[Kick API] ✅ Chat message sent successfully")
            return result
        except Exception as e:
            print(f"[Kick API] ❌ Error sending chat message: {e}")
            print(f"[Kick API]   Error type: {type(e).__name__}")
            if hasattr(e, 'status'):
                print(f"[Kick API]   Status: {e.status}")
            if hasattr(e, 'message'):
                print(f"[Kick API]   Message: {e.message}")
            raise

    # -------------------------
    # Categories API
    # -------------------------

    async def get_categories(
        self,
        query: str = None,
        category_ids: List[int] = None,
    ) -> Dict[str, Any]:
        """
        Get stream categories.
        Requires: channel:read scope

        Args:
            query: Search query for categories
            category_ids: Specific category IDs to fetch

        Returns:
            List of categories
        """
        params = {}
        if query:
            params["q"] = query
        if category_ids:
            params["id"] = category_ids
        return await self._get(KICK_CATEGORIES_URL, params=params)

    # -------------------------
    # Webhooks API
    # -------------------------

    async def subscribe_webhook(
        self,
        event: str,
        callback_url: str,
        broadcaster_user_id: int = None,
    ) -> WebhookSubscription:
        """
        Subscribe to a webhook event.
        Requires: events:subscribe scope

        Available events:
        - chat.message.sent
        - channel.followed
        - channel.subscription.new
        - channel.subscription.renewal
        - channel.subscription.gifts
        - livestream.status.updated
        - moderation.banned
        - kicks.gifted

        Args:
            event: Event type to subscribe to
            callback_url: HTTPS URL to receive webhook callbacks
            broadcaster_user_id: Filter events to specific broadcaster (optional)

        Returns:
            WebhookSubscription object
        """
        payload = {
            "events": [
                {
                    "name": event,
                    "version": 1,
                }
            ],
            "method": "webhook",
            "callback_url": callback_url,
        }

        if broadcaster_user_id:
            payload["events"][0]["broadcaster_user_id"] = broadcaster_user_id

        response = await self._post(KICK_WEBHOOKS_URL, json=payload)
        sub_data = response.get("data", [{}])[0]

        return WebhookSubscription(
            id=sub_data.get("id"),
            event=sub_data.get("event"),
            method=sub_data.get("method"),
            version=sub_data.get("version"),
            callback_url=sub_data.get("callback_url"),
            created_at=sub_data.get("created_at"),
            updated_at=sub_data.get("updated_at"),
            broadcaster_user_id=sub_data.get("broadcaster_user_id"),
        )

    async def get_webhook_subscriptions(self) -> List[WebhookSubscription]:
        """
        Get all active webhook subscriptions.
        Requires: events:subscribe scope

        Returns:
            List of WebhookSubscription objects
        """
        response = await self._get(KICK_WEBHOOKS_URL)
        subscriptions = []

        data = response.get("data", [])
        if not data:
            return subscriptions

        for sub in data:
            try:
                # Pass all fields Kick returns - WebhookSubscription accepts them all
                subscriptions.append(WebhookSubscription(**sub))
            except Exception as e:
                print(f"[API] Error creating WebhookSubscription: {e}")
                print(f"[API] Raw subscription data: {sub}")
                # Return raw dict if dataclass fails
                subscriptions.append(sub)

        return subscriptions

    async def delete_webhook_subscription(self, subscription_id: str) -> bool:
        """
        Delete a webhook subscription.
        Requires: events:subscribe scope

        Args:
            subscription_id: The subscription ID to delete

        Returns:
            True if successful, False if not found (404)
        """
        try:
            await self._delete(f"{KICK_WEBHOOKS_URL}/{subscription_id}")
            return True
        except Exception as e:
            # Treat 404 as non-fatal (already deleted)
            if "404" in str(e) or "Not Found" in str(e):
                return False
            raise

    async def subscribe_webhook(
        self,
        event: str,
        callback_url: str,
        broadcaster_user_id: str,
        secret: str = None,
    ) -> WebhookSubscription:
        """
        Subscribe to a webhook event.
        Requires: events:subscribe scope

        Args:
            event: Event type (e.g., 'livestream.status.updated')
            callback_url: Your webhook endpoint URL
            broadcaster_user_id: Broadcaster's user ID
            secret: Webhook signing secret (you generate this)

        Returns:
            WebhookSubscription object
        """
        data = {
            "event": event,
            "method": "webhook",
            "callback_url": callback_url,
            "broadcaster_user_id": int(broadcaster_user_id),
        }
        
        # Add secret if provided (for HMAC signature verification)
        if secret:
            data["secret"] = secret
        
        response = await self._post(KICK_WEBHOOKS_URL, json=data)
        
        # Kick may return 200/201/204 with empty body, list, or dict
        # ALL are SUCCESS - we don't fail on empty responses
        # HTTP status code determines success, not response body
        
        print(f"[API] Webhook creation response type: {type(response)}")
        print(f"[API] Webhook creation response: {response}")
        
        # Return response as-is (may be empty, list, or dict)
        # Caller doesn't need WebhookSubscription object for creation
        return response if response else {"event": event, "status": "created"}

    # -------------------------
    # Moderation API
    # -------------------------

    async def ban_user(
        self,
        broadcaster_user_id: int,
        user_id: int,
        duration_minutes: int = None,
        reason: str = None,
    ) -> Dict[str, Any]:
        """
        Ban a user from chat.
        Requires: moderation:ban scope

        Args:
            broadcaster_user_id: The broadcaster's user ID
            user_id: User ID to ban
            duration_minutes: Ban duration (None = permanent)
            reason: Ban reason

        Returns:
            Ban confirmation data
        """
        url = KICK_MODERATION_URL.format(broadcaster_user_id=broadcaster_user_id) + "/bans"

        payload = {
            "banned_user_id": user_id,
        }

        if duration_minutes:
            payload["duration"] = duration_minutes

        if reason:
            payload["reason"] = reason

        return await self._post(url, json=payload)

    async def unban_user(
        self,
        broadcaster_user_id: int,
        user_id: int,
    ) -> bool:
        """
        Unban a user from chat.
        Requires: moderation:ban scope

        Args:
            broadcaster_user_id: The broadcaster's user ID
            user_id: User ID to unban

        Returns:
            True if successful
        """
        url = KICK_MODERATION_URL.format(broadcaster_user_id=broadcaster_user_id) + "/bans"
        await self._delete(url, params={"banned_user_id": user_id})
        return True

    # -------------------------
    # Kicks (Tips) API
    # -------------------------

    async def get_kicks_leaderboard(
        self,
        broadcaster_user_id: int,
        range_type: str = "all_time",
    ) -> Dict[str, Any]:
        """
        Get the Kicks (tips) leaderboard for a channel.
        Requires: kicks:read scope

        Args:
            broadcaster_user_id: The broadcaster's user ID
            range_type: Time range - "all_time", "month", "week"

        Returns:
            Leaderboard data with top tippers
        """
        url = KICK_KICKS_LEADERBOARD.format(broadcaster_user_id=broadcaster_user_id)
        return await self._get(url, params={"range": range_type})

    # -------------------------
    # Livestream API
    # -------------------------

    async def get_livestreams(
        self,
        broadcaster_user_ids: List[int] = None,
        category_ids: List[int] = None,
        language: str = None,
        sort: str = "viewers_count",
        limit: int = 25,
    ) -> Dict[str, Any]:
        """
        Get currently live streams.
        Requires: channel:read scope

        Args:
            broadcaster_user_ids: Filter by broadcaster IDs
            category_ids: Filter by category IDs
            language: Filter by language code
            sort: Sort by "viewers_count" or "created_at"
            limit: Max results (25-100)

        Returns:
            List of live streams
        """
        params = {
            "sort": sort,
            "limit": min(max(limit, 25), 100),
        }

        if broadcaster_user_ids:
            params["broadcaster_user_id"] = broadcaster_user_ids
        if category_ids:
            params["category_id"] = category_ids
        if language:
            params["language"] = language

        return await self._get(f"{KICK_API_PUBLIC}/livestreams", params=params)

# -------------------------
# Webhook Payload Classes
# -------------------------

@dataclass
class WebhookChatMessage:
    """Parsed chat.message.sent webhook payload"""
    message_id: str
    broadcaster_user_id: int
    sender_user_id: int
    sender_username: str
    content: str
    sent_at: str
    badges: List[Dict]

    @classmethod
    def from_payload(cls, data: dict) -> "WebhookChatMessage":
        return cls(
            message_id=data.get("message_id"),
            broadcaster_user_id=data.get("broadcaster", {}).get("user_id"),
            sender_user_id=data.get("sender", {}).get("user_id"),
            sender_username=data.get("sender", {}).get("username"),
            content=data.get("content"),
            sent_at=data.get("sent_at"),
            badges=data.get("sender", {}).get("badges", []),
        )

@dataclass
class WebhookSubscription:
    """Parsed channel.subscription.* webhook payload"""
    broadcaster_user_id: int
    broadcaster_username: str
    subscriber_user_id: int
    subscriber_username: str
    created_at: str
    duration: int  # months

    @classmethod
    def from_payload(cls, data: dict) -> "WebhookSubscription":
        return cls(
            broadcaster_user_id=data.get("broadcaster", {}).get("user_id"),
            broadcaster_username=data.get("broadcaster", {}).get("username"),
            subscriber_user_id=data.get("subscriber", {}).get("user_id"),
            subscriber_username=data.get("subscriber", {}).get("username"),
            created_at=data.get("created_at"),
            duration=data.get("duration", 1),
        )

@dataclass
class WebhookGiftedSubs:
    """Parsed channel.subscription.gifts webhook payload"""
    broadcaster_user_id: int
    broadcaster_username: str
    gifter_user_id: int
    gifter_username: str
    created_at: str
    giftees: List[Dict]  # List of {user_id, username}

    @classmethod
    def from_payload(cls, data: dict) -> "WebhookGiftedSubs":
        return cls(
            broadcaster_user_id=data.get("broadcaster", {}).get("user_id"),
            broadcaster_username=data.get("broadcaster", {}).get("username"),
            gifter_user_id=data.get("gifter", {}).get("user_id"),
            gifter_username=data.get("gifter", {}).get("username"),
            created_at=data.get("created_at"),
            giftees=data.get("giftees", []),
        )

@dataclass
class WebhookKicksGifted:
    """Parsed kicks.gifted webhook payload (Tips)"""
    broadcaster_user_id: int
    broadcaster_username: str
    sender_user_id: int
    sender_username: str
    created_at: str
    amount: float
    kick_count: int

    @classmethod
    def from_payload(cls, data: dict) -> "WebhookKicksGifted":
        return cls(
            broadcaster_user_id=data.get("broadcaster", {}).get("user_id"),
            broadcaster_username=data.get("broadcaster", {}).get("username"),
            sender_user_id=data.get("sender", {}).get("user_id"),
            sender_username=data.get("sender", {}).get("username"),
            created_at=data.get("created_at"),
            amount=data.get("amount", 0),
            kick_count=data.get("kick_count", 0),
        )

@dataclass
class WebhookLivestreamStatus:
    """Parsed livestream.status.updated webhook payload"""
    broadcaster_user_id: int
    broadcaster_username: str
    is_live: bool
    stream_id: str
    title: str
    started_at: str

    @classmethod
    def from_payload(cls, data: dict) -> "WebhookLivestreamStatus":
        return cls(
            broadcaster_user_id=data.get("broadcaster", {}).get("user_id"),
            broadcaster_username=data.get("broadcaster", {}).get("username"),
            is_live=data.get("is_live", False),
            stream_id=data.get("livestream", {}).get("id"),
            title=data.get("livestream", {}).get("session_title"),
            started_at=data.get("livestream", {}).get("created_at"),
        )

# -------------------------
# Utility Functions
# -------------------------

def verify_webhook_signature(
    signature: str,
    message_id: str,
    timestamp: str,
    body: bytes,
    secret: str,
) -> bool:
    """
    Verify webhook signature from Kick.

    Signature is HMAC SHA256 of: {message_id}.{timestamp}.{raw_body}

    Args:
        signature: The Kick-Event-Signature header value
        message_id: The Kick-Event-Message-Id header value
        timestamp: The Kick-Event-Message-Timestamp header value
        body: Raw request body bytes
        secret: Your webhook secret

    Returns:
        True if signature is valid
    """
    message = f"{message_id}.{timestamp}.{body.decode()}"
    expected = hashlib.sha256(
        (secret + message).encode()
    ).hexdigest()

    return signature == expected

# Export all public interfaces
__all__ = [
    'KickOfficialAPI',
    'OAuthTokens',
    'WebhookSubscription',
    'WebhookChatMessage',
    'WebhookGiftedSubs',
    'WebhookKicksGifted',
    'WebhookLivestreamStatus',
    'verify_webhook_signature',
    'OAUTH_SCOPES',
    'WEBHOOK_EVENTS',
]
