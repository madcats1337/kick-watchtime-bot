"""
Quick fix script to patch bot.py for multi-server database compatibility
Adds discord_server_id to INSERT statements for watchtime and links tables
"""

import re

def fix_bot_file():
    """Add discord_server_id to bot database queries"""
    
    with open('bot.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Fix 1: watchtime INSERT - Add discord_server_id column
    content = re.sub(
        r'INSERT INTO watchtime \(username, minutes, last_active\)\s+VALUES \(:u, :m, :t\)',
        'INSERT INTO watchtime (username, minutes, last_active, discord_server_id)\n                        VALUES (:u, :m, :t, :server_id)',
        content
    )
    
    # Fix 2: Add server_id parameter to watchtime INSERT execute
    content = re.sub(
        r'(conn\.execute\(text\("""\s+INSERT INTO watchtime[^}]+)\}\)',
        r'\1, "server_id": DISCORD_GUILD_ID })',
        content
    )
    
    # Fix 3: Add WHERE discord_server_id filter to watchtime SELECT queries
    content = re.sub(
        r'SELECT username, minutes FROM watchtime ORDER BY minutes DESC LIMIT :n',
        'SELECT username, minutes FROM watchtime WHERE discord_server_id = :server_id ORDER BY minutes DESC LIMIT :n',
        content
    )
    
    content = re.sub(
        r'SELECT minutes FROM watchtime WHERE username = :u',
        'SELECT minutes FROM watchtime WHERE username = :u AND discord_server_id = :server_id',
        content
    )
    
    content = re.sub(
        r'SELECT COUNT\(\*\) FROM watchtime',
        'SELECT COUNT(*) FROM watchtime WHERE discord_server_id = :server_id',
        content
    )
    
    # Fix 4: Add WHERE discord_server_id filter to links SELECT queries
    content = re.sub(
        r'SELECT kick_name FROM links WHERE discord_id = :d',
        'SELECT kick_name FROM links WHERE discord_id = :d AND discord_server_id = :server_id',
        content
    )
    
    content = re.sub(
        r'SELECT COUNT\(\*\) FROM links',
        'SELECT COUNT(*) FROM links WHERE discord_server_id = :server_id',
        content
    )
    
    # Check if we made any changes
    if content == original_content:
        print("⚠️ No changes made - patterns might not match!")
        return False
    
    # Backup original
    with open('bot.py.backup', 'w', encoding='utf-8') as f:
        f.write(original_content)
    
    # Write fixed content
    with open('bot.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ bot.py has been patched!")
    print("📋 Backup saved as bot.py.backup")
    print("\n⚠️ IMPORTANT: You still need to add :server_id parameter to execute() calls!")
    print("Example:")
    print('  conn.execute(text("..."), {"u": user, "server_id": DISCORD_GUILD_ID})')
    return True

if __name__ == "__main__":
    print("🔄 Patching bot.py for multi-server support...")
    print("This will add discord_server_id to database queries\n")
    
    try:
        if fix_bot_file():
            print("\n✅ Done! Review the changes and test thoroughly.")
        else:
            print("\n❌ Failed to apply patches - manual fixes needed")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
