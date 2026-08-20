"""add regency_code to geos_aoi

Revision ID: b3f9a1c7d2e4
Revises: 5204748f5e4c
Create Date: 2026-08-17

Nullable column; safe to apply on live data. Downgrade drops it.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3f9a1c7d2e4'
down_revision = '5204748f5e4c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('geos_aoi', schema=None) as batch_op:
        batch_op.add_column(sa.Column('regency_code', sa.String(length=16), nullable=True))


def downgrade():
    with op.batch_alter_table('geos_aoi', schema=None) as batch_op:
        batch_op.drop_column('regency_code')
