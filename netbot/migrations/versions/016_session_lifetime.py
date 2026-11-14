"""Inicio real de cada sesión: la rotación no debe extenderla sin límite."""
from alembic import op
import sqlalchemy as sa

revision = '016_session_lifetime'
down_revision = '015_login_known_peer'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('refresh_tokens', sa.Column('session_started_at', sa.DateTime(timezone=True)))
    op.execute('UPDATE refresh_tokens SET session_started_at = created_at')


def downgrade():
    with op.batch_alter_table('refresh_tokens') as batch:
        batch.drop_column('session_started_at')
