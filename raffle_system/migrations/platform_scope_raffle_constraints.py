"""
Migration: Platform-scope the raffle linking/wager UNIQUE constraints.

The wager system now supports multiple affiliate platforms (shuffle, howl). The
original UNIQUE constraints were keyed on username / discord_id WITHOUT platform,
which blocks the same username (or Discord user) existing on more than one
platform — so a howl row can never insert alongside a shuffle one.

This rescopes them to include `platform`:
  - raffle_shuffle_links:  UNIQUE(shuffle_username)            -> UNIQUE(shuffle_username, platform)
                           UNIQUE(discord_id)                  -> UNIQUE(discord_id, platform)
  - raffle_shuffle_wagers: UNIQUE(period_id, shuffle_username) -> UNIQUE(period_id, shuffle_username, platform)

Idempotent + safe to re-run: DROP CONSTRAINT IF EXISTS for the old ones, and the
new ones are only added when not already present (Postgres has no
ADD CONSTRAINT IF NOT EXISTS). Must run AFTER migrate_add_platform_to_wager_tables
(which guarantees the `platform` column exists, default 'shuffle') so existing
rows already carry a platform and the new constraints cannot conflict on apply.
"""

import logging
import os

logger = logging.getLogger(__name__)

# (constraint_name, table, definition) — the rescoped constraints to ensure exist.
_NEW_CONSTRAINTS = [
    ("raffle_shuffle_links_username_platform_key", "raffle_shuffle_links", "UNIQUE (shuffle_username, platform)"),
    ("raffle_shuffle_links_discord_platform_key", "raffle_shuffle_links", "UNIQUE (discord_id, platform)"),
    (
        "raffle_shuffle_wagers_period_username_platform_key",
        "raffle_shuffle_wagers",
        "UNIQUE (period_id, shuffle_username, platform)",
    ),
]

# Old, non-platform-scoped constraints to drop.
_OLD_CONSTRAINTS = [
    ("raffle_shuffle_links", "raffle_shuffle_links_shuffle_username_key"),
    ("raffle_shuffle_links", "raffle_shuffle_links_discord_id_key"),
    ("raffle_shuffle_wagers", "raffle_shuffle_wagers_period_id_shuffle_username_key"),
]


def migrate_platform_scope_raffle_constraints(engine):
    """Rescope raffle link/wager UNIQUE constraints to include `platform`."""
    try:
        raw_conn = engine.raw_connection()
        cursor = raw_conn.cursor()

        logger.debug("🔄 Platform-scoping raffle linking/wager UNIQUE constraints...")

        # 1. Add the new platform-scoped constraints first (guarded — no
        #    ADD CONSTRAINT IF NOT EXISTS in Postgres). The new constraints are
        #    looser-or-equal than the old ones, so on existing all-'shuffle' data
        #    they cannot fail.
        for conname, table, definition in _NEW_CONSTRAINTS:
            cursor.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (conname,))
            if cursor.fetchone():
                logger.debug(f"   ✓ {conname} already exists")
                continue
            logger.info(f"   Adding {conname} on {table}: {definition}")
            cursor.execute(f"ALTER TABLE {table} ADD CONSTRAINT {conname} {definition}")

        # 2. Drop the old non-platform-scoped constraints (safe + idempotent).
        for table, conname in _OLD_CONSTRAINTS:
            cursor.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {conname}")
            logger.debug(f"   Dropped (if existed): {conname}")

        raw_conn.commit()
        cursor.close()
        raw_conn.close()

        logger.debug("✅ Raffle constraints are platform-scoped")

    except Exception as e:
        logger.error(f"❌ Migration failed (platform_scope_raffle_constraints): {e}")
        raise


if __name__ == "__main__":
    from sqlalchemy import create_engine

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        exit(1)

    engine = create_engine(DATABASE_URL)
    migrate_platform_scope_raffle_constraints(engine)
