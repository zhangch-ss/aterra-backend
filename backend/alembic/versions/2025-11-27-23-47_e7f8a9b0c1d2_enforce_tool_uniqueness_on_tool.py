"""Enforce tool uniqueness by user and for builtin (user_id IS NULL)

Revision ID: e7f8a9b0c1d2
Revises: d4e5f6a7b8c9
Create Date: 2025-11-27 23:47:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e7f8a9b0c1d2"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    # 1) 清理内置工具（user_id IS NULL）的重复：按 (module,function) 保留最早一条
    op.execute(
        """
        WITH d AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY module, function
                       ORDER BY created_at
                   ) AS rn
            FROM "tool"
            WHERE user_id IS NULL
              AND module IS NOT NULL
              AND function IS NOT NULL
        )
        DELETE FROM "tool" t
        USING d
        WHERE t.id = d.id AND d.rn > 1;
        """
    )

    # 2) 清理用户工具（user_id IS NOT NULL）的重复：按 (module,function,user_id) 保留最早一条
    op.execute(
        """
        WITH d AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY module, function, user_id
                       ORDER BY created_at
                   ) AS rn
            FROM "tool"
            WHERE user_id IS NOT NULL
              AND module IS NOT NULL
              AND function IS NOT NULL
        )
        DELETE FROM "tool" t
        USING d
        WHERE t.id = d.id AND d.rn > 1;
        """
    )

    # 3) 创建唯一索引
    # 3.1 针对内置工具（user_id IS NULL）强制 (module,function) 唯一（部分唯一索引）
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_module_function_builtin ON "tool"(module, function) WHERE user_id IS NULL;'
    )

    # 3.2 针对用户工具强制 (module,function,user_id) 唯一（允许 user_id 为 NULL 的行不受此条约束影响）
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_module_function_user ON "tool"(module, function, user_id);'
    )


def downgrade():
    # 仅回滚索引；已删除的数据不可恢复
    op.execute('DROP INDEX IF EXISTS uq_tool_module_function_user;')
    op.execute('DROP INDEX IF EXISTS uq_tool_module_function_builtin;')
