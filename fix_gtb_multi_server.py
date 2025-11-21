"""
Fix GTB (Guess the Balance) to support multi-server isolation by adding discord_server_id parameter.

This script updates:
1. GuessTheBalanceManager __init__ to accept server_id
2. All GTB database operations to include discord_server_id
3. bot.py initialization to pass DISCORD_GUILD_ID
"""

import re

print("=" * 80)
print("Fixing GTB Multi-Server Support")
print("=" * 80)

# ============================================================================
# Fix 1: Update GuessTheBalanceManager class in features/games/guess_the_balance.py
# ============================================================================

gtb_file = 'features/games/guess_the_balance.py'

with open(gtb_file, 'r', encoding='utf-8') as f:
    gtb_content = f.read()

# Fix __init__ to accept server_id
gtb_content = gtb_content.replace(
    '    def __init__(self, engine: Engine):\n        self.engine = engine',
    '    def __init__(self, engine: Engine, server_id: int):\n        self.engine = engine\n        self.server_id = server_id'
)

# Fix get_active_session to filter by server_id
gtb_content = gtb_content.replace(
    '''                result = conn.execute(text("""
                    SELECT id, opened_by, opened_at, status
                    FROM gtb_sessions
                    WHERE status = 'open'
                    ORDER BY opened_at DESC
                    LIMIT 1
                """)).fetchone()''',
    '''                result = conn.execute(text("""
                    SELECT id, opened_by, opened_at, status
                    FROM gtb_sessions
                    WHERE status = 'open' AND discord_server_id = :server_id
                    ORDER BY opened_at DESC
                    LIMIT 1
                """), {"server_id": self.server_id}).fetchone()'''
)

# Fix open_session to include server_id
gtb_content = gtb_content.replace(
    '''                result = conn.execute(text("""
                    INSERT INTO gtb_sessions (opened_by, status)
                    VALUES (:opened_by, 'open')
                    RETURNING id
                """), {"opened_by": opened_by})''',
    '''                result = conn.execute(text("""
                    INSERT INTO gtb_sessions (opened_by, status, discord_server_id)
                    VALUES (:opened_by, 'open', :server_id)
                    RETURNING id
                """), {"opened_by": opened_by, "server_id": self.server_id})'''
)

# Fix close_session to include server_id in UPDATE
gtb_content = gtb_content.replace(
    '''                conn.execute(text("""
                    UPDATE gtb_sessions
                    SET status = 'closed', closed_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {"id": session_id})''',
    '''                conn.execute(text("""
                    UPDATE gtb_sessions
                    SET status = 'closed', closed_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND discord_server_id = :server_id
                """), {"id": session_id, "server_id": self.server_id})'''
)

# Fix add_guess to include server_id
gtb_content = gtb_content.replace(
    '''                conn.execute(text("""
                    INSERT INTO gtb_guesses (session_id, kick_username, guess_amount)
                    VALUES (:session_id, :username, :amount)
                    ON CONFLICT (session_id, kick_username)
                    DO UPDATE SET guess_amount = :amount, guessed_at = CURRENT_TIMESTAMP
                """), {
                    "session_id": session_id,
                    "username": kick_username,
                    "amount": guess_amount
                })''',
    '''                conn.execute(text("""
                    INSERT INTO gtb_guesses (session_id, kick_username, guess_amount, discord_server_id)
                    VALUES (:session_id, :username, :amount, :server_id)
                    ON CONFLICT (session_id, kick_username)
                    DO UPDATE SET guess_amount = :amount, guessed_at = CURRENT_TIMESTAMP
                """), {
                    "session_id": session_id,
                    "username": kick_username,
                    "amount": guess_amount,
                    "server_id": self.server_id
                })'''
)

# Fix set_result to filter by server_id
gtb_content = gtb_content.replace(
    '''                session = conn.execute(text("""
                    SELECT id FROM gtb_sessions
                    WHERE status = 'closed'
                    ORDER BY closed_at DESC
                    LIMIT 1
                """)).fetchone()''',
    '''                session = conn.execute(text("""
                    SELECT id FROM gtb_sessions
                    WHERE status = 'closed' AND discord_server_id = :server_id
                    ORDER BY closed_at DESC
                    LIMIT 1
                """), {"server_id": self.server_id}).fetchone()'''
)

# Fix set_result UPDATE query
gtb_content = gtb_content.replace(
    '''                conn.execute(text("""
                    UPDATE gtb_sessions
                    SET result_amount = :amount, status = 'completed'
                    WHERE id = :id
                """), {"amount": result_amount, "id": session_id})''',
    '''                conn.execute(text("""
                    UPDATE gtb_sessions
                    SET result_amount = :amount, status = 'completed'
                    WHERE id = :id AND discord_server_id = :server_id
                """), {"amount": result_amount, "id": session_id, "server_id": self.server_id})'''
)

# Fix set_result winners DELETE
gtb_content = gtb_content.replace(
    '''                conn.execute(text("""
                    DELETE FROM gtb_winners WHERE session_id = :id
                """), {"id": session_id})''',
    '''                conn.execute(text("""
                    DELETE FROM gtb_winners WHERE session_id = :id AND discord_server_id = :server_id
                """), {"id": session_id, "server_id": self.server_id})'''
)

# Fix set_result guesses SELECT
gtb_content = gtb_content.replace(
    '''                guesses = conn.execute(text("""
                    SELECT kick_username, guess_amount,
                           ABS(guess_amount - :amount) as difference,
                           guessed_at
                    FROM gtb_guesses
                    WHERE session_id = :id
                    ORDER BY difference ASC, guessed_at ASC
                    LIMIT 3
                """), {"amount": result_amount, "id": session_id}).fetchall()''',
    '''                guesses = conn.execute(text("""
                    SELECT kick_username, guess_amount,
                           ABS(guess_amount - :amount) as difference,
                           guessed_at
                    FROM gtb_guesses
                    WHERE session_id = :id AND discord_server_id = :server_id
                    ORDER BY difference ASC, guessed_at ASC
                    LIMIT 3
                """), {"amount": result_amount, "id": session_id, "server_id": self.server_id}).fetchall()'''
)

# Fix set_result winners INSERT
gtb_content = gtb_content.replace(
    '''                    conn.execute(text("""
                        INSERT INTO gtb_winners
                        (session_id, kick_username, rank, guess_amount, result_amount, difference)
                        VALUES (:id, :username, :rank, :guess, :result, :diff)
                    """), {''',
    '''                    conn.execute(text("""
                        INSERT INTO gtb_winners
                        (session_id, kick_username, rank, guess_amount, result_amount, difference, discord_server_id)
                        VALUES (:id, :username, :rank, :guess, :result, :diff, :server_id)
                    """), {'''
)

# Add server_id to winners INSERT parameters
gtb_content = gtb_content.replace(
    '''                        "rank": rank,
                        "guess": guess["guess_amount"],
                        "result": result_amount,
                        "diff": guess["difference"]
                    })''',
    '''                        "rank": rank,
                        "guess": guess["guess_amount"],
                        "result": result_amount,
                        "diff": guess["difference"],
                        "server_id": self.server_id
                    })'''
)

with open(gtb_file, 'w', encoding='utf-8') as f:
    f.write(gtb_content)

print(f"✅ Updated {gtb_file}")

# ============================================================================
# Fix 2: Update bot.py to pass DISCORD_GUILD_ID to GTB manager
# ============================================================================

bot_file = 'bot.py'

with open(bot_file, 'r', encoding='utf-8') as f:
    bot_content = f.read()

# Fix GTB manager initialization
bot_content = bot_content.replace(
    '            gtb_manager = GuessTheBalanceManager(engine)',
    '            gtb_manager = GuessTheBalanceManager(engine, DISCORD_GUILD_ID)'
)

with open(bot_file, 'w', encoding='utf-8') as f:
    f.write(bot_content)

print(f"✅ Updated {bot_file}")

print("\n" + "=" * 80)
print("✅ GTB Multi-Server Support Fixed!")
print("=" * 80)
print("\nChanges made:")
print("1. GuessTheBalanceManager now accepts server_id parameter")
print("2. All GTB queries now filter by discord_server_id")
print("3. All GTB inserts now include discord_server_id")
print("4. bot.py passes DISCORD_GUILD_ID to GTB manager")
print("\nCommit and deploy to fix GTB guess saving!")
