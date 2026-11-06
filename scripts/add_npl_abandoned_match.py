#!/usr/bin/env python3
"""Safely add the abandoned NPL 2026/27 match (1558588) to the matches table."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "nepal_cricket.db"

MATCH_COLUMNS = (
    "match_id",
    "match_date",
    "stage",
    "stage_order",
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
    "gender",
    "umpire_1_name",
    "umpire_2_name",
    "match_referee_name",
    "tournament_id",
)

MATCH_RECORD = (
    "1558588",
    "2026-10-31",
    "League Stage",
    1,
    "T20",
    "Chitwan Rhinos",
    "Lumbini Lions",
    None,
    "Tribhuvan University International Cricket Ground, Kirtipur",
    "Kirtipur",
    None,
    None,
    None,
    None,
    "male",
    None,
    None,
    None,
    2184,
)


def add_match_record(database_path: Path = DEFAULT_DATABASE) -> bool:
    """Insert the match row once; return False when the exact row already exists."""
    connection = sqlite3.connect(Path(database_path), timeout=30)
    columns = ", ".join(f'"{column}"' for column in MATCH_COLUMNS)
    placeholders = ", ".join("?" for _ in MATCH_COLUMNS)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing_rows = connection.execute(
            f'SELECT {columns} FROM "matches" WHERE "match_id" = ?',
            (MATCH_RECORD[0],),
        ).fetchall()
        if existing_rows:
            if tuple(existing_rows[0]) != MATCH_RECORD:
                raise ValueError(
                    f"Match ID {MATCH_RECORD[0]} exists with conflicting data"
                )
            connection.commit()
            return False

        connection.execute(
            f'INSERT INTO "matches" ({columns}) VALUES ({placeholders})',
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
