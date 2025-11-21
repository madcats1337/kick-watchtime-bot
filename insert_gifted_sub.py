"""Manually insert a gifted sub event into the database"""
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
from raffle_system.tickets import TicketManager

# Database connection
database_url = "postgresql://postgres:qlCUFZaNzxnkRdqKYKmkrwFloDArkYqS@shinkansen.proxy.rlwy.net:57221/railway"
engine = create_engine(database_url)
ticket_manager = TicketManager(engine)

# Event details
GIFTER_KICK_NAME = "fishmeeting"
RECIPIENT_KICK_NAME = "raizto"
SUB_COUNT = 1
TICKETS_PER_SUB = 5  # From config.py GIFTED_SUB_TICKETS
EVENT_TIME = datetime.now() - timedelta(hours=1)  # Approximate time (1 hour ago)
DISCORD_SERVER_ID = 914986636629143562  # From bot.py DISCORD_GUILD_ID

print("=" * 80)
print("MANUAL GIFTED SUB INSERTION")
print("=" * 80)
print(f"\nGifter: {GIFTER_KICK_NAME}")
print(f"Recipient: {RECIPIENT_KICK_NAME}")
print(f"Sub Count: {SUB_COUNT}")
print(f"Event Time: {EVENT_TIME}")

with engine.begin() as conn:
    # Get active raffle period
    result = conn.execute(text("""
        SELECT id FROM raffle_periods
        WHERE status = 'active'
        ORDER BY start_date DESC
        LIMIT 1;
    """))
    row = result.fetchone()
    if not row:
        print("\n❌ ERROR: No active raffle period found!")
        exit(1)
    
    period_id = row[0]
    print(f"\nActive Period ID: {period_id}")
    
    # Check if gifter is linked
    result = conn.execute(text("""
        SELECT discord_id FROM links
        WHERE LOWER(kick_name) = LOWER(:kick_name)
    """), {'kick_name': GIFTER_KICK_NAME})
    
    row = result.fetchone()
    gifter_discord_id = row[0] if row else None
    
    if gifter_discord_id:
        print(f"Gifter Discord ID: {gifter_discord_id}")
        tickets_awarded = SUB_COUNT * TICKETS_PER_SUB
        print(f"Tickets to award: {tickets_awarded}")
        
        # Award tickets using TicketManager
        print("\n📝 Awarding tickets...")
        success = ticket_manager.award_tickets(
            discord_id=gifter_discord_id,
            kick_name=GIFTER_KICK_NAME,
            tickets=tickets_awarded,
            source='gifted_sub',
            description=f"Gifted {SUB_COUNT} sub(s) in chat (manual entry)",
            period_id=period_id
        )
        
        if success:
            print(f"✅ Awarded {tickets_awarded} tickets to {GIFTER_KICK_NAME}")
        else:
            print(f"❌ Failed to award tickets!")
            exit(1)
    else:
        print(f"⚠️  Gifter {GIFTER_KICK_NAME} is not linked to Discord")
        tickets_awarded = 0
    
    # Log the gifted sub event
    event_id = f"manual_{GIFTER_KICK_NAME}_{int(EVENT_TIME.timestamp())}"
    print(f"\n📝 Logging gifted sub event (ID: {event_id})...")
    
    conn.execute(text("""
        INSERT INTO raffle_gifted_subs
            (period_id, gifter_kick_name, gifter_discord_id, recipient_kick_name,
             sub_count, tickets_awarded, gifted_at, kick_event_id, discord_server_id)
        VALUES
            (:period_id, :gifter_kick_name, :gifter_discord_id, :recipient_kick_name,
             :sub_count, :tickets_awarded, :gifted_at, :event_id, :discord_server_id)
    """), {
        'period_id': period_id,
        'gifter_kick_name': GIFTER_KICK_NAME,
        'gifter_discord_id': gifter_discord_id,
        'recipient_kick_name': RECIPIENT_KICK_NAME,
        'sub_count': SUB_COUNT,
        'tickets_awarded': tickets_awarded,
        'gifted_at': EVENT_TIME,
        'event_id': event_id,
        'discord_server_id': DISCORD_SERVER_ID
    })
    
    print(f"✅ Logged gifted sub event in database")

print("\n" + "=" * 80)
print("✅ SUCCESS - Gifted sub manually inserted")
print("=" * 80)
