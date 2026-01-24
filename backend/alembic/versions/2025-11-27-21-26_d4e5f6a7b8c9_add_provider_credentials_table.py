"""Add provider_credentials table

Revision ID: d4e5f6a7b8c9
Revises: a1b2c3d4e5f7
Create Date: 2025-11-27 21:26:00

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade():
    # Create ProviderCredentials table based on app.models.provider_credentials.ProviderCredentials (BaseTable + fields)
    op.create_table(
        "provider_credentials",
        sa.Column("created_by_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("updated_by_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),

        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),

        sa.Column("api_key_enc", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("base_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("organization", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("azure_endpoint", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("api_version", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("azure_deployment", sqlmodel.sql.sqltypes.AutoString(), nullable=True),

        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider", name="uq_provider_credentials_user_provider"),
    )

    # Indexes
    op.create_index(op.f("ix_provider_credentials_id"), "provider_credentials", ["id"], unique=False)
    op.create_index(op.f("ix_provider_credentials_user_id"), "provider_credentials", ["user_id"], unique=False)
    op.create_index(op.f("ix_provider_credentials_provider"), "provider_credentials", ["provider"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_provider_credentials_provider"), table_name="provider_credentials")
    op.drop_index(op.f("ix_provider_credentials_user_id"), table_name="provider_credentials")
    op.drop_index(op.f("ix_provider_credentials_id"), table_name="provider_credentials")
    op.drop_table("provider_credentials")
