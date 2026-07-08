"""Add authentication columns to users table.

Revision ID: 0004_auth_columns
Revises: 0003_neon_backfill
Create Date: 2026-07-08

Adds password_hash, auth_provider, and google_id columns to support
email/password authentication and Google OAuth2 integration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_auth_columns"
down_revision: Union[str, None] = "0003_neon_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if columns already exist (Railway database may have them from previous migration)
    conn = op.get_bind()
    
    # Add password_hash column if it doesn't exist
    if not conn.dialect.has_column(conn, "users", "password_hash"):
        op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))
    
    # Add auth_provider column if it doesn't exist
    if not conn.dialect.has_column(conn, "users", "auth_provider"):
        op.add_column(
            "users",
            sa.Column("auth_provider", sa.String(), nullable=False, server_default="local")
        )
        # Update existing users to have auth_provider = 'local'
        op.execute("UPDATE users SET auth_provider = 'local' WHERE auth_provider IS NULL")
    
    # Add google_id column if it doesn't exist
    if not conn.dialect.has_column(conn, "users", "google_id"):
        op.add_column("users", sa.Column("google_id", sa.String(), nullable=True))
        # Create index only if column was just added
        op.create_unique_index(op.f("ix_users_google_id"), "users", ["google_id"])


def downgrade() -> None:
    # Remove in reverse order
    op.drop_index(op.f("ix_users_google_id"), table_name="users")
    op.drop_column("users", "google_id")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "password_hash")
