"""Add authentication columns to users table.

Revision ID: 0003_auth_columns
Revises: 0002_neon_backfill
Create Date: 2026-07-08

Adds password_hash, auth_provider, and google_id columns to support
email/password authentication and Google OAuth2 integration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_auth_columns"
down_revision: Union[str, None] = "0002_neon_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add password_hash column (nullable for Google-only users)
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))
    
    # Add auth_provider column with default value
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(), nullable=False, server_default="local")
    )
    
    # Add google_id column (nullable, unique, indexed)
    op.add_column("users", sa.Column("google_id", sa.String(), nullable=True))
    op.create_unique_index(op.f("ix_users_google_id"), "users", ["google_id"])
    
    # Update existing users to have auth_provider = 'local'
    # (they were created before authentication existed)
    op.execute("UPDATE users SET auth_provider = 'local' WHERE auth_provider IS NULL")


def downgrade() -> None:
    # Remove in reverse order
    op.drop_index(op.f("ix_users_google_id"), table_name="users")
    op.drop_column("users", "google_id")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "password_hash")
