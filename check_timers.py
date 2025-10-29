"""Quick script to check timed messages in database"""
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not set")
    exit(1)

try:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text('SELECT id, message, interval_minutes, enabled FROM timed_messages')).fetchall()
        
        print(f"\n📊 Total timed messages: {len(result)}\n")
        
        if result:
            enabled_count = sum(1 for r in result if r[3])
            print(f"✅ Enabled: {enabled_count}")
            print(f"❌ Disabled: {len(result) - enabled_count}\n")
            
            for r in result:
                status = "✅ ENABLED" if r[3] else "❌ Disabled"
                print(f"  {status} | ID {r[0]} | Every {r[2]}min")
                print(f"    Message: {r[1][:70]}{'...' if len(r[1]) > 70 else ''}")
                print()
            
            if enabled_count > 0:
                print("⚠️  These enabled timers are trying to send every minute!")
                print("💡 To disable: Use !toggletimer <id> off in Discord")
        else:
            print("✅ No timed messages configured")
            
except Exception as e:
    print(f"❌ Error: {e}")
