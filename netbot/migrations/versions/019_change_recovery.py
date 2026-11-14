"""Reinicios confirmados, bloqueo por equipo y ciclo de reservas (HU009/HU011/HU012)."""
from alembic import op
import sqlalchemy as sa

revision = '019_change_recovery'
down_revision = '018_monitoring_maintenance'
branch_labels = None
depends_on = None

ACTIVE = sa.text("status IN ('reserved', 'assigned')")
RESERVED = sa.text("status = 'reserved'")


def upgrade():
    op.create_table(
        'device_restart_plans',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('scope_id', sa.Integer(), sa.ForeignKey('wifi_scopes.id'), nullable=False),
        sa.Column('site_id', sa.String(160), nullable=False),
        sa.Column('device_id', sa.String(160), nullable=False),
        sa.Column('device_name', sa.String(255), nullable=False),
        sa.Column('access_point', sa.Boolean(), nullable=False),
        sa.Column('connected_clients', sa.Integer()),
        sa.Column('purpose', sa.String(500), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('revision', sa.String(64), nullable=False),
        sa.Column('execution_results', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_device_restart_plans_owner_id', 'device_restart_plans', ['owner_id'])
    with op.batch_alter_table('wifi_write_leases') as batch:
        batch.add_column(sa.Column('restart_plan_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_wifi_write_leases_restart_plan', 'device_restart_plans',
                                 ['restart_plan_id'], ['id'])
        batch.create_index('ix_wifi_write_leases_restart_plan_id', ['restart_plan_id'])
    # Las reservas anteriores no vencen: solo las nuevas reciben plazo.
    op.add_column('vlan_reservations', sa.Column('expires_at', sa.DateTime(timezone=True)))
    op.add_column('vlan_reservations', sa.Column('assigned_at', sa.DateTime(timezone=True)))
    op.drop_index('uq_active_vlan_reservation', table_name='vlan_reservations')
    op.create_index('uq_active_vlan_reservation', 'vlan_reservations', ['parent_interface', 'tag'], unique=True,
                    sqlite_where=ACTIVE, postgresql_where=ACTIVE)


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text(
            'SELECT COUNT(*) FROM wifi_write_leases WHERE restart_plan_id IS NOT NULL')).scalar_one():
        raise RuntimeError('Existen bloqueos de reinicio: concilia antes de revertir la migración.')
    if connection.execute(sa.text("SELECT COUNT(*) FROM vlan_reservations WHERE status = 'assigned'")).scalar_one():
        raise RuntimeError('Existen reservas asignadas: libéralas antes de revertir la migración.')
    op.drop_index('uq_active_vlan_reservation', table_name='vlan_reservations')
    op.create_index('uq_active_vlan_reservation', 'vlan_reservations', ['parent_interface', 'tag'], unique=True,
                    sqlite_where=RESERVED, postgresql_where=RESERVED)
    with op.batch_alter_table('vlan_reservations') as batch:
        batch.drop_column('assigned_at')
        batch.drop_column('expires_at')
    with op.batch_alter_table('wifi_write_leases') as batch:
        batch.drop_index('ix_wifi_write_leases_restart_plan_id')
        batch.drop_constraint('fk_wifi_write_leases_restart_plan', type_='foreignkey')
        batch.drop_column('restart_plan_id')
    op.drop_index('ix_device_restart_plans_owner_id', table_name='device_restart_plans')
    op.drop_table('device_restart_plans')
