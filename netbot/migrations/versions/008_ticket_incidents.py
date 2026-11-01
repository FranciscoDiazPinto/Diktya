"""Tickets de incidentes, criticidad, seguimiento y notificaciones (épica 005)."""
from alembic import op
import sqlalchemy as sa

revision = '008_ticket_incidents'
down_revision = '007_monitoring_inventory'
branch_labels = None
depends_on = None

_when = sa.DateTime(timezone=True)


def upgrade():
    with op.batch_alter_table('tickets') as batch:
        batch.alter_column('network_id', existing_type=sa.Integer(), nullable=True)
        batch.alter_column('created_by_id', existing_type=sa.Integer(), nullable=True)
        batch.alter_column('request_key', existing_type=sa.String(36), nullable=True)
        batch.alter_column('network_snapshot', existing_type=sa.JSON(), nullable=True)
        batch.add_column(sa.Column('source', sa.String(16), nullable=False, server_default='customer'))
        batch.add_column(sa.Column('criticality', sa.String(8), nullable=False, server_default='media'))
        batch.add_column(sa.Column('needs_review', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('incident_key', sa.String(255)))
        batch.add_column(sa.Column('incident_type', sa.String(40)))
        batch.add_column(sa.Column('alert_id', sa.Integer()))
        batch.add_column(sa.Column('device_id', sa.Integer()))
        batch.add_column(sa.Column('device_name', sa.String(255)))
        batch.add_column(sa.Column('evidence', sa.JSON()))
        batch.add_column(sa.Column('assignee_id', sa.Integer()))
        batch.add_column(sa.Column('resolution', sa.String(1000)))
        batch.add_column(sa.Column('attention_due_at', _when))
        batch.add_column(sa.Column('escalations', sa.Integer(), nullable=False, server_default='0'))
        batch.create_foreign_key('fk_tickets_alert', 'monitoring_alerts', ['alert_id'], ['id'], ondelete='SET NULL')
        batch.create_foreign_key('fk_tickets_device', 'monitoring_devices', ['device_id'], ['id'], ondelete='SET NULL')
        batch.create_foreign_key('fk_tickets_assignee', 'users', ['assignee_id'], ['id'])
        batch.create_check_constraint('ck_ticket_criticality', "criticality IN ('baja', 'media', 'alta', 'critica')")
    op.create_index('ix_tickets_criticality', 'tickets', ['criticality'])
    op.create_index('ix_tickets_assignee_id', 'tickets', ['assignee_id'])
    op.create_index('ix_tickets_attention_due_at', 'tickets', ['attention_due_at'])
    op.create_index('uq_ticket_active_incident', 'tickets', ['incident_key'], unique=True,
                    sqlite_where=sa.text("status <> 'closed'"), postgresql_where=sa.text("status <> 'closed'"))
    with op.batch_alter_table('ticket_events') as batch:
        batch.alter_column('actor_id', existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column('kind', sa.String(16), nullable=False, server_default='status'))

    op.create_table('notifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('channel', sa.String(8), nullable=False),
        sa.Column('event', sa.String(16), nullable=False),
        sa.Column('criticality', sa.String(8), nullable=False),
        sa.Column('highlighted', sa.Boolean(), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('link', sa.String(500), nullable=False),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', _when),
        sa.Column('last_error', sa.String(80)),
        sa.Column('created_at', _when, server_default=sa.func.now(), nullable=False),
        sa.Column('sent_at', _when),
        sa.Column('read_at', _when),
        sa.CheckConstraint("channel IN ('in_app', 'email')", name='ck_notification_channel'),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed', 'cancelled')", name='ck_notification_status'))
    for column in ('ticket_id', 'user_id', 'status'):
        op.create_index(f'ix_notifications_{column}', 'notifications', [column])


def downgrade():
    op.drop_table('notifications')
    with op.batch_alter_table('ticket_events') as batch:
        batch.drop_column('kind')
    # Los tickets de infraestructura no caben en el esquema anterior.
    op.execute("DELETE FROM ticket_events WHERE actor_id IS NULL")
    op.execute("DELETE FROM ticket_events WHERE ticket_id IN (SELECT id FROM tickets WHERE network_id IS NULL OR created_by_id IS NULL)")
    op.execute("DELETE FROM tickets WHERE network_id IS NULL OR created_by_id IS NULL")
    with op.batch_alter_table('ticket_events') as batch:
        batch.alter_column('actor_id', existing_type=sa.Integer(), nullable=False)
    for name in ('uq_ticket_active_incident', 'ix_tickets_attention_due_at', 'ix_tickets_assignee_id', 'ix_tickets_criticality'):
        op.drop_index(name, table_name='tickets')
    with op.batch_alter_table('tickets') as batch:
        batch.drop_constraint('ck_ticket_criticality', type_='check')
        batch.drop_constraint('fk_tickets_assignee', type_='foreignkey')
        batch.drop_constraint('fk_tickets_device', type_='foreignkey')
        batch.drop_constraint('fk_tickets_alert', type_='foreignkey')
        for column in ('escalations', 'attention_due_at', 'resolution', 'assignee_id', 'evidence', 'device_name',
                       'device_id', 'alert_id', 'incident_type', 'incident_key', 'needs_review', 'criticality', 'source'):
            batch.drop_column(column)
        batch.alter_column('network_snapshot', existing_type=sa.JSON(), nullable=False)
        batch.alter_column('request_key', existing_type=sa.String(36), nullable=False)
        batch.alter_column('created_by_id', existing_type=sa.Integer(), nullable=False)
        batch.alter_column('network_id', existing_type=sa.Integer(), nullable=False)
