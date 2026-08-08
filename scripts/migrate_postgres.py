"""Copy the complete Learn2Master PostgreSQL database to a new PostgreSQL host.

Credentials are supplied only through environment variables.  The script does
not print connection strings or row contents.  Target replacement is explicit
and the final table counts are verified before the transaction is committed.
"""

import argparse
import os
import re
from urllib.parse import urlparse
from urllib.parse import parse_qsl, urlencode, urlunparse

import psycopg2
from psycopg2 import extras, sql

from database import PostgresConnectionWrapper
from init_db import _table_name_from_create, run_postgres, schema_statements
from services.evaluation_dataset import ensure_evaluation_dataset_schema


def table_names(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema=current_schema() AND table_type='BASE TABLE'
            ORDER BY table_name
            """
        )
        return [row[0] for row in cur.fetchall()]


def columns(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name=%s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [row[0] for row in cur.fetchall()]


def count_rows(conn, table):
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
        return int(cur.fetchone()[0])


def schema_copy_order(common_tables):
    ordered = []
    for statement in schema_statements("postgres", reset=False):
        table = _table_name_from_create(statement)
        if table and table in common_tables and table not in ordered:
            ordered.append(table)
    for table in (
        "evaluation_reliability_records",
        "evaluation_qualitative_themes",
        "schema_migrations",
    ):
        if table in common_tables and table not in ordered:
            ordered.append(table)
    ordered.extend(sorted(common_tables - set(ordered)))
    return ordered


def url_with_search_path(url, schema):
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema}"
    return urlunparse(parsed._replace(query=urlencode(query)))


def reset_target_schema(target_url, target_schema):
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", target_schema):
        raise RuntimeError("Target schema name is invalid.")
    admin = psycopg2.connect(target_url)
    try:
        with admin.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(target_schema)
                )
            )
        admin.commit()
    finally:
        admin.close()

    schema_url = url_with_search_path(target_url, target_schema)
    run_postgres(schema_url, reset=True)
    raw = psycopg2.connect(schema_url)
    try:
        ensure_evaluation_dataset_schema(PostgresConnectionWrapper(raw))
    finally:
        raw.close()
    return schema_url


def copy_database(source_url, target_url, target_schema):
    source_host = urlparse(source_url).hostname
    target_host = urlparse(target_url).hostname
    if not source_host or not target_host or source_host == target_host:
        raise RuntimeError("Source and target database hosts must be different.")

    schema_url = reset_target_schema(target_url, target_schema)
    source = psycopg2.connect(source_url)
    target = psycopg2.connect(schema_url)
    source.set_session(readonly=True, isolation_level="REPEATABLE READ")
    target.autocommit = False
    try:
        source_tables = set(table_names(source))
        target_tables = set(table_names(target))
        common = source_tables & target_tables
        if "users" not in common or count_rows(source, "users") < 1:
            raise RuntimeError("Source validation failed: no Learn2Master users found.")

        order = schema_copy_order(common)
        truncate_targets = [table for table in order if table != "schema_migrations"]
        if truncate_targets:
            with target.cursor() as cur:
                cur.execute(
                    sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                        sql.SQL(", ").join(map(sql.Identifier, truncate_targets))
                    )
                )
        with target.cursor() as cur:
            cur.execute("TRUNCATE TABLE schema_migrations")

        copied = {}
        for table in order:
            source_columns = columns(source, table)
            target_columns = set(columns(target, table))
            shared_columns = [name for name in source_columns if name in target_columns]
            if not shared_columns:
                continue
            with source.cursor() as source_cur:
                source_cur.execute(
                    sql.SQL("SELECT {} FROM {}").format(
                        sql.SQL(", ").join(map(sql.Identifier, shared_columns)),
                        sql.Identifier(table),
                    )
                )
                rows = source_cur.fetchall()
            if rows:
                insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, shared_columns)),
                ).as_string(target)
                with target.cursor() as target_cur:
                    extras.execute_values(target_cur, insert_sql, rows, page_size=500)
            copied[table] = len(rows)

        with target.cursor() as cur:
            for table in order:
                cur.execute("SELECT pg_get_serial_sequence(%s, a.attname) "
                            "FROM pg_index i JOIN pg_attribute a "
                            "ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) "
                            "WHERE i.indrelid=%s::regclass AND i.indisprimary LIMIT 1",
                            (table, f"{target_schema}.{table}"))
                sequence = cur.fetchone()
                if not sequence or not sequence[0]:
                    continue
                pk_columns = columns(target, table)
                with target.cursor() as pk_cur:
                    pk_cur.execute(
                        """
                        SELECT a.attname
                        FROM pg_index i
                        JOIN pg_attribute a
                          ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
                        WHERE i.indrelid=%s::regclass AND i.indisprimary
                        ORDER BY a.attnum LIMIT 1
                        """,
                        (f"{target_schema}.{table}",),
                    )
                    pk_row = pk_cur.fetchone()
                if not pk_row:
                    continue
                cur.execute(
                    sql.SQL("SELECT MAX({}) FROM {}").format(
                        sql.Identifier(pk_row[0]), sql.Identifier(table)
                    )
                )
                maximum = cur.fetchone()[0]
                cur.execute(
                    "SELECT setval(%s, %s, %s)",
                    (sequence[0], maximum or 1, bool(maximum)),
                )

        mismatches = []
        for table, source_count in copied.items():
            target_count = count_rows(target, table)
            if target_count != source_count:
                mismatches.append((table, source_count, target_count))
        if mismatches:
            raise RuntimeError(f"Target count verification failed for {len(mismatches)} table(s).")
        target.commit()
        return {
            "tables": len(copied),
            "rows": sum(copied.values()),
            "users": copied.get("users", 0),
            "evaluation_records": copied.get("evaluation_dataset_records", 0),
            "evaluation_accounts": copied.get("evaluation_account_links", 0),
            "target_schema": target_schema,
        }
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-schema", default="learn2master_prod")
    args = parser.parse_args()
    source_url = os.environ.get("SOURCE_DATABASE_URL")
    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not source_url or not target_url:
        raise SystemExit("SOURCE_DATABASE_URL and TARGET_DATABASE_URL are required.")
    result = copy_database(source_url, target_url, args.target_schema)
    print(
        "Migration verified: "
        f"{result['tables']} tables, {result['rows']} rows, {result['users']} users, "
        f"{result['evaluation_records']} evaluation records and "
        f"{result['evaluation_accounts']} linked evaluation accounts in "
        f"schema {result['target_schema']}."
    )


if __name__ == "__main__":
    main()
