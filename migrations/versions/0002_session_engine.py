"""Session engine expansion - no-op migration for Railway compatibility.

This migration exists to match Railway's database migration history.
The actual schema changes were already applied in the production database.
This is a no-op migration to maintain migration chain consistency.

Revision ID: 0002_session_engine
Revises: 0001_baseline
Create Date: 2026-07-08
"""

from alembic import op

revision = "0002_session_engine"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op - schema changes already exist in Railway database
    pass


def downgrade() -> None:
    # No-op - cannot downgrade production schema
    pass
