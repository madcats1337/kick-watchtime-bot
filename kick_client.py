import asyncio
import json
import requests
import websockets

KICK_API_URL = "https://kick.com/api/v2/channels/"

class KickChatClient:
    def __init__(self, username: str):
        self.username = username
        self.chatroom_id = None
        self.ws_url = None
        self.connected = False

    async def connect(self):
        """Connects to Kick chat for a given channel."""
        try:
            # Fetch chatroom ID from Kick API
            res = requests.get(f"{KICK_API_URL}{self.username}")
            res.raise_for_status()
            data = res.json()
            self.chatroom_id = data["chatroom"]["id"]
            self.ws_url = f"wss://ws.chat.kick.com/chatroom/{self.chatroom_id}"

            print(f"[Kick] Connecting to {self.username} chat ({self.chatroom_id})...")
            async with websockets.connect(self.ws_url) as ws:
                self.connected = True
                print(f"[Kick] Connected to {self.username}'s chat!")

                async for message in ws:
                    await self.handle_message(message)

        except Exception as e:
            print(f"[Kick] Connection error: {e}")
            await asyncio.sleep(10)
            await self.connect()  # retry loop

    async def handle_message(self, message):
        """Handles incoming chat messages."""
        try:
            data = json.loads(message)
            if "content" in data:
                username = data.get("sender", {}).get("username", "Unknown")
                text = data["content"]
                print(f"[Kick] {username}: {text}")
        except Exception as e:
            # Some messages are system events — skip those
            pass


if __name__ == "__main__":
    # Test connection standalone
    client = KickChatClient("madcats")
    asyncio.run(client.connect())
