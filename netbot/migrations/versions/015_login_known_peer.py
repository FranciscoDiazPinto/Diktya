"""Origen conocido de cada cuenta: el bloqueo no debe dejar fuera a su titular."""
from alembic import op
import sqlalchemy as sa

revision = '015_login_known_peer'
down_revision = '014_h10_shared_wifi_lease'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('last_login_peer', sa.String(64)))


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('last_login_peer')
