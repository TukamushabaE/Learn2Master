"""Capture assessment start, completion, and elapsed time for research analysis.

Revision ID: 20260714_assessment_timing
Revises: 20260711_pg_schema
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op


revision = "20260714_assessment_timing"
down_revision = "20260711_pg_schema"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("assessment_attempts") as batch_op:
        batch_op.add_column(sa.Column("started_at", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("time_spent_seconds", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("assessment_attempts") as batch_op:
        batch_op.drop_column("time_spent_seconds")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("started_at")
