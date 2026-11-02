"""Read-only queries for the imported cricket statistics database."""

from typing import Any

from django.db import connections


CRICKET_DATABASE = "cricket"


def _rows_as_dicts(cursor: Any) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def list_tables() -> list[str]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        return [row[0] for row in cursor.fetchall()]


def get_tournaments() -> list[dict[str, Any]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT tournament_id, tournament_name, season
            FROM tournaments
            ORDER BY season, tournament_id
            """
        )
        return _rows_as_dicts(cursor)


def count_matches() -> int:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM matches")
        return cursor.fetchone()[0]


def get_top_batting_stats(tournament_id: int, limit: int = 10) -> list[dict[str, Any]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT p.player_name, s.matches_played, s.innings_played,
                   s.total_runs, s.highest_score, s.batting_average,
                   s.batting_strike_rate
            FROM batting_stats_by_tournament AS s
            JOIN players AS p ON p.player_id = s.player_id
            WHERE s.tournament_id = %s
            ORDER BY s.total_runs DESC, s.batting_average DESC, p.player_name
            LIMIT %s
            """,
            [tournament_id, limit],
        )
        return _rows_as_dicts(cursor)


def get_top_bowling_stats(tournament_id: int, limit: int = 10) -> list[dict[str, Any]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT p.player_name, s.matches_played, s.innings_bowled,
                   s.wickets, s.bowling_average, s.economy_rate,
                   s.bowling_strike_rate, s.best_bowling_figures
            FROM bowling_stats_by_tournament AS s
            JOIN players AS p ON p.player_id = s.player_id
            WHERE s.tournament_id = %s
            ORDER BY s.wickets DESC, s.economy_rate ASC, p.player_name
            LIMIT %s
            """,
            [tournament_id, limit],
        )
        return _rows_as_dicts(cursor)


def get_match_with_innings(match_id: str) -> dict[str, Any] | None:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT match_id, match_date, match_format, team_1_name, team_2_name,
                   winner_name, venue_name, tournament_id
            FROM matches
            WHERE match_id = %s
            """,
            [match_id],
        )
        match_rows = _rows_as_dicts(cursor)
        if not match_rows:
            return None

        cursor.execute(
            """
            SELECT innings_number, total_runs, total_wickets, legal_balls, overs
            FROM innings_summary
            WHERE match_id = %s
            ORDER BY innings_number
            """,
            [match_id],
        )
        match = match_rows[0]
        match["innings"] = _rows_as_dicts(cursor)
        return match
