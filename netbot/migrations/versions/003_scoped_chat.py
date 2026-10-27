"""Redes asignadas e historial privado de chat."""
from alembic import op
import sqlalchemy as sa

revision = "003_scoped_chat"
down_revision = "002_vlan_reservations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "networks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("site", sa.String(160), nullable=False),
        sa.Column("event_name", sa.String(160), nullable=False),
        sa.Column("external_id", sa.String(160), nullable=False),
        sa.Column("ssid", sa.String(64), nullable=False),
        sa.Column("vlan_tag", sa.Integer()),
        sa.UniqueConstraint("site", "external_id", name="uq_network_site_external"),
    )
    op.create_table(
        "network_assignments",
        sa.Column("network_id", sa.Integer(), sa.ForeignKey("networks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_network_assignments_user_id", "network_assignments", ["user_id"])
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("network_id", sa.Integer(), sa.ForeignKey("networks.id")),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("authorization_key", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_conversations_user_id", "chat_conversations", ["user_id"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
    # Idempotente también en bases cuyos roles se crearon durante el arranque.
    for name, description in [("cliente", "Atención de sus propias redes."), ("tecnico", "Técnico de redes asignadas.")]:
        op.execute(sa.text("INSERT INTO roles (name, description) SELECT :name, :description "
                           "WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = :name)")
                   .bindparams(name=name, description=description))


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_conversations_user_id", table_name="chat_conversations")
    op.drop_table("chat_conversations")
    op.drop_index("ix_network_assignments_user_id", table_name="network_assignments")
    op.drop_table("network_assignments")
    op.drop_table("networks")
    # Conservar roles y asignaciones de usuarios; un downgrade no elimina usuarios.
