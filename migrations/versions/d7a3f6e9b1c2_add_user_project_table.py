"""add user_project table

Revision ID: d7a3f6e9b1c2
Revises: c4e8b2d1a9f0
Create Date: 2026-09-20

Named, server-persisted projects. `checkpoint` holds the frontend's
SessionCheckpoint as an opaque JSONB blob. Downgrade drops the table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'd7a3f6e9b1c2'
down_revision = 'c4e8b2d1a9f0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user_project',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('account_id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('checkpoint', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('shared_from', sa.String(length=36), nullable=True),
    sa.Column('created_date', sa.DateTime(), nullable=True),
    sa.Column('modified_date', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['user_account.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['user_session.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('user_project', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_project_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_project_session_id'), ['session_id'], unique=False)


def downgrade():
    with op.batch_alter_table('user_project', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_project_session_id'))
        batch_op.drop_index(batch_op.f('ix_user_project_account_id'))

    op.drop_table('user_project')