"""Add agent-knowledge link table

Revision ID: b9c8d7e6f5a4
Revises: c2a1f0d7b6e8
Create Date: 2025-11-19 19:35:00

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = 'b9c8d7e6f5a4'
down_revision = 'c2a1f0d7b6e8'
branch_labels = None
depends_on = None


def upgrade():
    # Create M2M link table between agent and knowledge
    op.create_table(
        'agentknowledgelink',
        sa.Column('agent_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('knowledge_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agent.id']),
        sa.ForeignKeyConstraint(['knowledge_id'], ['knowledge.id']),
        sa.PrimaryKeyConstraint('agent_id', 'knowledge_id')
    )


def downgrade():
    op.drop_table('agentknowledgelink')
