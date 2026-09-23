"""add invite and login code columns to user_account

Revision ID: e5b8c2a4f1d3
Revises: d7a3f6e9b1c2
Create Date: 2026-09-21

invited_by marks accounts created by a project share; login_code is the
one-time code exchanged for an api_key after set-password. All nullable.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5b8c2a4f1d3'
down_revision = 'd7a3f6e9b1c2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_account', schema=None) as batch_op:
        batch_op.add_column(sa.Column('invited_by', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('login_code', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('login_code_expires', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_user_account_invited_by'), ['invited_by'], unique=False)
        batch_op.create_unique_constraint('uq_user_account_login_code', ['login_code'])


def downgrade():
    with op.batch_alter_table('user_account', schema=None) as batch_op:
        batch_op.drop_constraint('uq_user_account_login_code', type_='unique')
        batch_op.drop_index(batch_op.f('ix_user_account_invited_by'))
        batch_op.drop_column('login_code_expires')
        batch_op.drop_column('login_code')
        batch_op.drop_column('invited_by')
