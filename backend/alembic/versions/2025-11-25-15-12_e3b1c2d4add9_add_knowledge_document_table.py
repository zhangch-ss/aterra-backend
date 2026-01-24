"""Add knowledge_document table

Revision ID: e3b1c2d4add9
Revises: b9c8d7e6f5a4
Create Date: 2025-11-25 15:12:00

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = "e3b1c2d4add9"
down_revision = "b9c8d7e6f5a4"
branch_labels = None
depends_on = None


def upgrade():
    # Create KnowledgeDocument table based on app.models.knowledge_document.KnowledgeDocument (BaseTable + fields)
    op.create_table(
        "knowledge_document",
        # BaseTable mixin columns
        sa.Column("created_by_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("updated_by_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        # Ownership
        sa.Column("knowledge_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        # File metadata
        sa.Column("filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bucket", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("object_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("content_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        # Index and embedding params
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("embed_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("embed_model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        # Index results and error info
        sa.Column("vector_ids", sa.JSON(), nullable=True),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        # FKs
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["knowledge_id"], ["knowledge.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Indexes
    op.create_index(op.f("ix_knowledge_document_id"), "knowledge_document", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_document_knowledge_id"), "knowledge_document", ["knowledge_id"], unique=False)
    op.create_index(op.f("ix_knowledge_document_user_id"), "knowledge_document", ["user_id"], unique=False)
    op.create_index(op.f("ix_knowledge_document_status"), "knowledge_document", ["status"], unique=False)
    op.create_index(op.f("ix_knowledge_document_object_name"), "knowledge_document", ["object_name"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_knowledge_document_object_name"), table_name="knowledge_document")
    op.drop_index(op.f("ix_knowledge_document_status"), table_name="knowledge_document")
    op.drop_index(op.f("ix_knowledge_document_user_id"), table_name="knowledge_document")
    op.drop_index(op.f("ix_knowledge_document_knowledge_id"), table_name="knowledge_document")
    op.drop_index(op.f("ix_knowledge_document_id"), table_name="knowledge_document")
    op.drop_table("knowledge_document")
