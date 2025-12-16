"""
Utility functions for fetching Kick OAuth tokens from database
"""
from sqlalchemy import text


def get_kick_token_for_server(engine, discord_server_id):
    """
    Fetch OAuth access token for a Discord server from kick_oauth_tokens table
    
    Args:
        engine: SQLAlchemy engine
        discord_server_id: Discord server/guild ID (as string)
        
    Returns:
        dict with 'access_token' and 'refresh_token', or None if not found
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT access_token, refresh_token, expires_at, kick_username, kick_user_id
                    FROM kick_oauth_tokens
                    WHERE discord_server_id = :server_id
                    LIMIT 1
                """),
                {"server_id": str(discord_server_id)}
            )
            row = result.fetchone()
            
            if row:
                return {
                    'access_token': row[0],
                    'refresh_token': row[1],
                    'expires_at': row[2],
                    'kick_username': row[3],
                    'kick_user_id': row[4]
                }
            return None
            
    except Exception as e:
        print(f"[Kick OAuth] Error fetching token: {e}")
        return None


def get_chatroom_id_for_server(engine, discord_server_id):
    """
    Fetch stored chatroom ID from bot_settings table
    
    Args:
        engine: SQLAlchemy engine
        discord_server_id: Discord server/guild ID (as string)
        
    Returns:
        str: Chatroom ID or None
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT kick_chatroom_id
                    FROM bot_settings
                    WHERE discord_server_id = :server_id
                    LIMIT 1
                """),
                {"server_id": str(discord_server_id)}
            )
            row = result.fetchone()
            
            if row and row[0]:
                return str(row[0])
            return None
            
    except Exception as e:
        print(f"[Kick OAuth] Error fetching chatroom ID: {e}")
        return None
