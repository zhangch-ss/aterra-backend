"""Add splitter_type and params to text_splitter table

Revision ID: a1b2c3d4e5f7
Revises: f3c2a1b4add8
Create Date: 2025-11-25 19:15:00

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f7"
down_revision = "f3c2a1b4add8"
branch_labels = None
depends_on = None


def upgrade():
    # 增加新列：splitter_type（非空，默认 recursive）与 params（JSON 可空）
    op.add_column(
        "text_splitter",
        sa.Column(
            "splitter_type",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=False,
            server_default="recursive",
        ),
    )
    op.add_column(
        "text_splitter",
        sa.Column(
            "params",
            sa.JSON(),
            nullable=True,
        ),
    )

    # 可选：移除 server_default 以匹配模型中的默认值行为（保留现有数据中的值）
    with op.batch_alter_table("text_splitter") as batch_op:
        batch_op.alter_column("splitter_type", server_default=None)


def downgrade():
    # 回滚：删除新增列
    op.drop_column("text_splitter", "params")
    op.drop_column("text_splitter", "splitter_type")
