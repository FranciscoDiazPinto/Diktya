"""Trazas y estado de agentes (HU017/HU018)."""
from alembic import op
import sqlalchemy as sa

revision = '020_agent_events'
down_revision = '019_change_recovery'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agent_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.String(36), nullable=False, unique=True),
        sa.Column('correlation_id', sa.String(64), nullable=False),
        sa.Column('agent_id', sa.String(32), nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('resource_type', sa.String(32)),
        sa.Column('resource_id', sa.String(160)),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('detail', sa.String(255)),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_agent_events_correlation_id', 'agent_events', ['correlation_id'])
    op.create_index('ix_agent_events_agent_id', 'agent_events', ['agent_id'])
    op.create_index('ix_agent_events_occurred_at', 'agent_events', ['occurred_at'])
    op.create_table(
        'agent_states',
        sa.Column('agent_id', sa.String(32), primary_key=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('interval_seconds', sa.Integer(), nullable=False),
        sa.Column('runs', sa.Integer(), nullable=False),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True)),
        sa.Column('last_success_at', sa.DateTime(timezone=True)),
        sa.Column('last_error_at', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.String(160)),
    )
    # Trazas de solo inserción también para el rol de la API (ver 017_app_role_grants).
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'netbot_app') THEN "
                   "REVOKE UPDATE, DELETE, TRUNCATE ON agent_events FROM netbot_app; END IF; END $$")


def downgrade():
    op.drop_table('agent_states')
    op.drop_index('ix_agent_events_occurred_at', table_name='agent_events')
    op.drop_index('ix_agent_events_agent_id', table_name='agent_events')
    op.drop_index('ix_agent_events_correlation_id', table_name='agent_events')
    op.drop_table('agent_events')
