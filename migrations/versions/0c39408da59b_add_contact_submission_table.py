"""add contact_submission table

Revision ID: 0c39408da59b
Revises: b4289b175e3c
Create Date: 2026-05-01 14:50:53.671016

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0c39408da59b'
down_revision = 'b4289b175e3c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('contact_submission',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('full_name', sa.String(length=256), nullable=False),
    sa.Column('email', sa.String(length=256), nullable=False),
    sa.Column('phone_number', sa.String(length=50), nullable=True),
    sa.Column('company_name', sa.String(length=256), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_date', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('contact_submission')
