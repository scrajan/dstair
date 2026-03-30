"""
Database initialization utility.
Called on application startup to ensure the database exists and is seeded.
Idempotent — safe to call on every startup.
"""
import logging
import sqlalchemy
from extensions import db

logger = logging.getLogger(__name__)


def ensure_database_initialized(force_seed=False):
    """Check if the database has been initialized; if not, create tables and seed data."""
    inspector = sqlalchemy.inspect(db.engine)

    if not inspector.has_table("user") or force_seed:
        if not inspector.has_table("user"):
            logger.info("First run detected — creating tables...")
            db.create_all()
        else:
            logger.info("Force seed requested — updating database data...")

        from utils.db_seeder import run_seeding
        run_seeding()

        logger.info("Database initialized/seeded successfully.")
    else:
        logger.debug("Database already exists. Skipping initialization.")

    _run_migrations(inspector)


def _run_migrations(inspector):
    """
    Lightweight column-level migrations applied on every startup.
    Each migration is guarded so it only runs when the column is actually missing.
    """
    _migrate_analyses_table(inspector)
    _migrate_ai_analyses_table(inspector)
    _migrate_user_table(inspector)
    _drop_legacy_tables(inspector)


def _migrate_analyses_table(inspector):
    """Ensure analyses table has current columns and lacks legacy ones."""
    if not inspector.has_table("analyses"):
        return

    columns = {col['name'] for col in inspector.get_columns('analyses')}

    try:
        with db.engine.begin() as conn:
            if 'last_sync_timestamp' not in columns:
                logger.info("Migration: Adding last_sync_timestamp to analyses...")
                conn.execute(sqlalchemy.text(
                    "ALTER TABLE analyses ADD COLUMN last_sync_timestamp BIGINT DEFAULT 0"
                ))
                logger.info("Migration complete: last_sync_timestamp added.")

            if 'triggered_tools' not in columns:
                logger.info("Migration: Adding triggered_tools JSON to analyses...")
                conn.execute(sqlalchemy.text(
                    "ALTER TABLE analyses ADD COLUMN triggered_tools JSON DEFAULT '[]'"
                ))
                logger.info("Migration complete: triggered_tools column added.")
    except Exception as e:
        logger.error(f"Migration error on analyses table: {e}")


def _migrate_ai_analyses_table(inspector):
    """
    Rename legacy ai_analyses columns to the canonical spec names.
    Old: scores, comments
    New: ai_scores_for_all_questions, ai_comments_for_all_questions
    """
    if not inspector.has_table("ai_analyses"):
        return

    columns = {col['name'] for col in inspector.get_columns('ai_analyses')}

    try:
        with db.engine.begin() as conn:
            if 'ai_scores_for_all_questions' not in columns:
                if 'scores' in columns:
                    logger.info("Migration: Renaming scores → ai_scores_for_all_questions in ai_analyses...")
                    conn.execute(sqlalchemy.text(
                        "ALTER TABLE ai_analyses RENAME COLUMN scores TO ai_scores_for_all_questions"
                    ))
                else:
                    logger.info("Migration: Adding ai_scores_for_all_questions to ai_analyses...")
                    conn.execute(sqlalchemy.text(
                        "ALTER TABLE ai_analyses ADD COLUMN ai_scores_for_all_questions JSON DEFAULT '{}'"
                    ))
                logger.info("Migration complete: ai_scores_for_all_questions ready.")

            if 'ai_comments_for_all_questions' not in columns:
                if 'comments' in columns:
                    logger.info("Migration: Renaming comments → ai_comments_for_all_questions in ai_analyses...")
                    conn.execute(sqlalchemy.text(
                        "ALTER TABLE ai_analyses RENAME COLUMN comments TO ai_comments_for_all_questions"
                    ))
                else:
                    logger.info("Migration: Adding ai_comments_for_all_questions to ai_analyses...")
                    conn.execute(sqlalchemy.text(
                        "ALTER TABLE ai_analyses ADD COLUMN ai_comments_for_all_questions JSON DEFAULT '{}'"
                    ))
                logger.info("Migration complete: ai_comments_for_all_questions ready.")
    except Exception as e:
        logger.error(f"Migration error on ai_analyses table: {e}")


def _migrate_user_table(inspector):
    """Ensure user table has the profile_completed flag."""
    if not inspector.has_table("user"):
        return

    columns = {col['name'] for col in inspector.get_columns('user')}

    try:
        with db.engine.begin() as conn:
            if 'boolean_flag_indicating_if_user_profile_has_been_completed' not in columns:
                logger.info("Migration: Adding profile_completed flag to user table...")
                conn.execute(sqlalchemy.text(
                    "ALTER TABLE \"user\" ADD COLUMN "
                    "boolean_flag_indicating_if_user_profile_has_been_completed BOOLEAN DEFAULT 0"
                ))
                # Mark all pre-existing users as profile-completed so they bypass first-login redirect.
                conn.execute(sqlalchemy.text(
                    "UPDATE \"user\" SET boolean_flag_indicating_if_user_profile_has_been_completed = 1"
                ))
                logger.info("Migration complete: profile_completed flag added and backfilled.")
    except Exception as e:
        logger.error(f"Migration error on user table: {e}")


def _drop_legacy_tables(inspector):
    """Remove tables that no longer exist in the spec."""
    if inspector.has_table("analysis_tools"):
        logger.info("Migration: Dropping legacy analysis_tools join table...")
        try:
            with db.engine.begin() as conn:
                conn.execute(sqlalchemy.text("DROP TABLE IF EXISTS analysis_tools"))
            logger.info("Migration complete: analysis_tools dropped.")
        except Exception as e:
            logger.error(f"Migration error dropping analysis_tools: {e}")
