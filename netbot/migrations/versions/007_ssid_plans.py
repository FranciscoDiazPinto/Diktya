"""Ámbitos explícitos y planes privados de SSID con aprobación durable."""
from alembic import op
import sqlalchemy as sa
revision = '007_ssid_plans'
down_revision = '006_network_recipients'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('wifi_scopes', sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('name', sa.String(160), nullable=False), sa.Column('site_id', sa.String(160), nullable=False),
                    sa.Column('resources', sa.JSON(), nullable=False))
    op.create_table('wifi_scope_grants',
                    sa.Column('scope_id', sa.Integer(), sa.ForeignKey('wifi_scopes.id', ondelete='CASCADE'), primary_key=True),
                    sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True))
    op.create_table('ssid_plans',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('scope_id', sa.Integer(), sa.ForeignKey('wifi_scopes.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('source', sa.String(32), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('revision', sa.String(64), nullable=False),
        sa.Column('rows', sa.JSON(), nullable=False), sa.Column('selection', sa.JSON(), nullable=False),
        sa.Column('execution_results', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)))
    op.create_index('ix_ssid_plans_owner_id', 'ssid_plans', ['owner_id'])
    op.create_table('wifi_write_leases', sa.Column('resource_key',sa.String(64),primary_key=True),
                    sa.Column('plan_id',sa.String(36),sa.ForeignKey('ssid_plans.id'),nullable=False))
    op.create_index('ix_wifi_write_leases_plan_id','wifi_write_leases',['plan_id'])


def downgrade():
    op.drop_table('wifi_write_leases')
    op.drop_table('ssid_plans')
    op.drop_table('wifi_scope_grants')
    op.drop_table('wifi_scopes')
