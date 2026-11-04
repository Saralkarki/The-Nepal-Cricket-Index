"""Read-only queries for Nepal national-team cricket data."""

from typing import Any

from django.db import connections


CRICKET_DATABASE = "cricket"

LEAGUE_2_CYCLES = {
    "2019-2023": (1097, 1207, 1266, 1349, 1424),
    "2024-2027": (1583, 1659, 1760, 1860, 1973, 2087, 2177),
}

NEPAL_MATCH_OUTCOME_OVERRIDES = {
    "1312806": "tie",
    "1341976": "no_result",
    "1450700": "no_result",
    "1450707": "no_result",
}
ABANDONED_MATCH_IDS = {"1450700"}
NEPAL_PLAYER_FORMATS = ("ODI", "T20I", "T20")


def get_nepal_tournaments() -> list[dict[str, Any]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT tournament_id, tournament_name, season, gender
            FROM nepal_matches
            ORDER BY season DESC, tournament_id DESC, tournament_name, gender
            """
        )
        columns = [column[0] for column in cursor.description]
        return [
            dict(zip(columns, row, strict=True))
            for row in cursor.fetchall()
        ]


def get_nepal_player_directory(
    search_term: str = "", gender: str | None = None
) -> list[dict[str, Any]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT nepal_player_id, player_name, gender
            FROM nepal_players
            WHERE (%s = '' OR instr(lower(player_name), lower(%s)) > 0)
              AND (%s IS NULL OR gender = %s)
            ORDER BY lower(player_name), nepal_player_id
            """,
            [search_term, search_term, gender, gender],
        )
        players = _rows_as_dicts(cursor)

        if not players:
            return []

        player_ids = [player["nepal_player_id"] for player in players]
        player_placeholders = ", ".join("%s" for _ in player_ids)
        format_placeholders = ", ".join("%s" for _ in NEPAL_PLAYER_FORMATS)
        cursor.execute(
            f"""
            SELECT tp.nepal_player_id, tournament.tournament_id,
                   tournament.tournament_name, tournament.season
            FROM nepal_tournament_players AS tp
            JOIN (
                SELECT DISTINCT tournament_id, tournament_name, season
                FROM nepal_matches
                WHERE match_format IN ({format_placeholders})
            ) AS tournament
              ON tournament.tournament_id = tp.tournament_id
            WHERE tp.nepal_player_id IN ({player_placeholders})
            ORDER BY tp.nepal_player_id, tournament.season DESC,
                     tournament.tournament_name
            """,
            [*NEPAL_PLAYER_FORMATS, *player_ids],
        )
        participations = _rows_as_dicts(cursor)

    participation_by_player: dict[int, list[dict[str, Any]]] = {}
    seen: set[tuple[int, int]] = set()
    for row in participations:
        key = (row["nepal_player_id"], row["tournament_id"])
        if key in seen:
            continue
        seen.add(key)
        participation_by_player.setdefault(row["nepal_player_id"], []).append(
            {
                "tournament_id": row["tournament_id"],
                "tournament_name": row["tournament_name"],
                "season": row["season"],
            }
        )

    for player in players:
        player["participations"] = participation_by_player.get(
            player["nepal_player_id"], []
        )
    return players


def _nepal_batting_format_stats(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    runs = sum(row["runs"] or 0 for row in rows)
    dismissals = sum(bool(row["is_out"]) for row in rows)
    balls = sum(row["balls_faced"] or 0 for row in rows)
    dot_balls = sum(row["dot_balls"] or 0 for row in rows)
    return {
        "matches": len({row["match_id"] for row in rows}),
        "innings": len(rows),
        "runs": runs,
        "highest_score": max(
            (row["runs"] for row in rows if row["runs"] is not None),
            default=None,
        ),
        "average": runs / dismissals if dismissals else None,
        "balls_faced": balls,
        "strike_rate": runs * 100 / balls if balls else None,
        "fours": sum(row["fours"] or 0 for row in rows),
        "sixes": sum(row["sixes"] or 0 for row in rows),
        "fifties": sum(50 <= (row["runs"] or 0) < 100 for row in rows),
        "hundreds": sum((row["runs"] or 0) >= 100 for row in rows),
        "dot_balls": dot_balls,
        "dot_ball_percentage": dot_balls * 100 / balls if balls else None,
    }


def _nepal_bowling_format_stats(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    wickets = sum(row["wickets"] or 0 for row in rows)
    runs_conceded = sum(row["runs_conceded"] or 0 for row in rows)
    legal_balls = sum(row["legal_balls_bowled"] or 0 for row in rows)
    dot_balls = sum(row["dot_balls"] or 0 for row in rows)
    innings: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        key = (row["match_id"], row["innings_number"])
        figures = innings.setdefault(key, {"wickets": 0, "runs_conceded": 0})
        figures["wickets"] += row["wickets"] or 0
        figures["runs_conceded"] += row["runs_conceded"] or 0
    best_figures = min(
        innings.values(),
        key=lambda figures: (-figures["wickets"], figures["runs_conceded"]),
    )
    return {
        "matches": len({row["match_id"] for row in rows}),
        "innings": len(innings),
        "wickets": wickets,
        "runs_conceded": runs_conceded,
        "average": runs_conceded / wickets if wickets else None,
        "legal_balls": legal_balls,
        "overs": f"{legal_balls // 6}.{legal_balls % 6}",
        "economy": runs_conceded * 6 / legal_balls if legal_balls else None,
        "strike_rate": legal_balls / wickets if wickets else None,
        "maidens": sum(row["maidens"] or 0 for row in rows),
        "dot_balls": dot_balls,
        "dot_ball_percentage": (
            dot_balls * 100 / legal_balls if legal_balls else None
        ),
        "wides": sum(row["wides"] or 0 for row in rows),
        "no_balls": sum(row["no_balls"] or 0 for row in rows),
        "best_figures": best_figures,
    }


def get_nepal_player_profile(nepal_player_id: int) -> dict[str, Any] | None:
    format_placeholders = ", ".join("%s" for _ in NEPAL_PLAYER_FORMATS)
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT nepal_player_id, cricsheet_player_id, player_name, gender
            FROM nepal_players
            WHERE nepal_player_id = %s
            """,
            [nepal_player_id],
        )
        player_rows = _rows_as_dicts(cursor)
        if not player_rows:
            return None
        player = player_rows[0]

        cursor.execute(
            f"""
            SELECT match_format, match_id, runs, balls_faced, fours, sixes,
                   dot_balls, is_out
            FROM nepal_batting_scorecards
            WHERE batsman = %s
              AND gender = %s
              AND match_format IN ({format_placeholders})
            ORDER BY match_format, match_id, innings_number
            """,
            [player["player_name"], player["gender"], *NEPAL_PLAYER_FORMATS],
        )
        batting_by_format: dict[str, list[dict[str, Any]]] = {}
        for row in _rows_as_dicts(cursor):
            batting_by_format.setdefault(row["match_format"], []).append(row)

        cursor.execute(
            f"""
            SELECT match_format, match_id, innings_number, legal_balls_bowled,
                   runs_conceded, wickets, maidens, dot_balls, wides, no_balls
            FROM nepal_bowling_scorecards
            WHERE bowler = %s
              AND gender = %s
              AND match_format IN ({format_placeholders})
            ORDER BY match_format, match_id, innings_number
            """,
            [player["player_name"], player["gender"], *NEPAL_PLAYER_FORMATS],
        )
        bowling_by_format: dict[str, list[dict[str, Any]]] = {}
        for row in _rows_as_dicts(cursor):
            bowling_by_format.setdefault(row["match_format"], []).append(row)

        cursor.execute(
            f"""
            SELECT DISTINCT tournament.tournament_id,
                   tournament.tournament_name, tournament.season
            FROM nepal_tournament_players AS tp
            JOIN (
                SELECT DISTINCT tournament_id, tournament_name, season
                FROM nepal_matches
                WHERE match_format IN ({format_placeholders})
            ) AS tournament
              ON tournament.tournament_id = tp.tournament_id
            WHERE tp.nepal_player_id = %s
            ORDER BY tournament.season DESC, tournament.tournament_name
            """,
            [*NEPAL_PLAYER_FORMATS, nepal_player_id],
        )
        participations = _rows_as_dicts(cursor)

        cursor.execute(
            f"""
            WITH player_scorecard_matches AS (
                SELECT DISTINCT match_id, tournament_id
                FROM nepal_batting_scorecards
                WHERE batsman = %s
                  AND gender = %s
                  AND match_format IN ({format_placeholders})
                UNION
                SELECT DISTINCT match_id, tournament_id
                FROM nepal_bowling_scorecards
                WHERE bowler = %s
                  AND gender = %s
                  AND match_format IN ({format_placeholders})
            )
            SELECT match.tournament_id, match.match_id, match.match_date,
                   match.match_format, match.team_1_name, match.team_2_name
            FROM player_scorecard_matches AS appearance
            JOIN nepal_matches AS match
              ON match.match_id = appearance.match_id
             AND match.tournament_id = appearance.tournament_id
            ORDER BY match.tournament_id, match.match_date DESC, match.match_id DESC
            """,
            [
                player["player_name"],
                player["gender"],
                *NEPAL_PLAYER_FORMATS,
                player["player_name"],
                player["gender"],
                *NEPAL_PLAYER_FORMATS,
            ],
        )
        recorded_matches = _rows_as_dicts(cursor)

    matches_by_tournament: dict[int, list[dict[str, Any]]] = {}
    appearances_by_format: dict[str, set[str]] = {}
    for match in recorded_matches:
        opponent = (
            match["team_2_name"]
            if match["team_1_name"] == "Nepal"
            else match["team_1_name"]
        )
        appearances_by_format.setdefault(match["match_format"], set()).add(
            match["match_id"]
        )
        matches_by_tournament.setdefault(match["tournament_id"], []).append(
            {
                "match_id": match["match_id"],
                "match_date": match["match_date"],
                "match_format": match["match_format"],
                "opponent": opponent,
            }
        )
    for participation in participations:
        participation["matches"] = matches_by_tournament.get(
            participation["tournament_id"], []
        )

    player["participations"] = participations
    player["formats"] = [
        {
            "name": match_format,
            "recorded_appearances": len(
                appearances_by_format.get(match_format, set())
            ),
            "batting": _nepal_batting_format_stats(
                batting_by_format.get(match_format, [])
            ),
            "bowling": _nepal_bowling_format_stats(
                bowling_by_format.get(match_format, [])
            ),
        }
        for match_format in NEPAL_PLAYER_FORMATS
    ]
    return player


def _rows_as_dicts(cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    return [
        dict(zip(columns, row, strict=True))
        for row in cursor.fetchall()
    ]


def _id_placeholders(tournament_ids: tuple[int, ...]) -> str:
    if not tournament_ids:
        raise ValueError("At least one Nepal tournament ID is required")
    return ", ".join("%s" for _ in tournament_ids)


def _nepal_match_outcome(match: dict[str, Any]) -> str:
    match_id = str(match["match_id"])
    if match_id in NEPAL_MATCH_OUTCOME_OVERRIDES:
        return NEPAL_MATCH_OUTCOME_OVERRIDES[match_id]

    if match["team_1_name"] == "Nepal":
        opponent = match["team_2_name"]
    elif match["team_2_name"] == "Nepal":
        opponent = match["team_1_name"]
    else:
        opponent = None

    if match["winner_name"] == "Nepal":
        return "win"
    if opponent is not None and match["winner_name"] == opponent:
        return "loss"
    return "unclassified"


def _nepal_match_result(match: dict[str, Any], outcome: str) -> str:
    if outcome == "tie":
        return "Tie"
    if outcome == "no_result":
        result = "No Result (NR)"
        if str(match["match_id"]) in ABANDONED_MATCH_IDS:
            result += " — Abandoned without a ball being bowled"
        return result
    if outcome == "unclassified":
        return "Outcome unavailable"

    result = f'{match["winner_name"]} won'
    if match["margin"] is not None and match["margin_type"]:
        result += f' by {match["margin"]} {match["margin_type"]}'
    return result


def _build_nepal_performance(matches: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [_nepal_match_outcome(match) for match in matches]
    wins = outcomes.count("win")
    losses = outcomes.count("loss")
    ties = outcomes.count("tie")
    no_results = outcomes.count("no_result")
    unclassified = outcomes.count("unclassified")
    percentage_denominator = wins + losses + ties
    return {
        "matches_played": len(matches),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "no_results": no_results,
        "unclassified": unclassified,
        "win_percentage": (
            wins * 100 / percentage_denominator
            if percentage_denominator
            else None
        ),
    }


def _score_display(
    total_runs: int | float, total_wickets: int, overs: str | None
) -> str:
    score = f"{total_runs:g}/{total_wickets}"
    return f"{score} ({overs} ov)" if overs else score


def get_nepal_tournament_overview(
    tournament_ids: tuple[int, ...],
) -> dict[str, Any] | None:
    placeholders = _id_placeholders(tournament_ids)
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT tournament_name, gender, match_format
            FROM nepal_matches
            WHERE tournament_id IN ({placeholders})
            ORDER BY tournament_name, gender, match_format
            """,
            tournament_ids,
        )
        metadata = _rows_as_dicts(cursor)
        if not metadata:
            return None

        cursor.execute(
            f"""
            SELECT match_id, match_date, team_1_name, team_2_name,
                   winner_name, margin, margin_type
            FROM nepal_matches
            WHERE tournament_id IN ({placeholders})
            ORDER BY match_date DESC, match_id DESC
            """,
            tournament_ids,
        )
        matches = _rows_as_dicts(cursor)
        performance = _build_nepal_performance(matches)
        match_ids = [match["match_id"] for match in matches]

        innings_by_match: dict[str, list[dict[str, Any]]] = {
            match_id: [] for match_id in match_ids
        }
        if match_ids:
            match_placeholders = ", ".join("%s" for _ in match_ids)
            cursor.execute(
                f"""
                SELECT match_id, batting_team, total_runs, total_wickets, overs
                FROM nepal_innings_summary
                WHERE match_id IN ({match_placeholders})
                ORDER BY match_id, innings_number
                """,
                match_ids,
            )
            for innings in _rows_as_dicts(cursor):
                innings["score"] = _score_display(
                    innings["total_runs"],
                    innings["total_wickets"],
                    innings["overs"],
                )
                innings_by_match[innings["match_id"]].append(innings)

        cursor.execute(
            f"""
            SELECT batsman, SUM(total_runs) AS runs
            FROM nepal_batting_stats_by_tournament
            WHERE tournament_id IN ({placeholders})
            GROUP BY batsman
            ORDER BY runs DESC, batsman
            LIMIT 1
            """,
            tournament_ids,
        )
        most_runs = _rows_as_dicts(cursor)
        cursor.execute(
            f"""
            SELECT batsman, runs, match_id
            FROM nepal_batting_scorecards
            WHERE tournament_id IN ({placeholders})
            ORDER BY runs DESC, batsman, match_id
            LIMIT 1
            """,
            tournament_ids,
        )
        highest_score = _rows_as_dicts(cursor)
        cursor.execute(
            f"""
            SELECT bowler, SUM(wickets) AS wickets
            FROM nepal_bowling_stats_by_tournament
            WHERE tournament_id IN ({placeholders})
            GROUP BY bowler
            ORDER BY wickets DESC, bowler
            LIMIT 1
            """,
            tournament_ids,
        )
        most_wickets = _rows_as_dicts(cursor)
        cursor.execute(
            f"""
            SELECT bowler, match_id, innings_number,
                   SUM(wickets) AS wickets, SUM(runs_conceded) AS runs_conceded
            FROM nepal_bowling_scorecards
            WHERE tournament_id IN ({placeholders})
            GROUP BY bowler, match_id, innings_number
            ORDER BY wickets DESC, runs_conceded, bowler
            LIMIT 1
            """,
            tournament_ids,
        )
        best_figures = _rows_as_dicts(cursor)

    match_history = []
    for match in matches:
        opponent = (
            match["team_2_name"]
            if match["team_1_name"] == "Nepal"
            else match["team_1_name"]
        )
        outcome = _nepal_match_outcome(match)
        result = _nepal_match_result(match, outcome)
        match_history.append(
            {
                **match,
                "opponent": opponent,
                "outcome": outcome,
                "result": result,
                "scores": innings_by_match[match["match_id"]],
            }
        )

    return {
        "tournament_name": metadata[0]["tournament_name"],
        "genders": list(dict.fromkeys(row["gender"] for row in metadata if row["gender"])),
        "match_formats": list(
            dict.fromkeys(row["match_format"] for row in metadata if row["match_format"])
        ),
        "performance": performance,
        "batting": {
            "most_runs": most_runs[0] if most_runs else None,
            "highest_score": highest_score[0] if highest_score else None,
        },
        "bowling": {
            "most_wickets": most_wickets[0] if most_wickets else None,
            "best_figures": best_figures[0] if best_figures else None,
        },
        "matches": match_history,
    }


def get_nepal_match_scorecard(match_id: str) -> dict[str, Any] | None:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT match_id, match_date, match_format, team_1_name, team_2_name,
                   winner_name, margin, margin_type, venue_name, city,
                   tournament_id, tournament_name, season, gender
            FROM nepal_matches
            WHERE match_id = %s
            """,
            [match_id],
        )
        matches = _rows_as_dicts(cursor)
        if not matches:
            return None

        match = matches[0]
        cursor.execute(
            """
            SELECT innings_number, batting_team, total_runs, total_wickets,
                   legal_balls, overs
            FROM nepal_innings_summary
            WHERE match_id = %s
            ORDER BY innings_number
            """,
            [match_id],
        )
        innings = _rows_as_dicts(cursor)
        innings_by_number = {row["innings_number"]: row for row in innings}
        for innings_row in innings:
            innings_row["batting"] = []
            innings_row["bowling"] = []

        cursor.execute(
            """
            SELECT innings_number, batting_position, batsman, dismissal_type,
                   dismissed_by_bowler, dismissed_by_fielder, runs, balls_faced,
                   fours, sixes, strike_rate, is_out, dot_balls,
                   dot_ball_percentage
            FROM nepal_batting_scorecards
            WHERE match_id = %s
            ORDER BY innings_number, batting_position
            """,
            [match_id],
        )
        for batter in _rows_as_dicts(cursor):
            innings_by_number[batter["innings_number"]]["batting"].append(batter)

        cursor.execute(
            """
            SELECT innings_number, bowler, overs_bowled, runs_conceded,
                   wickets, economy, dot_balls, dot_ball_percentage
            FROM nepal_bowling_scorecards
            WHERE match_id = %s
            ORDER BY innings_number, legal_balls_bowled DESC, bowler
            """,
            [match_id],
        )
        for bowler in _rows_as_dicts(cursor):
            innings_by_number[bowler["innings_number"]]["bowling"].append(bowler)

        match["innings"] = innings
        match["outcome"] = _nepal_match_outcome(match)
        match["result"] = _nepal_match_result(match, match["outcome"])
        return match


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
