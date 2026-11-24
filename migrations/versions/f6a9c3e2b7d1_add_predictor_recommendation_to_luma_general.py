"""add predictor_recommendation to luma_general

Revision ID: f6a9c3e2b7d1
Revises: f1a7c3d9e2b4
Create Date: 2026-11-23

Nullable JSONB column holding the last predictor optimizer result of a
session (GET /luma/predictor/optimize). NULL = the optimizer has not run.
Downgrade drops it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'f6a9c3e2b7d1'
down_revision = 'f1a7c3d9e2b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('luma_general', schema=None) as batch_op:
        batch_op.add_column(sa.Column('predictor_recommendation', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade():
    with op.batch_alter_table('luma_general', schema=None) as batch_op:
        batch_op.drop_column('predictor_recommendation')
