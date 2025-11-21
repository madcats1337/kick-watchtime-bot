"""Fix the fishmeeting gifted sub - update from 5 to 15 tickets"""
from sqlalchemy import create_engine, text
from raffle_system.tickets import TicketManager

database_url = "postgresql://postgres:qlCUFZaNzxnkRdqKYKmkrwFloDArkYqS@shinkansen.proxy.rlwy.net:57221/railway"
engine = create_engine(database_url)
ticket_manager = TicketManager(engine)

GIFTER_KICK_NAME = "fishmeeting"
CORRECT_TICKETS = 15
INCORRECT_TICKETS = 5
DIFFERENCE = CORRECT_TICKETS - INCORRECT_TICKETS  # 10 more tickets

print("=" * 80)
print("FIXING FISHMEETING GIFTED SUB TICKETS")
print("=" * 80)
print(f"\nCurrent tickets: {INCORRECT_TICKETS}")
print(f"Correct tickets: {CORRECT_TICKETS}")
print(f"Need to add: {DIFFERENCE} tickets")

with engine.begin() as conn:
    # Get active period
    result = conn.execute(text("""
        SELECT id FROM raffle_periods
        WHERE status = 'active'
        ORDER BY start_date DESC
        LIMIT 1;
    """))
    period_id = result.fetchone()[0]
    
    # Get gifter discord ID
    result = conn.execute(text("""
        SELECT discord_id FROM links
        WHERE LOWER(kick_name) = LOWER(:kick_name)
    """), {'kick_name': GIFTER_KICK_NAME})
    discord_id = result.fetchone()[0]
    
    print(f"\nPeriod ID: {period_id}")
    print(f"Discord ID: {discord_id}")
    
    # Award the additional 10 tickets
    print(f"\n📝 Adding {DIFFERENCE} more tickets...")
    success = ticket_manager.award_tickets(
        discord_id=discord_id,
        kick_name=GIFTER_KICK_NAME,
        tickets=DIFFERENCE,
        source='gifted_sub',
        description="Correction: gifted sub should be 15 tickets, not 5",
        period_id=period_id
    )
    
    if success:
        print(f"✅ Added {DIFFERENCE} tickets to {GIFTER_KICK_NAME}")
    else:
        print(f"❌ Failed to add tickets!")
        exit(1)
    
    # Update the raffle_gifted_subs record
    print(f"\n📝 Updating raffle_gifted_subs record...")
    conn.execute(text("""
        UPDATE raffle_gifted_subs
        SET tickets_awarded = :correct_tickets
        WHERE gifter_kick_name = :kick_name
        AND period_id = :period_id
        AND kick_event_id LIKE 'manual_%'
    """), {
        'correct_tickets': CORRECT_TICKETS,
        'kick_name': GIFTER_KICK_NAME,
        'period_id': period_id
    })
    
    print(f"✅ Updated gifted sub record to show {CORRECT_TICKETS} tickets")

print("\n" + "=" * 80)
print("✅ SUCCESS - Tickets corrected to 15")
print("=" * 80)
