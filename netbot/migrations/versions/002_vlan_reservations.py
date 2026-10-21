"""Store VLAN reservation lifecycle."""
from alembic import op
import sqlalchemy as sa

revision = "002_vlan_reservations"
down_revision = "001_authentication_roles"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "vlan_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_interface", sa.String(64), nullable=False),
        sa.Column("tag", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(160)),
        sa.Column("interface_name", sa.String(64), nullable=False),
        sa.Column("event_name", sa.String(160), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("ssid", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("released_at", sa.DateTime(timezone=True)),
    )
    op.create_index("uq_active_vlan_reservation", "vlan_reservations",
                    ["parent_interface", "tag"], unique=True,
                    sqlite_where=sa.text("status = 'reserved'"),
                    postgresql_where=sa.text("status = 'reserved'"))

def downgrade() -> None:
    op.drop_index("uq_active_vlan_reservation", table_name="vlan_reservations")
    op.drop_table("vlan_reservations")
