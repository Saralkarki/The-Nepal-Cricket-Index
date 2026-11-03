#!/usr/bin/env python3
"""Import Nepal national-team Parquet datasets into the shared SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "data" / "nepal"
DEFAULT_DATABASE = ROOT / "data" / "nepal_cricket.db"

SOURCE_FILES = {
    "nepal_matches": "nepal_match_summary.parquet",
    "nepal_innings_summary": "nepal_innings_summary.parquet",
    "nepal_batting_scorecards": "nepal_batting_scorecards.parquet",
    "nepal_batting_stats_by_tournament": "nepal_batting_stats_by_tournament.parquet",
    "nepal_batting_stats_overall": "nepal_batting_stats_overall.parquet",
    "nepal_bowling_scorecards": "nepal_bowling_scorecards.parquet",
    "nepal_bowling_stats_by_tournament": "nepal_bowling_stats_by_tournament.parquet",
    "nepal_bowling_stats_overall": "nepal_bowling_stats_overall.parquet",
    "nepal_players": "dim_nepal_players.parquet",
    "nepal_tournament_players": "bridge_nepal_tournament_players.parquet",
}

SQLITE_TYPES = {
    "BIGINT": "INTEGER",
    "BOOLEAN": "INTEGER",
    "DOUBLE": "REAL",
    "FLOAT": "REAL",
    "VARCHAR": "TEXT",
}


@dataclass(frozen=True)
class SourceTable:
    columns: tuple[tuple[str, str], ...]
    rows: tuple[tuple[Any, ...], ...]


class ImportValidationError(ValueError):
    """Raised when source Parquet files cannot be imported safely."""


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlite_type(parquet_type: str, table: str, column: str) -> str:
    try:
        return SQLITE_TYPES[parquet_type.upper()]
    except KeyError as exc:
        raise ImportValidationError(
            f"Unsupported type {parquet_type!r} for {table}.{column}"
        ) from exc


def read_source_data(source_dir: Path) -> dict[str, SourceTable]:
    missing = [
        filename
        for filename in SOURCE_FILES.values()
        if not (source_dir / filename).is_file()
    ]
    if missing:
        raise ImportValidationError(
            f"Missing required Parquet file(s) in {source_dir}: {', '.join(missing)}"
        )

    connection = duckdb.connect()
    try:
        data = {}
        for table, filename in SOURCE_FILES.items():
            path = (source_dir / filename).resolve()
            description = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
            columns = tuple(
                (
                    column_name,
                    _sqlite_type(column_type, table, column_name),
                )
                for column_name, column_type, *_ in description
            )
            if not columns or len({name for name, _ in columns}) != len(columns):
                raise ImportValidationError(
                    f"Invalid or duplicate column names in {filename}"
                )
            rows = tuple(
                connection.execute(
                    "SELECT * FROM read_parquet(?)", [str(path)]
                ).fetchall()
            )
            data[table] = SourceTable(columns=columns, rows=rows)
        return data
    finally:
        connection.close()


def import_nepal_data(
    database_path: Path, source_dir: Path = DEFAULT_SOURCE_DIR
) -> dict[str, int]:
    data = read_source_data(source_dir)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table in SOURCE_FILES:
            connection.execute(f"DROP TABLE IF EXISTS {quote_identifier(table)}")

        row_counts = {}
        for table, source in data.items():
            columns_sql = ", ".join(
                f"{quote_identifier(name)} {column_type}"
                for name, column_type in source.columns
            )
            connection.execute(
                f"CREATE TABLE {quote_identifier(table)} ({columns_sql})"
            )
            if source.rows:
                placeholders = ", ".join("?" for _ in source.columns)
                connection.executemany(
                    f"INSERT INTO {quote_identifier(table)} VALUES ({placeholders})",
                    source.rows,
                )
            row_counts[table] = len(source.rows)

        connection.commit()
        return row_counts
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"Directory containing the Parquet files (default: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"SQLite database output path (default: {DEFAULT_DATABASE})",
    )
    args = parser.parse_args()

    try:
        row_counts = import_nepal_data(
            args.database.resolve(), args.source_dir.resolve()
        )
    except (duckdb.Error, sqlite3.Error, ImportValidationError, OSError) as exc:
        print(f"Nepal import failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "database": str(args.database.resolve()),
                "row_counts": row_counts,
                "total_rows": sum(row_counts.values()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
