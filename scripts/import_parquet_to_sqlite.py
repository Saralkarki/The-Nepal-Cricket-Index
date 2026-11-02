#!/usr/bin/env python3
"""Rebuild the dashboard SQLite database from the prepared NPL Parquet files."""

from __future__ import annotations

import argparse
import ast
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "data" / "npl"
DEFAULT_DATABASE = ROOT / "data" / "nepal_cricket.db"

SOURCE_SCHEMAS: dict[str, dict[str, str]] = {
    "matches": {
        "match_id": "VARCHAR",
        "match_date": "VARCHAR",
        "match_format": "VARCHAR",
        "team_1_name": "VARCHAR",
        "team_2_name": "VARCHAR",
        "winner_name": "VARCHAR",
        "venue_name": "VARCHAR",
        "city": "VARCHAR",
        "margin": "BIGINT",
        "margin_type": "VARCHAR",
        "toss_winner_name": "VARCHAR",
        "toss_decision": "VARCHAR",
        "tournament_name": "VARCHAR",
        "season": "VARCHAR",
        "gender": "VARCHAR",
        "player_of_match": "VARCHAR",
        "umpire_1_name": "VARCHAR",
        "umpire_2_name": "VARCHAR",
        "match_referee_name": "VARCHAR",
        "tournament_id": "BIGINT",
    },
    "innings_summary": {
        "match_id": "VARCHAR",
        "innings_number": "BIGINT",
        "gender": "VARCHAR",
        "batting_team": "VARCHAR",
        "total_runs": "DOUBLE",
        "total_wickets": "BIGINT",
        "legal_balls": "BIGINT",
        "overs": "VARCHAR",
    },
    "batting_scorecards": {
        "match_id": "VARCHAR",
        "innings_number": "BIGINT",
        "batting_position": "BIGINT",
        "batsman": "VARCHAR",
        "gender": "VARCHAR",
        "runs": "DOUBLE",
        "balls_faced": "BIGINT",
        "dot_balls": "BIGINT",
        "dot_ball_percentage": "DOUBLE",
        "fours": "BIGINT",
        "sixes": "BIGINT",
        "strike_rate": "FLOAT",
        "is_out": "BOOLEAN",
        "dismissal_type": "VARCHAR",
        "dismissed_by_bowler": "VARCHAR",
        "dismissed_by_fielder": "VARCHAR",
    },
    "bowling_scorecards": {
        "match_id": "VARCHAR",
        "innings_number": "BIGINT",
        "bowler": "VARCHAR",
        "gender": "VARCHAR",
        "legal_balls_bowled": "BIGINT",
        "overs_bowled": "VARCHAR",
        "runs_conceded": "DOUBLE",
        "wickets": "BIGINT",
        "wides": "BIGINT",
        "no_balls": "BIGINT",
        "maidens": "BIGINT",
        "dot_balls": "BIGINT",
        "dot_ball_percentage": "DOUBLE",
        "economy": "DOUBLE",
    },
    "batting_stats_by_tournament": {
        "tournament_id": "BIGINT",
        "tournament_name": "VARCHAR",
        "season": "VARCHAR",
        "batsman": "VARCHAR",
        "gender": "VARCHAR",
        "matches_played": "BIGINT",
        "innings_played": "BIGINT",
        "times_out": "DOUBLE",
        "not_outs": "DOUBLE",
        "total_runs": "DOUBLE",
        "highest_score": "DOUBLE",
        "total_balls_faced": "DOUBLE",
        "total_dot_balls": "DOUBLE",
        "total_fours": "DOUBLE",
        "total_sixes": "DOUBLE",
        "fifties": "DOUBLE",
        "hundreds": "DOUBLE",
        "batting_average": "DOUBLE",
        "batting_strike_rate": "DOUBLE",
        "dot_ball_percentage": "DOUBLE",
    },
    "bowling_stats_by_tournament": {
        "tournament_id": "BIGINT",
        "tournament_name": "VARCHAR",
        "season": "VARCHAR",
        "bowler": "VARCHAR",
        "gender": "VARCHAR",
        "matches_played": "BIGINT",
        "innings_bowled": "BIGINT",
        "total_legal_balls": "DOUBLE",
        "overs_bowled": "VARCHAR",
        "maidens": "DOUBLE",
        "total_dot_balls": "DOUBLE",
        "dot_ball_percentage": "DOUBLE",
        "runs_conceded": "DOUBLE",
        "wickets": "DOUBLE",
        "bowling_average": "DOUBLE",
        "economy_rate": "DOUBLE",
        "bowling_strike_rate": "DOUBLE",
        "best_bowling_figures": "VARCHAR",
        "three_wicket_hauls": "DOUBLE",
        "four_wicket_hauls": "DOUBLE",
        "five_wicket_hauls": "DOUBLE",
        "wides": "DOUBLE",
        "no_balls": "DOUBLE",
    },
    "players": {
        "npl_player_id": "BIGINT",
        "cricsheet_player_id": "VARCHAR",
        "player_name": "VARCHAR",
    },
    "tournament_players": {
        "tournament_id": "BIGINT",
        "npl_player_id": "BIGINT",
    },
    "tournaments": {
        "tournament_id": "BIGINT",
        "tournament_name": "VARCHAR",
        "season": "VARCHAR",
    },
}

TABLE_ORDER = (
    "tournaments",
    "players",
    "matches",
    "innings_summary",
    "batting_scorecards",
    "bowling_scorecards",
    "batting_stats_by_tournament",
    "bowling_stats_by_tournament",
    "tournament_players",
    "match_player_of_match",
)

PRIMARY_KEYS = {
    "tournaments": ("tournament_id",),
    "players": ("player_id",),
    "matches": ("match_id",),
    "innings_summary": ("match_id", "innings_number"),
    "batting_scorecards": ("match_id", "innings_number", "batting_position"),
    "bowling_scorecards": ("match_id", "innings_number", "player_id"),
    "batting_stats_by_tournament": ("tournament_id", "player_id"),
    "bowling_stats_by_tournament": ("tournament_id", "player_id"),
    "tournament_players": ("tournament_id", "player_id"),
    "match_player_of_match": ("match_id", "player_id"),
}

CREATE_STATEMENTS = (
    """
    CREATE TABLE tournaments (
        tournament_id INTEGER PRIMARY KEY,
        tournament_name TEXT NOT NULL,
        season TEXT NOT NULL,
        UNIQUE (tournament_name, season)
    )
    """,
    """
    CREATE TABLE players (
        player_id INTEGER PRIMARY KEY,
        npl_player_id INTEGER UNIQUE,
        cricsheet_player_id TEXT UNIQUE,
        player_name TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE matches (
        match_id TEXT PRIMARY KEY NOT NULL,
        match_date TEXT NOT NULL,
        match_format TEXT NOT NULL,
        team_1_name TEXT NOT NULL,
        team_2_name TEXT NOT NULL,
        winner_name TEXT,
        venue_name TEXT,
        city TEXT,
        margin INTEGER CHECK (margin IS NULL OR margin >= 0),
        margin_type TEXT,
        toss_winner_name TEXT,
        toss_decision TEXT,
        gender TEXT NOT NULL,
        umpire_1_name TEXT,
        umpire_2_name TEXT,
        match_referee_name TEXT,
        tournament_id INTEGER NOT NULL,
        FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id)
    )
    """,
    """
    CREATE TABLE innings_summary (
        match_id TEXT NOT NULL,
        innings_number INTEGER NOT NULL CHECK (innings_number > 0),
        gender TEXT NOT NULL,
        total_runs INTEGER NOT NULL CHECK (total_runs >= 0),
        total_wickets INTEGER NOT NULL CHECK (total_wickets >= 0),
        legal_balls INTEGER NOT NULL CHECK (legal_balls >= 0),
        overs TEXT NOT NULL,
        batting_team TEXT NOT NULL,
        PRIMARY KEY (match_id, innings_number),
        FOREIGN KEY (match_id) REFERENCES matches(match_id)
    )
    """,
    """
    CREATE TABLE batting_scorecards (
        match_id TEXT NOT NULL,
        innings_number INTEGER NOT NULL,
        batting_position INTEGER NOT NULL CHECK (batting_position > 0),
        player_id INTEGER NOT NULL,
        gender TEXT NOT NULL,
        runs INTEGER NOT NULL CHECK (runs >= 0),
        balls_faced INTEGER NOT NULL CHECK (balls_faced >= 0),
        fours INTEGER NOT NULL CHECK (fours >= 0),
        sixes INTEGER NOT NULL CHECK (sixes >= 0),
        strike_rate REAL,
        is_out INTEGER NOT NULL CHECK (is_out IN (0, 1)),
        dismissal_type TEXT,
        dismissed_by_bowler TEXT,
        dismissed_by_fielder TEXT,
        dot_balls INTEGER NOT NULL CHECK (dot_balls >= 0),
        dot_ball_percentage REAL,
        PRIMARY KEY (match_id, innings_number, batting_position),
        FOREIGN KEY (match_id, innings_number)
            REFERENCES innings_summary(match_id, innings_number),
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )
    """,
    """
    CREATE TABLE bowling_scorecards (
        match_id TEXT NOT NULL,
        innings_number INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        gender TEXT NOT NULL,
        legal_balls_bowled INTEGER NOT NULL CHECK (legal_balls_bowled >= 0),
        overs_bowled TEXT NOT NULL,
        runs_conceded INTEGER NOT NULL CHECK (runs_conceded >= 0),
        wickets INTEGER NOT NULL CHECK (wickets >= 0),
        wides INTEGER NOT NULL CHECK (wides >= 0),
        no_balls INTEGER NOT NULL CHECK (no_balls >= 0),
        maidens INTEGER NOT NULL CHECK (maidens >= 0),
        dot_balls INTEGER NOT NULL CHECK (dot_balls >= 0),
        dot_ball_percentage REAL,
        economy REAL,
        PRIMARY KEY (match_id, innings_number, player_id),
        FOREIGN KEY (match_id, innings_number)
            REFERENCES innings_summary(match_id, innings_number),
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )
    """,
    """
    CREATE TABLE batting_stats_by_tournament (
        tournament_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        gender TEXT NOT NULL,
        matches_played INTEGER NOT NULL CHECK (matches_played >= 0),
        innings_played INTEGER NOT NULL CHECK (innings_played >= 0),
        times_out INTEGER NOT NULL CHECK (times_out >= 0),
        not_outs INTEGER NOT NULL CHECK (not_outs >= 0),
        total_runs INTEGER NOT NULL CHECK (total_runs >= 0),
        highest_score INTEGER NOT NULL CHECK (highest_score >= 0),
        total_balls_faced INTEGER NOT NULL CHECK (total_balls_faced >= 0),
        total_dot_balls INTEGER NOT NULL CHECK (total_dot_balls >= 0),
        total_fours INTEGER NOT NULL CHECK (total_fours >= 0),
        total_sixes INTEGER NOT NULL CHECK (total_sixes >= 0),
        fifties INTEGER NOT NULL CHECK (fifties >= 0),
        hundreds INTEGER NOT NULL CHECK (hundreds >= 0),
        batting_average REAL,
        batting_strike_rate REAL,
        dot_ball_percentage REAL,
        PRIMARY KEY (tournament_id, player_id),
        FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id),
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )
    """,
    """
    CREATE TABLE bowling_stats_by_tournament (
        tournament_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        gender TEXT NOT NULL,
        matches_played INTEGER NOT NULL CHECK (matches_played >= 0),
        innings_bowled INTEGER NOT NULL CHECK (innings_bowled >= 0),
        total_legal_balls INTEGER NOT NULL CHECK (total_legal_balls >= 0),
        overs_bowled TEXT NOT NULL,
        runs_conceded INTEGER NOT NULL CHECK (runs_conceded >= 0),
        wickets INTEGER NOT NULL CHECK (wickets >= 0),
        bowling_average REAL,
        economy_rate REAL,
        bowling_strike_rate REAL,
        best_bowling_figures TEXT,
        three_wicket_hauls INTEGER NOT NULL CHECK (three_wicket_hauls >= 0),
        four_wicket_hauls INTEGER NOT NULL CHECK (four_wicket_hauls >= 0),
        five_wicket_hauls INTEGER NOT NULL CHECK (five_wicket_hauls >= 0),
        wides INTEGER NOT NULL CHECK (wides >= 0),
        no_balls INTEGER NOT NULL CHECK (no_balls >= 0),
        maidens INTEGER NOT NULL CHECK (maidens >= 0),
        total_dot_balls INTEGER NOT NULL CHECK (total_dot_balls >= 0),
        dot_ball_percentage REAL,
        PRIMARY KEY (tournament_id, player_id),
        FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id),
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )
    """,
    """
    CREATE TABLE tournament_players (
        tournament_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        PRIMARY KEY (tournament_id, player_id),
        FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id),
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )
    """,
    """
    CREATE TABLE match_player_of_match (
        match_id TEXT NOT NULL,
        player_id INTEGER NOT NULL,
        PRIMARY KEY (match_id, player_id),
        FOREIGN KEY (match_id) REFERENCES matches(match_id),
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )
    """,
)

DROP_STATEMENTS = tuple(
    f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLE_ORDER)
)


class ImportValidationError(ValueError):
    """Raised when source data cannot be imported without losing integrity."""


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def read_source_data(source_dir: Path) -> dict[str, list[dict[str, Any]]]:
    missing = [
        filename
        for filename in (f"{table}.parquet" for table in SOURCE_SCHEMAS)
        if not (source_dir / filename).is_file()
    ]
    if missing:
        raise ImportValidationError(
            f"Missing required Parquet file(s) in {source_dir}: {', '.join(missing)}"
        )

    data: dict[str, list[dict[str, Any]]] = {}
    connection = duckdb.connect()
    try:
        for table, expected_schema in SOURCE_SCHEMAS.items():
            path = str(source_dir / f"{table}.parquet").replace("'", "''")
            description = connection.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{path}')"
            ).fetchall()
            actual_schema = {row[0]: row[1].upper() for row in description}
            if actual_schema != expected_schema:
                raise ImportValidationError(
                    f"Unexpected schema for {table}.parquet: "
                    f"expected {expected_schema}, got {actual_schema}"
                )

            columns = list(expected_schema)
            query = (
                f"SELECT {', '.join(quote_identifier(c) for c in columns)} "
                f"FROM read_parquet('{path}')"
            )
            cursor = connection.execute(query)
            data[table] = [
                dict(zip(columns, row, strict=True))
                for row in cursor.fetchall()
            ]
    finally:
        connection.close()
    return data


def text_value(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None:
        if nullable:
            return None
        raise ImportValidationError(f"{field} cannot be NULL")
    if not isinstance(value, str):
        raise ImportValidationError(
            f"{field} must be text; received {type(value).__name__}"
        )
    return value


def integer_value(value: Any, field: str, *, nullable: bool = False) -> int | None:
    if value is None:
        if nullable:
            return None
        raise ImportValidationError(f"{field} cannot be NULL")
    if isinstance(value, bool):
        raise ImportValidationError(f"{field} must be an integer, not a boolean")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ImportValidationError(f"{field} is not numeric: {value!r}") from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ImportValidationError(
            f"{field} must be an integral value; received {value!r}"
        )
    result = int(numeric)
    if not -(2**63) <= result < 2**63:
        raise ImportValidationError(f"{field} exceeds SQLite INTEGER range")
    return result


def real_value(value: Any, field: str, *, nullable: bool = False) -> float | None:
    if value is None:
        if nullable:
            return None
        raise ImportValidationError(f"{field} cannot be NULL")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ImportValidationError(f"{field} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise ImportValidationError(f"{field} must be finite; received {value!r}")
    return result


def create_player_mappings(
    connection: sqlite3.Connection,
    players: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[int, int]]:
    connection.executemany(
        """
        INSERT INTO players (npl_player_id, cricsheet_player_id, player_name)
        VALUES (?, ?, ?)
        """,
        [
            (
                integer_value(row["npl_player_id"], "players.npl_player_id"),
                text_value(row["cricsheet_player_id"], "players.cricsheet_player_id"),
                text_value(row["player_name"], "players.player_name"),
            )
            for row in players
        ],
    )
    names_by_id: dict[str, set[int]] = defaultdict(set)
    ids_by_source_id: dict[int, int] = {}
    for row in connection.execute(
        "SELECT player_id, npl_player_id, player_name FROM players"
    ):
        player_id, source_id, name = row
        names_by_id[name].add(player_id)
        ids_by_source_id[source_id] = player_id

    ambiguous_names = sorted(name for name, ids in names_by_id.items() if len(ids) != 1)
    if ambiguous_names:
        raise ImportValidationError(
            f"Player names map to multiple player IDs: {ambiguous_names}"
        )
    return (
        {name: next(iter(ids)) for name, ids in names_by_id.items()},
        ids_by_source_id,
    )


def resolve_player_id(
    name: Any,
    player_ids_by_name: dict[str, int],
    context: str,
) -> int:
    player_name = text_value(name, f"{context} player name")
    player_id = player_ids_by_name.get(player_name)
    if player_id is None:
        raise ImportValidationError(
            f"Missing exact player mapping for {player_name!r} in {context}"
        )
    return player_id


def validate_tournament_reference(
    row: dict[str, Any],
    tournaments_by_id: dict[int, tuple[str, str]],
    context: str,
) -> int:
    tournament_id = integer_value(row["tournament_id"], f"{context}.tournament_id")
    tournament = tournaments_by_id.get(tournament_id)
    if tournament is None:
        raise ImportValidationError(
            f"Missing tournament {tournament_id} referenced by {context}"
        )
    source_identity = (row["tournament_name"], row["season"])
    if source_identity != tournament:
        raise ImportValidationError(
            f"{context} tournament name/season {source_identity!r} does not match "
            f"tournaments.tournament_id {tournament_id}: {tournament!r}"
        )
    return tournament_id


def parse_player_of_match(value: Any, match_id: str) -> list[str]:
    if value is None:
        raise ImportValidationError(
            f"matches.player_of_match is NULL for match {match_id}"
        )
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        raise ImportValidationError(
            f"Cannot parse player_of_match for match {match_id}: {value!r}"
        ) from exc
    if isinstance(parsed, str):
        recipients = [parsed]
    elif isinstance(parsed, (list, tuple)):
        recipients = parsed
    else:
        raise ImportValidationError(
            f"player_of_match for match {match_id} must be a name or list"
        )
    if not recipients:
        raise ImportValidationError(
            f"player_of_match has no recipients for match {match_id}"
        )
    names = [text_value(name, f"player_of_match for match {match_id}") for name in recipients]
    if len(set(names)) != len(names):
        raise ImportValidationError(
            f"Duplicate player_of_match recipient for match {match_id}: {names}"
        )
    return names


def insert_source_rows(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    rows: list[tuple[Any, ...]],
) -> None:
    if not rows:
        return
    column_sql = ", ".join(quote_identifier(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    connection.executemany(
        f"INSERT INTO {quote_identifier(table)} ({column_sql}) "
        f"VALUES ({placeholders})",
        rows,
    )


def load_data(
    connection: sqlite3.Connection,
    data: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    for statement in CREATE_STATEMENTS:
        connection.execute(statement)

    tournaments = data["tournaments"]
    insert_source_rows(
        connection,
        "tournaments",
        ("tournament_id", "tournament_name", "season"),
        [
            (
                integer_value(row["tournament_id"], "tournaments.tournament_id"),
                text_value(row["tournament_name"], "tournaments.tournament_name"),
                text_value(row["season"], "tournaments.season"),
            )
            for row in tournaments
        ],
    )
    tournaments_by_id = {
        tournament_id: (name, season)
        for tournament_id, name, season in connection.execute(
            "SELECT tournament_id, tournament_name, season FROM tournaments"
        )
    }

    player_ids_by_name, player_ids_by_npl_id = create_player_mappings(
        connection, data["players"]
    )

    match_rows = []
    match_recipients: list[tuple[str, int]] = []
    for row in data["matches"]:
        tournament_id = validate_tournament_reference(
            row, tournaments_by_id, f"matches.match_id={row['match_id']}"
        )
        match_id = text_value(row["match_id"], "matches.match_id")
        match_rows.append(
            (
                match_id,
                text_value(row["match_date"], "matches.match_date"),
                text_value(row["match_format"], "matches.match_format"),
                text_value(row["team_1_name"], "matches.team_1_name"),
                text_value(row["team_2_name"], "matches.team_2_name"),
                text_value(row["winner_name"], "matches.winner_name", nullable=True),
                text_value(row["venue_name"], "matches.venue_name", nullable=True),
                text_value(row["city"], "matches.city", nullable=True),
                integer_value(row["margin"], "matches.margin", nullable=True),
                text_value(row["margin_type"], "matches.margin_type", nullable=True),
                text_value(row["toss_winner_name"], "matches.toss_winner_name", nullable=True),
                text_value(row["toss_decision"], "matches.toss_decision", nullable=True),
                text_value(row["gender"], "matches.gender"),
                text_value(row["umpire_1_name"], "matches.umpire_1_name", nullable=True),
                text_value(row["umpire_2_name"], "matches.umpire_2_name", nullable=True),
                text_value(
                    row["match_referee_name"], "matches.match_referee_name", nullable=True
                ),
                tournament_id,
            )
        )
        for recipient in parse_player_of_match(row["player_of_match"], match_id):
            match_recipients.append(
                (
                    match_id,
                    resolve_player_id(
                        recipient, player_ids_by_name, f"player_of_match match {match_id}"
                    ),
                )
            )
    insert_source_rows(
        connection,
        "matches",
        (
            "match_id", "match_date", "match_format", "team_1_name", "team_2_name",
            "winner_name", "venue_name", "city", "margin", "margin_type",
            "toss_winner_name", "toss_decision", "gender", "umpire_1_name",
            "umpire_2_name", "match_referee_name", "tournament_id",
        ),
        match_rows,
    )

    innings_rows = [
        (
            text_value(row["match_id"], "innings_summary.match_id"),
            integer_value(row["innings_number"], "innings_summary.innings_number"),
            text_value(row["gender"], "innings_summary.gender"),
            integer_value(row["total_runs"], "innings_summary.total_runs"),
            integer_value(row["total_wickets"], "innings_summary.total_wickets"),
            integer_value(row["legal_balls"], "innings_summary.legal_balls"),
            text_value(row["overs"], "innings_summary.overs"),
            text_value(row["batting_team"], "innings_summary.batting_team"),
        )
        for row in data["innings_summary"]
    ]
    insert_source_rows(
        connection,
        "innings_summary",
        (
            "match_id", "innings_number", "gender", "total_runs", "total_wickets",
            "legal_balls", "overs", "batting_team",
        ),
        innings_rows,
    )

    batting_rows = [
        (
            text_value(row["match_id"], "batting_scorecards.match_id"),
            integer_value(row["innings_number"], "batting_scorecards.innings_number"),
            integer_value(row["batting_position"], "batting_scorecards.batting_position"),
            resolve_player_id(
                row["batsman"], player_ids_by_name, "batting_scorecards"
            ),
            text_value(row["gender"], "batting_scorecards.gender"),
            integer_value(row["runs"], "batting_scorecards.runs"),
            integer_value(row["balls_faced"], "batting_scorecards.balls_faced"),
            integer_value(row["fours"], "batting_scorecards.fours"),
            integer_value(row["sixes"], "batting_scorecards.sixes"),
            real_value(row["strike_rate"], "batting_scorecards.strike_rate", nullable=True),
            int(row["is_out"]) if isinstance(row["is_out"], bool) else None,
            text_value(
                row["dismissal_type"], "batting_scorecards.dismissal_type", nullable=True
            ),
            text_value(
                row["dismissed_by_bowler"],
                "batting_scorecards.dismissed_by_bowler",
                nullable=True,
            ),
            text_value(
                row["dismissed_by_fielder"],
                "batting_scorecards.dismissed_by_fielder",
                nullable=True,
            ),
            integer_value(row["dot_balls"], "batting_scorecards.dot_balls"),
            real_value(
                row["dot_ball_percentage"],
                "batting_scorecards.dot_ball_percentage",
                nullable=True,
            ),
        )
        for row in data["batting_scorecards"]
    ]
    if any(row[10] is None for row in batting_rows):
        raise ImportValidationError(
            "batting_scorecards.is_out contains a non-boolean value"
        )
    insert_source_rows(
        connection,
        "batting_scorecards",
        (
            "match_id", "innings_number", "batting_position", "player_id", "gender",
            "runs", "balls_faced", "fours", "sixes", "strike_rate", "is_out",
            "dismissal_type", "dismissed_by_bowler", "dismissed_by_fielder",
            "dot_balls", "dot_ball_percentage",
        ),
        batting_rows,
    )

    bowling_rows = [
        (
            text_value(row["match_id"], "bowling_scorecards.match_id"),
            integer_value(row["innings_number"], "bowling_scorecards.innings_number"),
            resolve_player_id(row["bowler"], player_ids_by_name, "bowling_scorecards"),
            text_value(row["gender"], "bowling_scorecards.gender"),
            integer_value(
                row["legal_balls_bowled"], "bowling_scorecards.legal_balls_bowled"
            ),
            text_value(row["overs_bowled"], "bowling_scorecards.overs_bowled"),
            integer_value(row["runs_conceded"], "bowling_scorecards.runs_conceded"),
            integer_value(row["wickets"], "bowling_scorecards.wickets"),
            integer_value(row["wides"], "bowling_scorecards.wides"),
            integer_value(row["no_balls"], "bowling_scorecards.no_balls"),
            real_value(row["economy"], "bowling_scorecards.economy", nullable=True),
            integer_value(row["maidens"], "bowling_scorecards.maidens"),
            integer_value(row["dot_balls"], "bowling_scorecards.dot_balls"),
            real_value(
                row["dot_ball_percentage"],
                "bowling_scorecards.dot_ball_percentage",
                nullable=True,
            ),
        )
        for row in data["bowling_scorecards"]
    ]
    insert_source_rows(
        connection,
        "bowling_scorecards",
        (
            "match_id", "innings_number", "player_id", "gender",
            "legal_balls_bowled", "overs_bowled", "runs_conceded", "wickets",
            "wides", "no_balls", "economy", "maidens", "dot_balls",
            "dot_ball_percentage",
        ),
        bowling_rows,
    )

    batting_stats_rows = []
    for row in data["batting_stats_by_tournament"]:
        tournament_id = validate_tournament_reference(
            row, tournaments_by_id, "batting_stats_by_tournament"
        )
        batting_stats_rows.append(
            (
                tournament_id,
                resolve_player_id(
                    row["batsman"], player_ids_by_name, "batting_stats_by_tournament"
                ),
                text_value(row["gender"], "batting_stats_by_tournament.gender"),
                integer_value(row["matches_played"], "batting_stats_by_tournament.matches_played"),
                integer_value(row["innings_played"], "batting_stats_by_tournament.innings_played"),
                integer_value(row["times_out"], "batting_stats_by_tournament.times_out"),
                integer_value(row["not_outs"], "batting_stats_by_tournament.not_outs"),
                integer_value(row["total_runs"], "batting_stats_by_tournament.total_runs"),
                integer_value(row["highest_score"], "batting_stats_by_tournament.highest_score"),
                integer_value(row["total_balls_faced"], "batting_stats_by_tournament.total_balls_faced"),
                integer_value(row["total_dot_balls"], "batting_stats_by_tournament.total_dot_balls"),
                integer_value(row["total_fours"], "batting_stats_by_tournament.total_fours"),
                integer_value(row["total_sixes"], "batting_stats_by_tournament.total_sixes"),
                integer_value(row["fifties"], "batting_stats_by_tournament.fifties"),
                integer_value(row["hundreds"], "batting_stats_by_tournament.hundreds"),
                real_value(row["batting_average"], "batting_stats_by_tournament.batting_average", nullable=True),
                real_value(row["batting_strike_rate"], "batting_stats_by_tournament.batting_strike_rate", nullable=True),
                real_value(row["dot_ball_percentage"], "batting_stats_by_tournament.dot_ball_percentage", nullable=True),
            )
        )
    insert_source_rows(
        connection,
        "batting_stats_by_tournament",
        (
            "tournament_id", "player_id", "gender", "matches_played", "innings_played",
            "times_out", "not_outs", "total_runs", "highest_score",
            "total_balls_faced", "total_dot_balls", "total_fours", "total_sixes", "fifties",
            "hundreds", "batting_average", "batting_strike_rate",
            "dot_ball_percentage",
        ),
        batting_stats_rows,
    )

    bowling_stats_rows = []
    for row in data["bowling_stats_by_tournament"]:
        tournament_id = validate_tournament_reference(
            row, tournaments_by_id, "bowling_stats_by_tournament"
        )
        bowling_stats_rows.append(
            (
                tournament_id,
                resolve_player_id(
                    row["bowler"], player_ids_by_name, "bowling_stats_by_tournament"
                ),
                text_value(row["gender"], "bowling_stats_by_tournament.gender"),
                integer_value(row["matches_played"], "bowling_stats_by_tournament.matches_played"),
                integer_value(row["innings_bowled"], "bowling_stats_by_tournament.innings_bowled"),
                integer_value(row["total_legal_balls"], "bowling_stats_by_tournament.total_legal_balls"),
                text_value(row["overs_bowled"], "bowling_stats_by_tournament.overs_bowled"),
                integer_value(row["runs_conceded"], "bowling_stats_by_tournament.runs_conceded"),
                integer_value(row["wickets"], "bowling_stats_by_tournament.wickets"),
                real_value(row["bowling_average"], "bowling_stats_by_tournament.bowling_average", nullable=True),
                real_value(row["economy_rate"], "bowling_stats_by_tournament.economy_rate", nullable=True),
                real_value(row["bowling_strike_rate"], "bowling_stats_by_tournament.bowling_strike_rate", nullable=True),
                text_value(row["best_bowling_figures"], "bowling_stats_by_tournament.best_bowling_figures", nullable=True),
                integer_value(row["three_wicket_hauls"], "bowling_stats_by_tournament.three_wicket_hauls"),
                integer_value(row["four_wicket_hauls"], "bowling_stats_by_tournament.four_wicket_hauls"),
                integer_value(row["five_wicket_hauls"], "bowling_stats_by_tournament.five_wicket_hauls"),
                integer_value(row["wides"], "bowling_stats_by_tournament.wides"),
                integer_value(row["no_balls"], "bowling_stats_by_tournament.no_balls"),
                integer_value(row["maidens"], "bowling_stats_by_tournament.maidens"),
                integer_value(
                    row["total_dot_balls"],
                    "bowling_stats_by_tournament.total_dot_balls",
                ),
                real_value(
                    row["dot_ball_percentage"],
                    "bowling_stats_by_tournament.dot_ball_percentage",
                    nullable=True,
                ),
            )
        )
    insert_source_rows(
        connection,
        "bowling_stats_by_tournament",
        (
            "tournament_id", "player_id", "gender", "matches_played",
            "innings_bowled", "total_legal_balls", "overs_bowled",
            "runs_conceded", "wickets", "bowling_average", "economy_rate",
            "bowling_strike_rate", "best_bowling_figures", "three_wicket_hauls",
            "four_wicket_hauls", "five_wicket_hauls", "wides", "no_balls",
            "maidens", "total_dot_balls", "dot_ball_percentage",
        ),
        bowling_stats_rows,
    )

    participation_rows = []
    for row in data["tournament_players"]:
        tournament_id = integer_value(
            row["tournament_id"], "tournament_players.tournament_id"
        )
        npl_player_id = integer_value(
            row["npl_player_id"], "tournament_players.npl_player_id"
        )
        player_id = player_ids_by_npl_id.get(npl_player_id)
        if player_id is None:
            raise ImportValidationError(
                f"Missing npl_player_id={npl_player_id} mapping in tournament_players"
            )
        participation_rows.append((tournament_id, player_id))
    insert_source_rows(
        connection,
        "tournament_players",
        ("tournament_id", "player_id"),
        participation_rows,
    )

    insert_source_rows(
        connection,
        "match_player_of_match",
        ("match_id", "player_id"),
        match_recipients,
    )
    return {
        "scorecard_and_stat_player_names_resolved": (
            len(data["batting_scorecards"])
            + len(data["bowling_scorecards"])
            + len(data["batting_stats_by_tournament"])
            + len(data["bowling_stats_by_tournament"])
        ),
        "player_of_match_names_resolved": len(match_recipients),
    }


def validate_database(
    connection: sqlite3.Connection,
    source_data: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise ImportValidationError(f"Foreign-key violations: {foreign_key_errors}")

    integrity_result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity_result != "ok":
        raise ImportValidationError(f"SQLite integrity_check failed: {integrity_result}")

    counts = {
        table: connection.execute(
            f"SELECT COUNT(*) FROM {quote_identifier(table)}"
        ).fetchone()[0]
        for table in TABLE_ORDER
    }
    expected_counts = {
        table: len(source_data[table])
        for table in SOURCE_SCHEMAS
    }
    expected_counts["match_player_of_match"] = sum(
        len(parse_player_of_match(row["player_of_match"], row["match_id"]))
        for row in source_data["matches"]
    )
    count_mismatches = {
        table: {"expected": expected, "actual": counts[table]}
        for table, expected in expected_counts.items()
        if counts[table] != expected
    }
    if count_mismatches:
        raise ImportValidationError(
            f"Imported row counts do not match source rows: {count_mismatches}"
        )

    duplicate_primary_keys = {}
    for table, columns in PRIMARY_KEYS.items():
        grouping = ", ".join(quote_identifier(column) for column in columns)
        duplicates = connection.execute(
            f"SELECT COUNT(*) FROM ("
            f"SELECT {grouping} FROM {quote_identifier(table)} "
            f"GROUP BY {grouping} HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        if duplicates:
            duplicate_primary_keys[table] = duplicates
    if duplicate_primary_keys:
        raise ImportValidationError(
            f"Duplicate primary keys found: {duplicate_primary_keys}"
        )

    return {
        "row_counts": counts,
        "source_row_counts": expected_counts,
        "foreign_key_violations": len(foreign_key_errors),
        "sqlite_integrity_check": integrity_result,
        "duplicate_primary_keys": duplicate_primary_keys,
        "all_source_records_imported": True,
    }


def rebuild_database(database_path: Path, source_data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise ImportValidationError("SQLite foreign-key enforcement is not enabled")
        connection.execute("BEGIN IMMEDIATE")
        for statement in DROP_STATEMENTS:
            connection.execute(statement)
        mapping_counts = load_data(connection, source_data)
        validation = validate_database(connection, source_data)
        connection.commit()
        validation.update(
            {
                "missing_player_mappings": 0,
                "missing_player_of_match_mappings": 0,
                "resolved_name_mappings": mapping_counts,
            }
        )
        return validation
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
        help=f"Directory containing the nine Parquet files (default: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"SQLite database output path (default: {DEFAULT_DATABASE})",
    )
    args = parser.parse_args()

    try:
        source_data = read_source_data(args.source_dir.resolve())
        validation = rebuild_database(args.database.resolve(), source_data)
    except (duckdb.Error, sqlite3.Error, ImportValidationError, OSError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    result = {
        "database": str(args.database.resolve()),
        "file_size_bytes": args.database.resolve().stat().st_size,
        **validation,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
