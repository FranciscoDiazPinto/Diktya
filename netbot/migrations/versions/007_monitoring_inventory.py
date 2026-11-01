"""Inventario persistido, disponibilidad, alertas y planos de cobertura (épica 002)."""
from alembic import op
import sqlalchemy as sa

revision = '007_monitoring_inventory'
down_revision = '006_network_recipients'
branch_labels = None
depends_on = None

_when = sa.DateTime(timezone=True)


def upgrade():
    op.create_table('monitoring_sources',
        sa.Column('source', sa.String(32), primary_key=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('version', sa.String(120)),
        sa.Column('last_attempt_at', _when),
        sa.Column('last_success_at', _when),
        sa.Column('next_attempt_at', _when),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('last_error_kind', sa.String(32)),
        sa.Column('last_error_message', sa.String(255)))

    op.create_table('monitoring_devices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('external_id', sa.String(160), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('device_type', sa.String(16), nullable=False),
        sa.Column('model', sa.String(120)),
        sa.Column('mac_address', sa.String(17)),
        sa.Column('ip_address', sa.String(64)),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('last_online_at', _when),
        sa.Column('last_seen_at', _when, nullable=False),
        sa.Column('missing_since', _when),
        sa.UniqueConstraint('source', 'external_id', name='uq_monitoring_device'))
    for column in ('source', 'device_type', 'state'):
        op.create_index(f'ix_monitoring_devices_{column}', 'monitoring_devices', [column])

    op.create_table('monitoring_vlans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('external_id', sa.String(160), nullable=False),
        sa.Column('name', sa.String(255)),
        sa.Column('tag', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean()),
        sa.Column('last_seen_at', _when, nullable=False),
        sa.Column('missing_since', _when),
        sa.UniqueConstraint('source', 'external_id', name='uq_monitoring_vlan'))
    op.create_index('ix_monitoring_vlans_source', 'monitoring_vlans', ['source'])

    op.create_table('monitoring_ssids',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('external_id', sa.String(160), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('security', sa.String(40)),
        sa.Column('vlan_tag', sa.Integer()),
        sa.Column('last_seen_at', _when, nullable=False),
        sa.Column('missing_since', _when),
        sa.UniqueConstraint('source', 'external_id', name='uq_monitoring_ssid'))
    op.create_index('ix_monitoring_ssids_source', 'monitoring_ssids', ['source'])

    op.create_table('monitoring_availability',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('monitoring_devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bucket_start', _when, nullable=False),
        sa.Column('online_seconds', sa.Float(), nullable=False),
        sa.Column('observed_seconds', sa.Float(), nullable=False),
        sa.UniqueConstraint('device_id', 'bucket_start', name='uq_monitoring_availability'))
    op.create_index('ix_monitoring_availability_bucket_start', 'monitoring_availability', ['bucket_start'])

    op.create_table('monitoring_alerts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('dedup_key', sa.String(255), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('severity_rank', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(16), nullable=False),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('monitoring_devices.id', ondelete='SET NULL')),
        sa.Column('device_name', sa.String(255)),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('detected_at', _when, nullable=False),
        sa.Column('last_seen_at', _when, nullable=False),
        sa.Column('resolved_at', _when))
    for column in ('source', 'device_id', 'resolved_at'):
        op.create_index(f'ix_monitoring_alerts_{column}', 'monitoring_alerts', [column])
    op.create_index('uq_monitoring_alert_active', 'monitoring_alerts', ['dedup_key'], unique=True,
                    sqlite_where=sa.text('resolved_at IS NULL'),
                    postgresql_where=sa.text('resolved_at IS NULL'))

    op.create_table('monitoring_plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('content_type', sa.String(32), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', _when, nullable=False))

    op.create_table('monitoring_placements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(), sa.ForeignKey('monitoring_plans.id', ondelete='CASCADE'), nullable=False),
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('monitoring_devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('x', sa.Float(), nullable=False),
        sa.Column('y', sa.Float(), nullable=False),
        sa.UniqueConstraint('device_id', name='uq_monitoring_placement_device'))
    op.create_index('ix_monitoring_placements_plan_id', 'monitoring_placements', ['plan_id'])


def downgrade():
    for table in ('monitoring_placements', 'monitoring_plans', 'monitoring_alerts', 'monitoring_availability',
                  'monitoring_ssids', 'monitoring_vlans', 'monitoring_devices', 'monitoring_sources'):
        op.drop_table(table)
