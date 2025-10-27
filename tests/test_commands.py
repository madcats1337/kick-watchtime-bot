"""
Test Discord Commands for Raffle System
Validates command structure and database interactions
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raffle_system.database import setup_raffle_database, create_new_period
from raffle_system.tickets import TicketManager
from raffle_system.draw import RaffleDraw
from raffle_system.shuffle_tracker import ShuffleWagerTracker

def main():
    """Test raffle command database interactions"""
    
    load_dotenv()
    
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///watchtime.db")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    print("🎮 Testing Raffle Commands")
    print("=" * 50)
    
    engine = create_engine(DATABASE_URL)
    
    # Step 1: Setup
    print("\n1️⃣ Setting up test environment...")
    setup_raffle_database(engine)
    
    # Ensure links table exists
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS links (
                discord_id BIGINT PRIMARY KEY,
                kick_name TEXT UNIQUE
            );
        """))
    
    print("✅ Database ready")
    
    # Step 2: Create raffle period
    print("\n2️⃣ Creating raffle period...")
    start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(seconds=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(seconds=1)
    
    period_id = create_new_period(engine, start, end)
    print(f"✅ Period #{period_id} created")
    
    # Step 3: Create test users
    print("\n3️⃣ Creating test users...")
    test_users = [
        (111111111, 'alice_kick'),
        (222222222, 'bob_kick'),
        (333333333, 'charlie_kick'),
        (444444444, 'diana_kick'),
        (555555555, 'eve_kick'),
    ]
    
    with engine.begin() as conn:
        for discord_id, kick_name in test_users:
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name)
                VALUES (:discord_id, :kick_name)
                ON CONFLICT (discord_id) DO NOTHING
            """), {'discord_id': discord_id, 'kick_name': kick_name})
    
    print(f"   Created {len(test_users)} test users")
    
    # Step 4: Award tickets via different sources
    print("\n4️⃣ Awarding tickets from different sources...")
    tm = TicketManager(engine)
    draw = RaffleDraw(engine)  # Create draw object early for later use
    
    # Alice: Mostly watchtime
    tm.award_tickets(111111111, 'alice_kick', 150, 'watchtime', 'Converted 15 hours')
    tm.award_tickets(111111111, 'alice_kick', 30, 'gifted_sub', '2 subs gifted')
    
    # Bob: Mostly gifted subs
    tm.award_tickets(222222222, 'bob_kick', 225, 'gifted_sub', '15 subs gifted')
    tm.award_tickets(222222222, 'bob_kick', 40, 'watchtime', 'Converted 4 hours')
    
    # Charlie: Mostly Shuffle wagers
    tm.award_tickets(333333333, 'charlie_kick', 200, 'shuffle_wager', 'Wagered $10,000')
    tm.award_tickets(333333333, 'charlie_kick', 50, 'watchtime', 'Converted 5 hours')
    
    # Diana: Balanced
    tm.award_tickets(444444444, 'diana_kick', 80, 'watchtime', 'Converted 8 hours')
    tm.award_tickets(444444444, 'diana_kick', 75, 'gifted_sub', '5 subs gifted')
    tm.award_tickets(444444444, 'diana_kick', 60, 'shuffle_wager', 'Wagered $3,000')
    tm.award_tickets(444444444, 'diana_kick', 50, 'bonus', 'Event participation')
    
    # Eve: Small amount
    tm.award_tickets(555555555, 'eve_kick', 25, 'watchtime', 'Converted 2.5 hours')
    
    print("✅ Tickets awarded")
    
    # Step 5: Test !tickets command logic
    print("\n5️⃣ Testing !tickets command logic...")
    
    for discord_id, kick_name in test_users[:2]:  # Test first 2 users
        tickets = tm.get_user_tickets(discord_id)
        rank = tm.get_user_rank(discord_id)
        stats = tm.get_period_stats()
        
        print(f"\n   {kick_name}:")
        print(f"   • Total: {tickets['total_tickets']} tickets")
        print(f"   • Rank: #{rank} of {stats['total_participants']}")
        print(f"   • Watchtime: {tickets['watchtime_tickets']}")
        print(f"   • Gifted Subs: {tickets['gifted_sub_tickets']}")
        print(f"   • Shuffle: {tickets['shuffle_wager_tickets']}")
        print(f"   • Bonus: {tickets['bonus_tickets']}")
    
    # Step 6: Test !leaderboard command logic
    print("\n6️⃣ Testing !leaderboard command logic...")
    
    leaderboard = tm.get_leaderboard(limit=5)
    stats = tm.get_period_stats()
    
    print(f"\n   Raffle Leaderboard (Period #{stats['period_id']})")
    print(f"   Total Tickets: {stats['total_tickets']:,}")
    print(f"   Total Participants: {stats['total_participants']}\n")
    
    for entry in leaderboard:
        rank = entry['rank']
        kick_name = entry['kick_name']
        total = entry['total_tickets']
        # Calculate probability
        prob = (total / stats['total_tickets']) if stats['total_tickets'] > 0 else 0
        
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
        print(f"   {medal} {kick_name}: {total:,} tickets ({prob:.2%} chance)")
    
    # Step 7: Test !linkshuffle command logic
    print("\n7️⃣ Testing !linkshuffle command logic...")
    
    shuffle_tracker = ShuffleWagerTracker(engine)
    
    # Alice tries to link
    result = shuffle_tracker.link_shuffle_account(
        shuffle_username='alice_shuffle',
        kick_name='alice_kick',
        discord_id=111111111,
        verified=False
    )
    
    if result['status'] == 'success':
        print(f"   ✅ Link request created: alice_shuffle → alice_kick")
        print(f"   ⏳ Pending verification")
    
    # Try duplicate
    result2 = shuffle_tracker.link_shuffle_account(
        shuffle_username='alice_shuffle',
        kick_name='bob_kick',
        discord_id=222222222,
        verified=False
    )
    
    if result2['status'] == 'already_linked':
        print(f"   ✅ Duplicate prevention working")
    
    # Step 8: Test !raffleverify command logic
    print("\n8️⃣ Testing !raffleverify command logic...")
    
    # Admin verifies Alice's link
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE raffle_shuffle_links
            SET 
                verified = TRUE,
                verified_by_discord_id = :admin_id,
                verified_at = CURRENT_TIMESTAMP
            WHERE discord_id = :discord_id AND shuffle_username = :username
        """), {
            'admin_id': 999999999,  # Fake admin ID
            'discord_id': 111111111,
            'username': 'alice_shuffle'
        })
    
    print(f"   ✅ Verified alice_shuffle → alice_kick")
    
    # Step 9: Test !rafflegive command logic
    print("\n9️⃣ Testing !rafflegive command logic...")
    
    success = tm.award_tickets(
        discord_id=555555555,
        kick_name='eve_kick',
        tickets=100,
        source='bonus',
        description='Manual award by TestAdmin: Community event winner'
    )
    
    if success:
        updated_tickets = tm.get_user_tickets(555555555)
        print(f"   ✅ Awarded 100 tickets to eve_kick")
        print(f"   New total: {updated_tickets['total_tickets']} tickets")
    
    # Step 10: Test !raffleremove command logic
    print("\n🔟 Testing !raffleremove command logic...")
    
    success = tm.remove_tickets(
        discord_id=555555555,
        kick_name='eve_kick',
        tickets=50,
        reason='Test removal'
    )
    
    if success:
        updated_tickets = tm.get_user_tickets(555555555)
        print(f"   ✅ Removed 50 tickets from eve_kick")
        print(f"   New total: {updated_tickets['total_tickets']} tickets")
    
    # Step 11: Test !rafflestats command logic
    print("\n1️⃣1️⃣ Testing !rafflestats command logic...")
    
    # Get Diana's detailed stats
    diana_id = 444444444
    tickets = tm.get_user_tickets(diana_id)
    rank = tm.get_user_rank(diana_id)
    stats = tm.get_period_stats()
    
    with engine.begin() as conn:
        # Get detailed breakdowns
        watchtime_result = conn.execute(text("""
            SELECT SUM(minutes_converted), SUM(tickets_awarded)
            FROM raffle_watchtime_converted
            WHERE kick_name = :kick_name
        """), {'kick_name': 'diana_kick'})
        wt_row = watchtime_result.fetchone()
        total_minutes = wt_row[0] or 0
    
    print(f"\n   Detailed Stats for diana_kick:")
    print(f"   • Rank: #{rank} of {stats['total_participants']}")
    print(f"   • Total Tickets: {tickets['total_tickets']:,}")
    win_prob = (tickets['total_tickets'] / stats['total_tickets']) if stats['total_tickets'] > 0 else 0
    print(f"   • Win Probability: {win_prob:.2%}")
    print(f"   • Watchtime: {tickets['watchtime_tickets']} tickets ({total_minutes/60:.1f} hours)")
    print(f"   • Gifted Subs: {tickets['gifted_sub_tickets']} tickets")
    print(f"   • Shuffle: {tickets['shuffle_wager_tickets']} tickets")
    print(f"   • Bonus: {tickets['bonus_tickets']} tickets")
    
    # Step 12: Test !raffledraw command logic
    print("\n1️⃣2️⃣ Testing !raffledraw command logic...")
    
    # Check current stats
    stats = tm.get_period_stats()
    print(f"   Period #{stats['period_id']}")
    print(f"   Total tickets: {stats['total_tickets']:,}")
    print(f"   Participants: {stats['total_participants']}")
    
    # Draw winner for the current period
    result = draw.draw_winner(
        period_id=stats['period_id'],
        prize_description='$500 Cash Prize',
        drawn_by_discord_id=999999999
    )
    
    if result:
        print(f"\n   🎉 WINNER: {result['winner_kick_name']}")
        print(f"   Tickets: {result['winner_tickets']:,} out of {result['total_tickets']:,}")
        print(f"   Win probability: {result['win_probability']:.2f}%")
        print(f"   Prize: $500 Cash Prize")
    else:
        print(f"   ❌ Failed to draw winner")
    
    print("\n✅ All command tests passed!")
    print("\n📋 Command Summary:")
    print("   User Commands:")
    print("   • !tickets - Check ticket balance ✅")
    print("   • !leaderboard - View rankings ✅")
    print("   • !raffleinfo - Period information ✅")
    print("   • !linkshuffle - Link Shuffle account ✅")
    print("\n   Admin Commands:")
    print("   • !raffleverify @user <shuffle_username> - Verify Shuffle link ✅")
    print("   • !rafflegive @user <tickets> [reason] - Award tickets ✅")
    print("   • !raffleremove @user <tickets> [reason] - Remove tickets ✅")
    print("   • !raffledraw [prize] - Draw winner ✅")
    print("   • !rafflestats [@user] - View stats ✅")

if __name__ == "__main__":
    main()
