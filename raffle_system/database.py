"""
Database Schema Setup for Raffle System
Creates all tables, indices, and views needed for the monthly raffle
"""

from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

# SQL schema for raffle system
RAFFLE_SCHEMA_SQL = """
-- ============================================
-- RAFFLE SYSTEM DATABASE SCHEMA
-- ============================================

-- Monthly raffle periods
CREATE TABLE IF NOT EXISTS raffle_periods (
    id SERIAL PRIMARY KEY,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'active',  -- active, ended, archived
    winner_discord_id BIGINT,
    winner_kick_name TEXT,
    winning_ticket_number INTEGER,
    total_tickets INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User ticket balances (resets monthly)
CREATE TABLE IF NOT EXISTS raffle_tickets (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id) ON DELETE CASCADE,
    discord_id BIGINT NOT NULL,
    kick_name TEXT NOT NULL,

    -- Ticket sources
    watchtime_tickets INTEGER DEFAULT 0,
    gifted_sub_tickets INTEGER DEFAULT 0,
    shuffle_wager_tickets INTEGER DEFAULT 0,
    bonus_tickets INTEGER DEFAULT 0,  -- Manual admin awards

    -- Totals
    total_tickets INTEGER DEFAULT 0,

    -- Metadata
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(period_id, discord_id)
);

-- Watchtime conversion tracking (prevent double-counting)
CREATE TABLE IF NOT EXISTS raffle_watchtime_converted (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id) ON DELETE CASCADE,
    kick_name TEXT NOT NULL,
    minutes_converted INTEGER NOT NULL,
    tickets_awarded INTEGER NOT NULL,
    converted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(period_id, kick_name)
);

-- Gifted sub event log
CREATE TABLE IF NOT EXISTS raffle_gifted_subs (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id) ON DELETE CASCADE,
    gifter_kick_name TEXT NOT NULL,
    gifter_discord_id BIGINT,  -- NULL if not linked
    recipient_kick_name TEXT,
    sub_count INTEGER DEFAULT 1,  -- For multi-gifts
    tickets_awarded INTEGER NOT NULL,
    gifted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    kick_event_id TEXT UNIQUE  -- Prevent duplicate processing
);

-- Shuffle.com wager tracking
CREATE TABLE IF NOT EXISTS raffle_shuffle_wagers (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id) ON DELETE CASCADE,
    shuffle_username TEXT NOT NULL,
    kick_name TEXT,  -- If we can map shuffle→kick
    discord_id BIGINT,  -- NULL if not linked

    -- Wager tracking
    total_wager_usd DECIMAL(15, 2) DEFAULT 0,
    last_known_wager DECIMAL(15, 2) DEFAULT 0,
    tickets_awarded INTEGER DEFAULT 0,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(period_id, shuffle_username)
);

-- Shuffle username → Kick/Discord mapping
CREATE TABLE IF NOT EXISTS raffle_shuffle_links (
    id SERIAL PRIMARY KEY,
    shuffle_username TEXT NOT NULL UNIQUE,
    kick_name TEXT NOT NULL,
    discord_id BIGINT NOT NULL UNIQUE,  -- One Shuffle account per Discord user
    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    verified BOOLEAN DEFAULT FALSE,  -- Admin verification
    verified_by_discord_id BIGINT,
    verified_at TIMESTAMP
);

-- Ticket transaction log (audit trail)
CREATE TABLE IF NOT EXISTS raffle_ticket_log (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id) ON DELETE CASCADE,
    discord_id BIGINT NOT NULL,
    kick_name TEXT NOT NULL,
    ticket_change INTEGER NOT NULL,  -- +10, +15, -50, etc.
    source VARCHAR(50) NOT NULL,  -- 'watchtime', 'gifted_sub', 'shuffle_wager', 'bonus', 'reset'
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Raffle draw history
CREATE TABLE IF NOT EXISTS raffle_draws (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id) UNIQUE,
    total_tickets INTEGER NOT NULL,
    total_participants INTEGER NOT NULL,
    winner_discord_id BIGINT NOT NULL,
    winner_kick_name TEXT NOT NULL,
    winner_shuffle_name TEXT,
    winning_ticket INTEGER NOT NULL,
    prize_description TEXT,
    drawn_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    drawn_by_discord_id BIGINT  -- Admin who triggered draw
);

-- ============================================
-- INDICES FOR PERFORMANCE
-- ============================================

CREATE INDEX IF NOT EXISTS idx_raffle_tickets_period ON raffle_tickets(period_id);
CREATE INDEX IF NOT EXISTS idx_raffle_tickets_discord ON raffle_tickets(discord_id);
CREATE INDEX IF NOT EXISTS idx_raffle_tickets_total ON raffle_tickets(total_tickets DESC);
CREATE INDEX IF NOT EXISTS idx_raffle_ticket_log_period ON raffle_ticket_log(period_id);
CREATE INDEX IF NOT EXISTS idx_raffle_ticket_log_discord ON raffle_ticket_log(discord_id);
CREATE INDEX IF NOT EXISTS idx_raffle_gifted_subs_period ON raffle_gifted_subs(period_id);
CREATE INDEX IF NOT EXISTS idx_raffle_gifted_subs_discord ON raffle_gifted_subs(gifter_discord_id);
CREATE INDEX IF NOT EXISTS idx_raffle_shuffle_period ON raffle_shuffle_wagers(period_id);
CREATE INDEX IF NOT EXISTS idx_raffle_shuffle_discord ON raffle_shuffle_wagers(discord_id);
CREATE INDEX IF NOT EXISTS idx_raffle_periods_status ON raffle_periods(status);

-- ============================================
-- VIEWS FOR EASY QUERYING
-- ============================================

-- Drop views if they exist (for re-creation)
DROP VIEW IF EXISTS raffle_leaderboard;
DROP VIEW IF EXISTS raffle_current_stats;

-- Leaderboard view
CREATE VIEW raffle_leaderboard AS
SELECT
    rt.period_id,
    rt.discord_id,
    rt.kick_name,
    rt.total_tickets,
    rt.watchtime_tickets,
    rt.gifted_sub_tickets,
    rt.shuffle_wager_tickets,
    rt.bonus_tickets,
    RANK() OVER (PARTITION BY rt.period_id ORDER BY rt.total_tickets DESC) as rank
FROM raffle_tickets rt
WHERE rt.total_tickets > 0
ORDER BY rt.period_id DESC, rt.total_tickets DESC;

-- Current period stats
CREATE VIEW raffle_current_stats AS
SELECT
    rp.id as period_id,
    rp.start_date,
    rp.end_date,
    rp.status,
    COUNT(DISTINCT rt.discord_id) as total_participants,
    COALESCE(SUM(rt.total_tickets), 0) as total_tickets,
    COALESCE(SUM(rt.watchtime_tickets), 0) as watchtime_tickets,
    COALESCE(SUM(rt.gifted_sub_tickets), 0) as gifted_sub_tickets,
    COALESCE(SUM(rt.shuffle_wager_tickets), 0) as shuffle_wager_tickets,
    COALESCE(SUM(rt.bonus_tickets), 0) as bonus_tickets
FROM raffle_periods rp
LEFT JOIN raffle_tickets rt ON rt.period_id = rp.id
WHERE rp.status = 'active'
GROUP BY rp.id;
"""

def setup_raffle_database(engine):
    """
    Create all raffle system tables, indices, and views

    Args:
        engine: SQLAlchemy engine instance

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info("Setting up raffle system database schema...")

        with engine.begin() as conn:
            # Split SQL into individual statements and execute one by one
            # This is required for SQLite which can only execute one statement at a time
            statements = []
            current_statement = []

            for line in RAFFLE_SCHEMA_SQL.split('\n'):
                # Skip comments and empty lines
                stripped = line.strip()
                if not stripped or stripped.startswith('--'):
                    continue

                current_statement.append(line)

                # Check if this line ends a statement
                if stripped.endswith(';'):
                    statement = '\n'.join(current_statement)
                    statements.append(statement)
                    current_statement = []

            # Execute each statement
            for statement in statements:
                if statement.strip():
                    try:
                        conn.execute(text(statement))
                    except Exception as e:
                        # Log but continue (some statements might fail on re-run)
                        logger.debug(f"Statement warning: {e}")

        logger.info("✅ Raffle database schema created successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to setup raffle database: {e}")
        return False

def verify_raffle_schema(engine):
    """
    Verify that all required tables exist

    Args:
        engine: SQLAlchemy engine instance

    Returns:
        dict: Status of each table (True/False)
    """
    required_tables = [
        'raffle_periods',
        'raffle_tickets',
        'raffle_watchtime_converted',
        'raffle_gifted_subs',
        'raffle_shuffle_wagers',
        'raffle_shuffle_links',
        'raffle_ticket_log',
        'raffle_draws'
    ]

    status = {}

    try:
        with engine.begin() as conn:
            for table in required_tables:
                result = conn.execute(text(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = '{table}'
                    );
                """))
                status[table] = result.scalar()

    except Exception as e:
        logger.error(f"Failed to verify schema: {e}")

    return status

def get_current_period(engine):
    """
    Get the currently active raffle period

    Args:
        engine: SQLAlchemy engine instance

    Returns:
        dict: Current period info or None
    """
    try:
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT id, start_date, end_date, status, total_tickets
                FROM raffle_periods
                WHERE status = 'active'
                ORDER BY start_date DESC
                LIMIT 1
            """))
            row = result.fetchone()

            if row:
                return {
                    'id': row[0],
                    'start_date': row[1],
                    'end_date': row[2],
                    'status': row[3],
                    'total_tickets': row[4]
                }
            return None

    except Exception as e:
        logger.error(f"Failed to get current period: {e}")
        return None

def create_new_period(engine, start_date, end_date):
    """
    Create a new raffle period and reset all tickets

    Args:
        engine: SQLAlchemy engine instance
        start_date: datetime - Period start
        end_date: datetime - Period end

    Returns:
        int: New period ID or None
    """
    try:
        with engine.begin() as conn:
            # Get the old active period if it exists
            old_period = conn.execute(text("""
                SELECT id FROM raffle_periods
                WHERE status = 'active'
                ORDER BY id DESC
                LIMIT 1
            """)).fetchone()

            # Close any active periods
            if old_period:
                conn.execute(text("""
                    UPDATE raffle_periods
                    SET status = 'ended'
                    WHERE id = :period_id
                """), {'period_id': old_period[0]})
                logger.info(f"Closed old raffle period #{old_period[0]}")

            # Create new period
            result = conn.execute(text("""
                INSERT INTO raffle_periods (start_date, end_date, status)
                VALUES (:start, :end, 'active')
                RETURNING id
            """), {
                'start': start_date,
                'end': end_date
            })
            period_id = result.scalar()

            # Delete ALL tickets from all periods (fresh start)
            deleted_tickets = conn.execute(text("DELETE FROM raffle_tickets")).rowcount
            logger.info(f"Deleted {deleted_tickets} ticket records from all periods")

            # Clear ALL conversion tracking (fresh start)
            deleted_watchtime = conn.execute(text("DELETE FROM raffle_watchtime_converted")).rowcount
            logger.info(f"Deleted {deleted_watchtime} watchtime conversion records")

            # Snapshot current watchtime as "already converted" for new period
            # This prevents awarding tickets for watchtime earned before this period
            conn.execute(text("""
                INSERT INTO raffle_watchtime_converted (period_id, kick_name, minutes_converted, tickets_awarded)
                SELECT :period_id, username, minutes, 0
                FROM watchtime
                WHERE minutes > 0
            """), {'period_id': period_id})
            logger.info(f"Snapshotted existing watchtime for new period (prevents double-awarding)")

            deleted_subs = conn.execute(text("DELETE FROM raffle_gifted_subs")).rowcount
            logger.info(f"Deleted {deleted_subs} gifted sub records")

            # Clear ALL shuffle wager tracking (fresh start)
            deleted_wagers = conn.execute(text("DELETE FROM raffle_shuffle_wagers")).rowcount
            logger.info(f"Deleted {deleted_wagers} shuffle wager records")

        logger.info(f"✅ Created new raffle period #{period_id} and reset all tickets")
        return period_id

    except Exception as e:
        logger.error(f"Failed to create new period: {e}")
        return None

def migrate_add_created_at_to_shuffle_wagers(engine):
    """
    Migration: Add created_at column to raffle_shuffle_wagers table
    This is needed to determine if wagers were made during the current period
    """
    try:
        with engine.begin() as conn:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'raffle_shuffle_wagers'
                AND column_name = 'created_at'
            """))

            if result.fetchone():
                logger.info("✓ Column 'created_at' already exists in raffle_shuffle_wagers")
                return True

            # Add the column
            conn.execute(text("""
                ALTER TABLE raffle_shuffle_wagers
                ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """))

            # Set created_at for existing rows to last_checked (best approximation)
            conn.execute(text("""
                UPDATE raffle_shuffle_wagers
                SET created_at = last_checked
                WHERE created_at IS NULL
            """))

            logger.info("✅ Added 'created_at' column to raffle_shuffle_wagers table")
            return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

def migrate_add_platform_to_wager_tables(engine):
    """
    Migration: Add platform column to wager tracking tables
    This allows the bot to work with multiple gambling platforms (Shuffle, Stake, etc.)
    """
    try:
        from .config import WAGER_PLATFORM_NAME

        with engine.begin() as conn:
            # Add platform column to raffle_shuffle_wagers if it doesn't exist
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'raffle_shuffle_wagers'
                AND column_name = 'platform'
            """))

            if not result.fetchone():
                # Add the column
                conn.execute(text("""
                    ALTER TABLE raffle_shuffle_wagers
                    ADD COLUMN platform VARCHAR(50) DEFAULT 'shuffle'
                """))

                # Set platform for existing rows
                conn.execute(text("""
                    UPDATE raffle_shuffle_wagers
                    SET platform = 'shuffle'
                    WHERE platform IS NULL
                """))

                logger.info("✅ Added 'platform' column to raffle_shuffle_wagers table")
            else:
                logger.info("✓ Column 'platform' already exists in raffle_shuffle_wagers")

            # Add platform column to raffle_shuffle_links if it doesn't exist
            result2 = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'raffle_shuffle_links'
                AND column_name = 'platform'
            """))

            if not result2.fetchone():
                # Add the column
                conn.execute(text("""
                    ALTER TABLE raffle_shuffle_links
                    ADD COLUMN platform VARCHAR(50) DEFAULT 'shuffle'
                """))

                # Set platform for existing rows
                conn.execute(text("""
                    UPDATE raffle_shuffle_links
                    SET platform = 'shuffle'
                    WHERE platform IS NULL
                """))

                logger.info("✅ Added 'platform' column to raffle_shuffle_links table")
            else:
                logger.info("✓ Column 'platform' already exists in raffle_shuffle_links")

            return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

if __name__ == "__main__":
    """
    Run this script directly to setup the database schema
    """
    import os
    from dotenv import load_dotenv
    from sqlalchemy import create_engine

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load environment variables
    load_dotenv()

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        logger.error("❌ DATABASE_URL not found in environment variables")
        exit(1)

    # Create engine
    engine = create_engine(DATABASE_URL)

    # Setup schema
    success = setup_raffle_database(engine)

    if success:
        # Verify schema
        logger.info("\nVerifying schema...")
        status = verify_raffle_schema(engine)

        all_ok = all(status.values())
        if all_ok:
            logger.info("✅ All tables created successfully:")
            for table, exists in status.items():
                logger.info(f"  ✓ {table}")
        else:
            logger.warning("⚠️ Some tables missing:")
            for table, exists in status.items():
                symbol = "✓" if exists else "✗"
                logger.info(f"  {symbol} {table}")
    else:
        logger.error("❌ Schema setup failed")
        exit(1)
