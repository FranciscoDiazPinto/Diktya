"""Vinculación explícita de AP UniFi a redes de soporte autorizadas."""
from alembic import op
import sqlalchemy as sa

revision = '009_network_monitoring_scope'
down_revision = '008_auth_audit'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('network_support_config',sa.Column('unifi_site_id',sa.String(160)))
    op.add_column('network_support_config',sa.Column('unifi_ap_ids',sa.JSON(),nullable=False,server_default='[]'))


def downgrade():
    with op.batch_alter_table('network_support_config') as batch:
        batch.drop_column('unifi_ap_ids')
        batch.drop_column('unifi_site_id')
