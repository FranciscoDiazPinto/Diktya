"""Planes persistentes para cambios de VLAN en SSID existentes (H10)."""

from alembic import op
import sqlalchemy as sa


revision = "013_ssid_vlan_change_plans"
down_revision = "012_wifi_email_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ssid_vlan_change_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "scope_id",
            sa.Integer(),
            sa.ForeignKey("wifi_scopes.id"),
            nullable=False,
        ),
        sa.Column("broadcast_id", sa.String(160), nullable=False),
        sa.Column("site_id", sa.String(160), nullable=False),
        sa.Column("ssid", sa.String(160), nullable=False),
        sa.Column("current_network_id", sa.String(160), nullable=False),
        sa.Column("target_network_id", sa.String(160), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("execution_results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_ssid_vlan_change_plans_owner_id",
        "ssid_vlan_change_plans",
        ["owner_id"],
    )


def downgrade():
    op.drop_index(
        "ix_ssid_vlan_change_plans_owner_id",
        table_name="ssid_vlan_change_plans",
    )
    op.drop_table("ssid_vlan_change_plans")