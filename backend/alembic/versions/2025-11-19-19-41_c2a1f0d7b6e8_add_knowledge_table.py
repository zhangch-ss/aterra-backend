"""Add knowledge table

Revision ID: c2a1f0d7b6e8
Revises: a4678f9d1234
Create Date: 2025-11-19 19:41:00

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = 'c2a1f0d7b6e8'
down_revision = 'a4678f9d1234'
branch_labels = None
depends_on = None


def upgrade():
    # Create Knowledge table based on app.models.knowledge.Knowledge (BaseTable + fields)
    op.create_table(
        'knowledge',
        sa.Column('created_by_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('updated_by_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['updated_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_id'), 'knowledge', ['id'], unique=False)
    op.create_index(op.f('ix_knowledge_name'), 'knowledge', ['name'], unique=False)
    op.create_index(op.f('ix_knowledge_user_id'), 'knowledge', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_knowledge_user_id'), table_name='knowledge')
    op.drop_index(op.f('ix_knowledge_name'), table_name='knowledge')
    op.drop_index(op.f('ix_knowledge_id'), table_name='knowledge')
    op.drop_table('knowledge')
