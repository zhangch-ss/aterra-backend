"""Add text_splitter table

Revision ID: f3c2a1b4add8
Revises: e3b1c2d4add9
Create Date: 2025-11-25 18:51:00

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = "f3c2a1b4add8"
down_revision = "e3b1c2d4add9"
branch_labels = None
depends_on = None


def upgrade():
    # Create TextSplitter table based on app.models.text_splitter.TextSplitter (BaseTable + fields)
    op.create_table(
        "text_splitter",
        # BaseTable mixin columns
        sa.Column("created_by_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("updated_by_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        # TextSplitter specific columns
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column("separators", sa.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_text_splitter_user_name"),
    )
    # Indexes
    op.create_index(op.f("ix_text_splitter_id"), "text_splitter", ["id"], unique=False)
    op.create_index(op.f("ix_text_splitter_user_id"), "text_splitter", ["user_id"], unique=False)
    op.create_index(op.f("ix_text_splitter_name"), "text_splitter", ["name"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_text_splitter_name"), table_name="text_splitter")
    op.drop_index(op.f("ix_text_splitter_user_id"), table_name="text_splitter")
    op.drop_index(op.f("ix_text_splitter_id"), table_name="text_splitter")
    op.drop_table("text_splitter")
