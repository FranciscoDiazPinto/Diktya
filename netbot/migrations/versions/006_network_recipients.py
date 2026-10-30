"""Contactos destinatarios de credenciales, independientes de cuentas."""
from alembic import op
import sqlalchemy as sa

revision = '006_network_recipients'
down_revision = '005_csv_imports'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('network_recipients',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('network_id', sa.Integer(), sa.ForeignKey('networks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(320)),
        sa.Column('phone', sa.String(16)))
    for column in ('network_id', 'email', 'phone'):
        op.create_index(f'ix_network_recipients_{column}', 'network_recipients', [column])


def downgrade():
    op.drop_table('network_recipients')
