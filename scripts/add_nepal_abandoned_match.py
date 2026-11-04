#!/usr/bin/env python3
"""Safely add the abandoned Nepal-Oman League 2 match record."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "nepal_cricket.db"

MATCH_COLUMNS = (
    "match_id",
    "match_date",
    "match_format",
    "team_1_name",
    "team_2_name",
    "winner_name",
    "venue_name",
    "city",
    "margin",
    "margin_type",
    "toss_winner_name",
    "toss_decision",
    "tournament_name",
    "season",
    "gender",
    "player_of_match",
    "umpire_1_name",
    "umpire_2_name",
    "match_referee_name",
    "tournament_id",
)

MATCH_RECORD = (
    "1450700",
    "2024-09-24",
    "ODI",
    "Nepal",
    "Oman",
    None,
    "King City (NW)",
    "King City",
    None,
    None,
    None,
    None,
    "ICC Men's Cricket World Cup League 2",
    "2024/25",
    "male",
    None,
    None,
    None,
    None,
    1760,
)


def add_match_record(database_path: Path = DEFAULT_DATABASE) -> bool:
    """Insert the match row once; return False when the exact row already exists."""
    database_path = Path(database_path)
    connection = sqlite3.connect(database_path, timeout=30)
    columns = ", ".join(f'"{column}"' for column in MATCH_COLUMNS)
    placeholders = ", ".join("?" for _ in MATCH_COLUMNS)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing_rows = connection.execute(
            f'SELECT {columns} FROM "nepal_matches" WHERE "match_id" = ?',
            (MATCH_RECORD[0],),
        ).fetchall()
        if existing_rows:
            if len(existing_rows) != 1 or tuple(existing_rows[0]) != MATCH_RECORD:
                raise ValueError(
                    f"Match ID {MATCH_RECORD[0]} exists with conflicting data"
                )
            connection.commit()
            return False

        connection.execute(
            f'INSERT INTO "nepal_matches" ({columns}) VALUES ({placeholders})',
            MATCH_RECORD,
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"SQLite database path (default: {DEFAULT_DATABASE})",
    )
    args = parser.parse_args()
    inserted = add_match_record(args.database)
    print(
        f"Match {MATCH_RECORD[0]} "
        + ("inserted." if inserted else "already present; no changes made.")
    )


if __name__ == "__main__":
    main()
