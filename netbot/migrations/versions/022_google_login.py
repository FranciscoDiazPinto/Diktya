"""Google Workspace identities and single-use browser login challenges."""
from alembic import op
import sqlalchemy as sa

revision = '022_google_login'
down_revision = '021_execution_ownership'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('google_identities',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('subject', sa.String(255), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('google_login_challenges',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('nonce_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_google_login_challenges_expires_at', 'google_login_challenges', ['expires_at'])


def downgrade():
    # Never remove stable identity bindings silently: that would permit rebinding
    # an old local account to a different Google subject with a recycled email.
    identities = sa.table('google_identities', sa.column('user_id'))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(identities)):
        raise RuntimeError('Existen identidades Google vinculadas; no se puede retirar su protección.')
    op.drop_index('ix_google_login_challenges_expires_at', table_name='google_login_challenges')
    op.drop_table('google_login_challenges')
    op.drop_table('google_identities')
