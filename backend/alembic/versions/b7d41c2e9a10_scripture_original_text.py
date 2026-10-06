"""scripture original text

Revision ID: b7d41c2e9a10
Revises: fac4209f92c2
Create Date: 2026-10-06 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b7d41c2e9a10'
down_revision = 'fac4209f92c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scriptures', sa.Column('original_text', sa.Text(), nullable=True))
    op.add_column('scriptures', sa.Column('original_source', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('scriptures', 'original_source')
    op.drop_column('scriptures', 'original_text')
