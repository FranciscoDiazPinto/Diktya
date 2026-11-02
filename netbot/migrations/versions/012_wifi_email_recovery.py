"""Recuperación por correo de redes explícitas de expositores."""
from alembic import op
import sqlalchemy as sa

revision = '012_wifi_email_recovery'
down_revision = '011_login_lockout'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('network_support_config', sa.Column('guest_recovery_purpose', sa.String(24), nullable=False, server_default='disabled'))
    op.create_table('wifi_email_recoveries',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('email', sa.String(320), nullable=False),
        sa.Column('network_ids', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True)))
    op.create_index('ix_wifi_email_recoveries_expires_at', 'wifi_email_recoveries', ['expires_at'])


def downgrade():
    op.drop_table('wifi_email_recoveries')
    with op.batch_alter_table('network_support_config') as batch:
        batch.drop_column('guest_recovery_purpose')
