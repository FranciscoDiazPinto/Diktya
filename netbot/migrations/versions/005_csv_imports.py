"""Vistas previas privadas e historial de reservas CSV confirmadas."""
from alembic import op
import sqlalchemy as sa

revision = "005_csv_imports"
down_revision = "004_customer_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "csv_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_context", sa.String(64), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('preview', 'confirmed', 'cancelled')", name="ck_csv_import_status"),
    )
    op.create_index("ix_csv_imports_owner_id", "csv_imports", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_csv_imports_owner_id", table_name="csv_imports")
    op.drop_table("csv_imports")
