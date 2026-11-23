"""Bind a VLAN change to its confirmed reservation."""
from alembic import op
import sqlalchemy as sa

revision = '023_vlan_change_reservation'
down_revision = '022_google_login'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ssid_vlan_change_plans') as batch:
        batch.add_column(sa.Column('reservation_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_ssid_vlan_change_reservation', 'vlan_reservations',
            ['reservation_id'], ['id'],
        )


def downgrade():
    with op.batch_alter_table('ssid_vlan_change_plans') as batch:
        batch.drop_constraint('fk_ssid_vlan_change_reservation', type_='foreignkey')
        batch.drop_column('reservation_id')
