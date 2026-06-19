"""
Migration: Add `platform` to the `links` table and platform-scope its UNIQUE
constraints so a Discord user can link a Kick AND a Twitch account in the same
server.

Mirrors raffle_system/migrations/platform_scope_raffle_constraints.py and the
existing raffle_shuffle_links.platform precedent.

Changes:
  - links.platform  varchar(50) NOT NULL DEFAULT 'kick'   (backfills existing rows
    to 'kick' → zero behavior change for current servers)
  - UNIQUE(discord_id, discord_server_id)        -> UNIQUE(discord_id, discord_server_id, platform)
  - UNIQUE(kick_name,  discord_server_id)         -> UNIQUE(kick_name,  discord_server_id, platform)

The `kick_name` column is kept as the generic per-platform username column (for a
twitch row it stores the Twitch login). Renaming it is high-blast-radius and is
intentionally avoided.

Idempotent + safe to re-run: ADD COLUMN IF NOT EXISTS, guarded ADD CONSTRAINT,
DROP CONSTRAINT IF EXISTS. The new constraints are looser-or-equal than the old
ones on existing all-'kick' data, so they cannot fail on apply.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Existing (old) non-platform-scoped constraint names. schema.sql names them
# explicitly; a fresh DB created by bot.py's CREATE TABLE gets Postgres
# auto-generated names. We drop the known names AND auto-discover any remaining
# 2-column UNIQUE on these column sets (see _drop_unscoped_uniques).
_OLD_CONSTRAINTS = [
    "links_discord_server_unique",  # UNIQUE (discord_id, discord_server_id)
    "links_kick_name_server_unique",  # UNIQUE (kick_name, discord_server_id)
    "links_kick_name_discord_server_id_key",  # auto-named by bot.py CREATE TABLE
    "links_discord_id_discord_server_id_key",
]

# New platform-scoped constraints.
_NEW_CONSTRAINTS = [
    ("links_discord_server_platform_key", "UNIQUE (discord_id, discord_server_id, platform)"),
    ("links_kick_name_server_platform_key", "UNIQUE (kick_name, discord_server_id, platform)"),
]


def _drop_unscoped_uniques(cursor):
    """Drop any UNIQUE constraint on links whose column set is exactly
    {kick_name, discord_server_id} or {discord_id, discord_server_id} (i.e. the
    old 2-column uniques without `platform`), regardless of constraint name. The
    new platform-scoped 3-column uniques are left intact."""
    cursor.execute(
        """
        SELECT con.conname, array_agg(att.attname ORDER BY att.attname) AS cols
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
        WHERE rel.relname = 'links' AND con.contype = 'u'
        GROUP BY con.conname
        """
    )
    targets = {frozenset(["kick_name", "discord_server_id"]), frozenset(["discord_id", "discord_server_id"])}
    for conname, cols in cursor.fetchall():
        if frozenset(cols) in targets:
            logger.info(f"   Dropping unscoped unique {conname} ({cols})")
            cursor.execute(f"ALTER TABLE links DROP CONSTRAINT IF EXISTS {conname}")


def migrate_add_platform_to_links(engine):
    """Add links.platform (default 'kick') and platform-scope its UNIQUE constraints."""
    try:
        raw_conn = engine.raw_connection()
        cursor = raw_conn.cursor()

        # Table may not exist yet on a fresh DB — bot.py creates it at startup.
        cursor.execute("SELECT to_regclass('public.links')")
        if not cursor.fetchone()[0]:
            logger.debug("   ℹ️ links table doesn't exist yet — skipping (bot.py will create it)")
            cursor.close()
            raw_conn.close()
            return

        logger.debug("🔄 Adding platform column + platform-scoped constraints to links...")

        # 1. Add the platform column, backfilling existing rows to 'kick'.
        cursor.execute("ALTER TABLE links ADD COLUMN IF NOT EXISTS platform varchar(50) NOT NULL DEFAULT 'kick'")

        # 2. Add the new platform-scoped UNIQUE constraints (guarded).
        for conname, definition in _NEW_CONSTRAINTS:
            cursor.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (conname,))
            if cursor.fetchone():
                logger.debug(f"   ✓ {conname} already exists")
                continue
            logger.info(f"   Adding {conname}: {definition}")
            cursor.execute(f"ALTER TABLE links ADD CONSTRAINT {conname} {definition}")

        # 3. Drop the old non-platform-scoped constraints (known names).
        for conname in _OLD_CONSTRAINTS:
            cursor.execute(f"ALTER TABLE links DROP CONSTRAINT IF EXISTS {conname}")
            logger.debug(f"   Dropped (if existed): {conname}")

        # 3b. Auto-discover and drop any remaining UNIQUE constraint on exactly
        #     (kick_name, discord_server_id) or (discord_id, discord_server_id)
        #     without `platform` (e.g. Postgres-auto-named ones from a fresh DB).
        _drop_unscoped_uniques(cursor)

        raw_conn.commit()
        cursor.close()
        raw_conn.close()
        logger.debug("✅ links table is platform-scoped")
    except Exception as e:
        logger.error(f"❌ Migration failed (add_platform_to_links): {e}")
        raise


if __name__ == "__main__":
    from sqlalchemy import create_engine

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        exit(1)
    engine = create_engine(DATABASE_URL)
    migrate_add_platform_to_links(engine)
