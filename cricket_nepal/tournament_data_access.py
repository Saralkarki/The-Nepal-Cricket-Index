"""Read-only queries for tournament-level match metadata across datasets."""

from typing import Any

from django.db import connections


def get_tournament_match_formats() -> list[dict[str, Any]]:
    with connections["cricket"].cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT
                'NPL' AS source,
                t.tournament_name,
                t.season,
                m.gender,
                m.match_format
            FROM matches AS m
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            UNION
            SELECT DISTINCT
                'Nepal national team' AS source,
                tournament_name,
                season,
                gender,
                match_format
            FROM nepal_matches
            ORDER BY source, tournament_name, season, gender, match_format
            """
        )
        columns = [column[0] for column in cursor.description]
        return [
            dict(zip(columns, row, strict=True))
            for row in cursor.fetchall()
        ]
