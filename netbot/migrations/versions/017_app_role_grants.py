"""PostgreSQL: el rol de la API no altera auditoría ni el historial de migraciones."""
from alembic import op

revision = '017_app_role_grants'
down_revision = '016_session_lifetime'
branch_labels = None
depends_on = None


def _grants(statement):
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'netbot_app') THEN "
                   + statement + " END IF; END $$")


def upgrade():
    _grants("REVOKE UPDATE, DELETE, TRUNCATE ON auth_audit_events, support_audit, ticket_events FROM netbot_app; "
            "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM netbot_app;")


def downgrade():
    _grants("GRANT UPDATE, DELETE ON auth_audit_events, support_audit, ticket_events TO netbot_app; "
            "GRANT INSERT, UPDATE, DELETE ON alembic_version TO netbot_app;")
