"""Telegram account binding and one-time recovery challenges."""
from alembic import op
import sqlalchemy as sa
revision = "015_telegram_password_recovery"
down_revision = "014_h10_shared_wifi_lease"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("telegram_bindings",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chat_id", sa.String(64), unique=True, nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("telegram_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_telegram_challenges_user_id", "telegram_challenges", ["user_id"])

def downgrade():
    op.drop_index("ix_telegram_challenges_user_id", table_name="telegram_challenges")
    op.drop_table("telegram_challenges")
    op.drop_table("telegram_bindings")
