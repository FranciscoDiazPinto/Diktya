"""Bind each approved batch to its target VLAN reservations."""
from alembic import op
import sqlalchemy as sa

revision = '027_vlan_batch_reservation'
down_revision = '026_reservation_execution_hold'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('wifi_write_leases') as batch:
        batch.add_column(sa.Column('vlan_batch_id', sa.String(36)))
        batch.create_foreign_key('fk_wifi_lease_vlan_batch', 'ssid_vlan_batch_plans', ['vlan_batch_id'], ['id'])
        batch.create_index('ix_wifi_write_leases_vlan_batch_id', ['vlan_batch_id'])


def downgrade():
    leases = sa.table('wifi_write_leases', sa.column('vlan_batch_id'))
    if op.get_bind().scalar(sa.select(leases.c.vlan_batch_id).where(
        leases.c.vlan_batch_id.is_not(None),
    ).limit(1)):
        raise RuntimeError('Hay lotes con VLAN reservadas.')
    with op.batch_alter_table('wifi_write_leases') as batch:
        batch.drop_index('ix_wifi_write_leases_vlan_batch_id')
        batch.drop_constraint('fk_wifi_lease_vlan_batch', type_='foreignkey')
        batch.drop_column('vlan_batch_id')
