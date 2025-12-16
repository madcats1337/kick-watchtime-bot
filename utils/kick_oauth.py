"""
Utility functions for fetching Kick OAuth tokens from database
"""
from sqlalchemy import text


def get_kick_token_for_server(engine, discord_server_id):
    """
    Fetch OAuth access token for a Discord server from kick_oauth_tokens table
    
    Args:
        engine: SQLAlchemy engine
        discord_server_id: Discord server/guild ID (as int or None)
        
    Returns:
        dict with 'access_token', 'refresh_token', etc., or None if not found
    """
    if not discord_server_id:
        print(f"[Kick OAuth] No discord_server_id provided")
        return None
        
    try:
        with engine.connect() as conn:
            # First, get the configured kick_channel (streamer username) for this server
            result = conn.execute(
                text("""
                    SELECT value FROM bot_settings 
                    WHERE key = 'kick_channel' AND discord_server_id = :server_id
                """),
                {"server_id": discord_server_id}
            )
            row = result.fetchone()
            
            if not row or not row[0]:
                print(f"[Kick OAuth] No kick_channel found for server {discord_server_id}")
                return None
            
            kick_channel = row[0].lower()
            print(f"[Kick OAuth] Looking for token for kick_channel: {kick_channel}")
            
            # Now fetch the OAuth token for that Kick username
            result = conn.execute(
                text("""
                    SELECT access_token, refresh_token, expires_at, kick_username
                    FROM kick_oauth_tokens
                    WHERE LOWER(kick_username) = :kick_username
                    LIMIT 1
                """),
                {"kick_username": kick_channel}
            )
            row = result.fetchone()
            
            if row:
                print(f"[Kick OAuth] Found token for {row[3]}")
                return {
                    'access_token': row[0],
                    'refresh_token': row[1],
                    'expires_at': row[2],
                    'kick_username': row[3]
                }
            
            print(f"[Kick OAuth] No token found for username: {kick_channel}")
            return None
            
    except Exception as e:
        print(f"[Kick OAuth] Error fetching token: {e}")
        return None


def get_chatroom_id_for_server(engine, discord_server_id):
    """
    Fetch stored chatroom ID from bot_settings table
    
    Args:
        engine: SQLAlchemy engine
        discord_server_id: Discord server/guild ID (as int or None)
        
    Returns:
        str: Chatroom ID or None
    """
    if not discord_server_id:
        return None
        
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT kick_chatroom_id
                    FROM bot_settings
                    WHERE discord_server_id = :server_id
                    LIMIT 1
                """),
                {"server_id": discord_server_id}
            )
            row = result.fetchone()
            
            if row and row[0]:
                return str(row[0])
            return None
            
    except Exception as e:
        print(f"[Kick OAuth] Error fetching chatroom ID: {e}")
        return None
