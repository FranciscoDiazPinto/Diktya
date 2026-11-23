"""Store reviewed batches and dependencies between their approved rows."""
from alembic import op
import sqlalchemy as sa

revision = '025_vlan_batch_plans'
down_revision = '024_fair_accepts_changes'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ssid_vlan_batch_plans',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('scope_id', sa.Integer(), sa.ForeignKey('wifi_scopes.id'), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('revision', sa.String(64), nullable=False),
        sa.Column('rows', sa.JSON(), nullable=False),
        sa.Column('selection', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_ssid_vlan_batch_plans_owner_id', 'ssid_vlan_batch_plans', ['owner_id'])
    with op.batch_alter_table('ssid_vlan_change_plans') as batch:
        batch.add_column(sa.Column('batch_id', sa.String(36)))
        batch.add_column(sa.Column('batch_row', sa.Integer()))
        batch.add_column(sa.Column('predecessor_id', sa.String(36)))
        batch.create_foreign_key('fk_vlan_plan_batch', 'ssid_vlan_batch_plans', ['batch_id'], ['id'])
        batch.create_foreign_key('fk_vlan_plan_predecessor', 'ssid_vlan_change_plans', ['predecessor_id'], ['id'])
        batch.create_index('ix_ssid_vlan_change_plans_batch_id', ['batch_id'])


def downgrade():
    batches = sa.table('ssid_vlan_batch_plans', sa.column('id'))
    if op.get_bind().scalar(sa.select(batches.c.id).limit(1)):
        raise RuntimeError('El downgrade eliminaría lotes y su orden de ejecución.')
    with op.batch_alter_table('ssid_vlan_change_plans') as batch:
        batch.drop_index('ix_ssid_vlan_change_plans_batch_id')
        batch.drop_constraint('fk_vlan_plan_predecessor', type_='foreignkey')
        batch.drop_constraint('fk_vlan_plan_batch', type_='foreignkey')
        batch.drop_column('predecessor_id')
        batch.drop_column('batch_row')
        batch.drop_column('batch_id')
    op.drop_table('ssid_vlan_batch_plans')
