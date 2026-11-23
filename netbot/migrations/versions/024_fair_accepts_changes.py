"""Persist the closure gate of each fair scope."""
from alembic import op
import sqlalchemy as sa

revision = '024_fair_accepts_changes'
down_revision = '023_vlan_change_reservation'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('wifi_scopes', sa.Column(
        'accepts_changes', sa.Boolean(), nullable=False, server_default=sa.true(),
    ))


def downgrade():
    scopes = sa.table('wifi_scopes', sa.column('accepts_changes', sa.Boolean()))
    if op.get_bind().scalar(sa.select(sa.literal(1)).select_from(scopes).where(
        scopes.c.accepts_changes.is_(False),
    ).limit(1)):
        raise RuntimeError('El downgrade reabriría un ámbito de feria cerrado.')
    op.drop_column('wifi_scopes', 'accepts_changes')
