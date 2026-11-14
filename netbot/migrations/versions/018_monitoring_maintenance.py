"""Mantenimiento declarado y transición a inactivo de SSID/VLAN (HU011/HU017)."""
from alembic import op
import sqlalchemy as sa

revision = '018_monitoring_maintenance'
down_revision = '017_app_role_grants'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'monitoring_maintenance',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('external_id', sa.String(160), nullable=False),
        sa.Column('reason', sa.String(160), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_monitoring_maintenance_target', 'monitoring_maintenance', ['source', 'external_id'])
    op.add_column('monitoring_vlans', sa.Column('disabled_since', sa.DateTime(timezone=True)))
    op.add_column('monitoring_ssids', sa.Column('disabled_since', sa.DateTime(timezone=True)))


def downgrade():
    with op.batch_alter_table('monitoring_ssids') as batch:
        batch.drop_column('disabled_since')
    with op.batch_alter_table('monitoring_vlans') as batch:
        batch.drop_column('disabled_since')
    op.drop_index('ix_monitoring_maintenance_target', table_name='monitoring_maintenance')
    op.drop_table('monitoring_maintenance')
