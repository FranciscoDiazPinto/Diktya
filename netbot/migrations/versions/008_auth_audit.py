"""Auditoría de identidad append-only y retención de usuarios auditados."""
from alembic import op
import sqlalchemy as sa

revision = '008_auth_audit'
down_revision = '007_ssid_plans'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_audit_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT')),
        sa.Column('target_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT')),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('source', sa.String(16), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for column in ('actor_id', 'target_id', 'action'):
        op.create_index(f'ix_auth_audit_events_{column}', 'auth_audit_events', [column])
    dialect = op.get_bind().dialect.name
    if dialect == 'sqlite':
        for action in ('UPDATE', 'DELETE'):
            op.execute(f"CREATE TRIGGER auth_audit_no_{action.lower()} BEFORE {action} ON auth_audit_events "
                       "BEGIN SELECT RAISE(ABORT, 'auth audit is append only'); END")
        op.execute("CREATE TRIGGER auth_users_no_audited_delete BEFORE DELETE ON users "
                   "WHEN EXISTS (SELECT 1 FROM auth_audit_events WHERE actor_id=OLD.id OR target_id=OLD.id) "
                   "BEGIN SELECT RAISE(ABORT, 'audited users cannot be deleted'); END")
    elif dialect == 'postgresql':
        op.execute("CREATE FUNCTION netbot_auth_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ "
                   "BEGIN RAISE EXCEPTION 'auth audit is append only'; END; $$")
        op.execute("CREATE TRIGGER auth_audit_immutable BEFORE UPDATE OR DELETE ON auth_audit_events "
                   "FOR EACH ROW EXECUTE FUNCTION netbot_auth_audit_immutable()")


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == 'sqlite':
        op.execute('DROP TRIGGER auth_users_no_audited_delete')
    op.drop_table('auth_audit_events')
    if dialect == 'postgresql':
        op.execute('DROP FUNCTION netbot_auth_audit_immutable()')
