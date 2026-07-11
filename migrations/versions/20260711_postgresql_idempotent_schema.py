"""Idempotent current Learn2Master schema for SQLite and PostgreSQL.

Revision ID: 20260711_pg_schema
Revises: 609ccac433d4
Create Date: 2026-07-11
"""

from alembic import op

from init_db import schema_statements


revision = "20260711_pg_schema"
down_revision = "609ccac433d4"
branch_labels = None
depends_on = None


def upgrade():
    dialect_name = op.get_bind().dialect.name
    dialect = "postgres" if dialect_name.startswith("postgresql") else "sqlite"
    for statement in schema_statements(dialect, reset=False):
        op.execute(statement)


def downgrade():
    # Non-destructive by design. Use `python init_db.py --reset` only on local/dev databases.
    pass
