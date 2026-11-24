"""add luma_report_data table

Revision ID: f1a7c3d9e2b4
Revises: e5b8c2a4f1d3
Create Date: 2026-11-11

What the map report needs from a run, one row per session: `generation` is the
snapshot written when the map is generated, `thematic` the latest thematic
accuracy test. Downgrade drops the table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'f1a7c3d9e2b4'
down_revision = 'e5b8c2a4f1d3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('luma_report_data',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('generation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('thematic', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_date', sa.DateTime(), nullable=True),
    sa.Column('modified_date', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['user_session.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('luma_report_data', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_luma_report_data_session_id'), ['session_id'], unique=False)


def downgrade():
    with op.batch_alter_table('luma_report_data', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_luma_report_data_session_id'))

    op.drop_table('luma_report_data')
