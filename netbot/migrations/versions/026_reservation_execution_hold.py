"""Keep VLAN reservations protected through execution and reconciliation."""
from alembic import op
import sqlalchemy as sa

revision = '026_reservation_execution_hold'
down_revision = '025_vlan_batch_plans'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vlan_reservations', sa.Column('held_by_plan_id', sa.String(36), nullable=True))
    op.create_index('ix_vlan_reservations_held_by_plan_id', 'vlan_reservations', ['held_by_plan_id'])


def downgrade():
    reservations = sa.table('vlan_reservations', sa.column('held_by_plan_id'))
    if op.get_bind().scalar(sa.select(reservations.c.held_by_plan_id).where(
        reservations.c.held_by_plan_id.is_not(None),
    ).limit(1)):
        raise RuntimeError('Hay reservas protegidas por trabajos activos o pendientes de conciliación.')
    op.drop_index('ix_vlan_reservations_held_by_plan_id', table_name='vlan_reservations')
    op.drop_column('vlan_reservations', 'held_by_plan_id')
