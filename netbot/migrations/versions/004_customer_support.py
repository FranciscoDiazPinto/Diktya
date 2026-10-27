"""Configuración de soporte, tickets y auditoría sin secretos."""
from alembic import op
import sqlalchemy as sa

revision = "004_customer_support"
down_revision = "003_scoped_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "network_support_config",
        sa.Column("network_id", sa.Integer(), sa.ForeignKey("networks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("credential_ref", sa.String(160)),
        sa.Column("monitoring_interface_id", sa.String(160)),
    )
    op.create_table(
        "support_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("network_id", sa.Integer(), sa.ForeignKey("networks.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_audit_actor_id", "support_audit", ["actor_id"])
    op.create_index("ix_support_audit_network_id", "support_audit", ["network_id"])
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("network_id", sa.Integer(), sa.ForeignKey("networks.id"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("summary", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("network_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("created_by_id", "request_key", name="uq_ticket_owner_request"),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'closed')", name="ck_ticket_status"),
    )
    op.create_index("ix_tickets_network_id", "tickets", ["network_id"])
    op.create_index("ix_tickets_created_by_id", "tickets", ["created_by_id"])
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ticket_events_ticket_id", "ticket_events", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("ix_ticket_events_ticket_id", table_name="ticket_events")
    op.drop_table("ticket_events")
    op.drop_index("ix_tickets_created_by_id", table_name="tickets")
    op.drop_index("ix_tickets_network_id", table_name="tickets")
    op.drop_table("tickets")
    op.drop_index("ix_support_audit_network_id", table_name="support_audit")
    op.drop_index("ix_support_audit_actor_id", table_name="support_audit")
    op.drop_table("support_audit")
    op.drop_table("network_support_config")
