"""Neon production adoption: backfill flat problem metadata + stats columns from the
pre-existing JSONB `meta`/`stats` columns, add missing indexes and checks.

PostgreSQL-only logic is dialect-guarded; on SQLite (dev) this is a no-op
except for portable index creation. Safe to re-run (idempotent SQL).

Revision ID: 0002_neon_backfill
Revises: 0001_baseline
Create Date: 2026-07-06
"""
from alembic import op
from sqlalchemy import text

revision = "0002_neon_backfill"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


PG_BACKFILL = r"""
DO $$
BEGIN
    -- Only when the legacy JSONB columns exist (live Neon database)
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'problems' AND column_name = 'meta') THEN
        UPDATE problems SET
            interview_round     = COALESCE(interview_round, meta->>'interview_round'),
            why_this_problem    = COALESCE(why_this_problem, meta->>'why_this_problem'),
            key_concepts        = CASE WHEN key_concepts IS NULL OR key_concepts::text IN ('null','[]')
                                       THEN COALESCE(meta->'key_concepts', '[]'::jsonb)::json
                                       ELSE key_concepts END,
            similar_problems    = CASE WHEN similar_problems IS NULL OR similar_problems::text IN ('null','[]')
                                       THEN COALESCE(meta->'similar_problems', '[]'::jsonb)::json
                                       ELSE similar_problems END,
            next_level_problems = CASE WHEN next_level_problems IS NULL OR next_level_problems::text IN ('null','[]')
                                       THEN COALESCE(meta->'next_level_problems', '[]'::jsonb)::json
                                       ELSE next_level_problems END,
            sources             = CASE WHEN sources IS NULL OR sources::text IN ('null','[]')
                                       THEN COALESCE(meta->'sources', '[]'::jsonb)::json
                                       ELSE sources END,
            what_youll_learn    = CASE WHEN what_youll_learn IS NULL OR what_youll_learn::text IN ('null','[]')
                                       THEN (CASE jsonb_typeof(meta->'what_youll_learn')
                                                 WHEN 'array'  THEN meta->'what_youll_learn'
                                                 WHEN 'string' THEN jsonb_build_array(meta->'what_youll_learn')
                                                 ELSE '[]'::jsonb END)::json
                                       ELSE what_youll_learn END;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'problems' AND column_name = 'stats') THEN
        UPDATE problems SET
            attempts              = COALESCE(attempts,              (stats->>'attempts')::int, 0),
            completions           = COALESCE(completions,           (stats->>'completions')::int, 0),
            success_rate          = COALESCE(success_rate,          (stats->>'success_rate')::float, 0),
            avg_rating            = COALESCE(avg_rating,            (stats->>'avg_rating')::float, 0),
            rating_count          = COALESCE(rating_count,          (stats->>'rating_count')::int, 0),
            bookmark_count        = COALESCE(bookmark_count,        (stats->>'bookmark_count')::int, 0),
            avg_attempts_to_solve = COALESCE(avg_attempts_to_solve, (stats->>'avg_attempts_to_solve')::float, 0);
    END IF;

    -- Backstop defaults for rows where JSONB keys were absent
    UPDATE problems SET attempts = 0 WHERE attempts IS NULL;
    UPDATE problems SET completions = 0 WHERE completions IS NULL;
    UPDATE problems SET success_rate = 0 WHERE success_rate IS NULL;
    UPDATE problems SET avg_rating = 0 WHERE avg_rating IS NULL;
    UPDATE problems SET rating_count = 0 WHERE rating_count IS NULL;
    UPDATE problems SET bookmark_count = 0 WHERE bookmark_count IS NULL;
    UPDATE problems SET avg_attempts_to_solve = 0 WHERE avg_attempts_to_solve IS NULL;

    -- Ratings range check (new tables created by the baseline may pre-date the
    -- model-level CheckConstraint)
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_rating_range') THEN
        ALTER TABLE problem_ratings
            ADD CONSTRAINT ck_rating_range CHECK (rating >= 1 AND rating <= 5);
    END IF;
END $$;
"""

PG_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_sessions_user_status ON sessions (user_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_sessions_problem_id ON sessions (problem_id)",
    "CREATE INDEX IF NOT EXISTS ix_sessions_session_token ON sessions (session_token)",
    "CREATE INDEX IF NOT EXISTS ix_problems_difficulty ON problems (difficulty)",
    "CREATE INDEX IF NOT EXISTS ix_evaluations_problem_score ON evaluations (problem_id, composite_score)",
    "CREATE INDEX IF NOT EXISTS ix_evaluations_user_created ON evaluations (user_id, created_at)",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text(PG_BACKFILL))
    for ddl in PG_INDEXES:
        bind.execute(text(ddl))


def downgrade() -> None:
    # Backfill is data-only and additive; nothing to reverse safely.
    pass
