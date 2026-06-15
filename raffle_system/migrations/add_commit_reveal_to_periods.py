"""
Migration: Add commit-reveal columns for provably-fair raffle draws.

Adds to raffle_periods:
  - server_seed            TEXT  (the seed, committed at period creation,
                                  revealed only at draw time)
  - server_seed_commitment TEXT  (SHA256(server_seed) — published the moment
                                  the period opens so the operator can't grind
                                  seeds after the ticket pool is known)

Adds to raffle_draws:
  - server_seed_commitment TEXT  (copied onto the draw row so each draw is
                                  self-contained for verifiers)
"""

import os


def migrate_add_commit_reveal_to_periods(engine):
    """Add commit-reveal columns to raffle_periods and raffle_draws."""
    try:
        raw_conn = engine.raw_connection()
        cursor = raw_conn.cursor()

        print("🔄 Checking commit-reveal columns (raffle_periods / raffle_draws)...")

        # --- raffle_periods: server_seed + server_seed_commitment ---
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'raffle_periods'
            AND column_name IN ('server_seed', 'server_seed_commitment')
        """
        )
        period_existing = [row[0] for row in cursor.fetchall()]

        period_to_add = []
        if "server_seed" not in period_existing:
            period_to_add.append("server_seed")
        if "server_seed_commitment" not in period_existing:
            period_to_add.append("server_seed_commitment")

        for column_name in period_to_add:
            print(f"   Adding raffle_periods.{column_name} TEXT")
            cursor.execute(f"ALTER TABLE raffle_periods ADD COLUMN IF NOT EXISTS {column_name} TEXT")

        # --- raffle_draws: server_seed_commitment ---
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'raffle_draws'
            AND column_name = 'server_seed_commitment'
        """
        )
        draw_has_commitment = cursor.fetchone() is not None

        if not draw_has_commitment:
            print("   Adding raffle_draws.server_seed_commitment TEXT")
            cursor.execute("ALTER TABLE raffle_draws ADD COLUMN IF NOT EXISTS server_seed_commitment TEXT")

        if not period_to_add and draw_has_commitment:
            print("✅ Commit-reveal columns already exist")
            cursor.close()
            raw_conn.close()
            return

        raw_conn.commit()
        cursor.close()
        raw_conn.close()

        print("✅ Added commit-reveal column(s)")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise


if __name__ == "__main__":
    from sqlalchemy import create_engine

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        exit(1)

    engine = create_engine(DATABASE_URL)
    migrate_add_commit_reveal_to_periods(engine)
