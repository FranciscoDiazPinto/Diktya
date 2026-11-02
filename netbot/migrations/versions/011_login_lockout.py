"""Bloqueo persistente de login tras cinco intentos fallidos."""
from alembic import op
import sqlalchemy as sa

revision = '011_login_lockout'
down_revision = '010_merge_monitoring_tickets'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('login_locked_until', sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column('users', 'login_locked_until')
    op.drop_column('users', 'failed_login_attempts')
