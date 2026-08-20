"""add split_ratio to luma_general

Revision ID: c4e8b2d1a9f0
Revises: b3f9a1c7d2e4
Create Date: 2026-08-17

Nullable column; NULL keeps the previous hardcoded 0.7 train ratio.
Downgrade drops it.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4e8b2d1a9f0'
down_revision = 'b3f9a1c7d2e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('luma_general', schema=None) as batch_op:
        batch_op.add_column(sa.Column('split_ratio', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('luma_general', schema=None) as batch_op:
        batch_op.drop_column('split_ratio')
