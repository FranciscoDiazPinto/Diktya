"""Inicio real de ejecución y evidencia de reinicio para recuperación segura."""
from alembic import op
import sqlalchemy as sa

revision = '021_execution_ownership'
down_revision = '020_agent_events'
branch_labels = None
depends_on = None

TABLES = ('ssid_plans', 'ssid_vlan_change_plans', 'device_restart_plans')


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column('execution_started_at', sa.DateTime(timezone=True)))
        # No usar confirmed_at: las aprobaciones antiguas pueden haber empezado recién.
        # Los workers deben estar detenidos al migrar; se otorga el plazo completo
        # de recuperación a los executing heredados antes de conciliarlos.
        plans = sa.table(table, sa.column('execution_started_at'), sa.column('status'))
        op.execute(plans.update().where(plans.c.status == 'executing')
                   .values(execution_started_at=sa.func.current_timestamp()))
    op.add_column('device_restart_plans', sa.Column('uptime_before', sa.Integer()))


def downgrade():
    for table in TABLES:
        plans = sa.table(table, sa.column('status'))
        pending = op.get_bind().scalar(sa.select(sa.func.count()).select_from(plans)
                                      .where(plans.c.status.in_(('executing', 'uncertain', 'rollback_failed'))))
        if pending:
            raise RuntimeError('Existen trabajos pendientes de conciliación; no se puede retirar su seguimiento.')
    with op.batch_alter_table('device_restart_plans') as batch:
        batch.drop_column('uptime_before')
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column('execution_started_at')
