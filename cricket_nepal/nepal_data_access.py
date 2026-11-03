"""Read-only queries for Nepal national-team cricket data."""

from typing import Any

from django.db import connections


CRICKET_DATABASE = "cricket"


def get_nepal_tournaments() -> list[dict[str, Any]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT tournament_id, tournament_name, season
            FROM nepal_matches
            ORDER BY season DESC, tournament_id DESC, tournament_name
            """
        )
        columns = [column[0] for column in cursor.description]
        return [
            dict(zip(columns, row, strict=True))
            for row in cursor.fetchall()
        ]


def get_nepal_matches(
    tournament_id: int | None = None,
    gender: str | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT
            match_id,
            match_date,
            match_format,
            team_1_name,
            team_2_name,
            venue_name,
            tournament_id,
            tournament_name,
            season,
            gender,
            winner_name,
            margin,
            margin_type,
            player_of_match
        FROM nepal_matches
    """
    filters = []
    parameters: list[int | str] = []
    if tournament_id is not None:
        filters.append("tournament_id = %s")
        parameters.append(tournament_id)
    if gender is not None:
        filters.append("gender = %s")
        parameters.append(gender)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY match_date DESC, match_id DESC"

    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(query, parameters)
        columns = [column[0] for column in cursor.description]
        return [
            dict(zip(columns, row, strict=True))
            for row in cursor.fetchall()
        ]
