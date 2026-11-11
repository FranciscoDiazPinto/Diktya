"""H10: permitir que creación y modificación compartan el mismo bloqueo WiFi."""
from alembic import op
import sqlalchemy as sa

revision = '014_h10_shared_wifi_lease'
down_revision = '013_ssid_vlan_change_plans'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('wifi_write_leases') as batch:
        batch.alter_column('plan_id', existing_type=sa.String(length=36), nullable=True)
        batch.add_column(sa.Column('vlan_plan_id', sa.String(length=36), nullable=True))
        batch.create_foreign_key('fk_wifi_write_leases_vlan_plan', 'ssid_vlan_change_plans',
                                 ['vlan_plan_id'], ['id'])
        batch.create_index('ix_wifi_write_leases_vlan_plan_id', ['vlan_plan_id'])


def downgrade():
    # No convertir leases H10 a leases de creación: exigir conciliación previa.
    connection = op.get_bind()
    remaining = connection.execute(sa.text(
        'SELECT COUNT(*) FROM wifi_write_leases WHERE vlan_plan_id IS NOT NULL'
    )).scalar_one()
    if remaining:
        raise RuntimeError('Existen bloqueos H10: concilia antes de revertir la migración.')
    with op.batch_alter_table('wifi_write_leases') as batch:
        batch.drop_index('ix_wifi_write_leases_vlan_plan_id')
        batch.drop_constraint('fk_wifi_write_leases_vlan_plan', type_='foreignkey')
        batch.drop_column('vlan_plan_id')
        batch.alter_column('plan_id', existing_type=sa.String(length=36), nullable=False)
