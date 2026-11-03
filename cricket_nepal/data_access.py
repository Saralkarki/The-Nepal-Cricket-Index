"""Read-only queries for the imported cricket statistics database."""

from typing import Any

from django.db import connections
from django.utils.text import slugify


CRICKET_DATABASE = "cricket"
TEAM_NAME_ALIASES = {
    "Kathmandu Gorkhas": ("Kathmandu Gorkhas", "Kathmandu Gurkhas"),
}


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
            ORDER BY season DESC, tournament_id DESC
            """
        )
        return _rows_as_dicts(cursor)


def get_tournament_overview(tournament_id: int) -> dict[str, Any]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM matches WHERE tournament_id = %s",
            [tournament_id],
        )
        matches_played = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT team_1_name AS team_name
                FROM matches
                WHERE tournament_id = %s
                UNION
                SELECT team_2_name AS team_name
                FROM matches
                WHERE tournament_id = %s
            ) AS participating_teams
            """,
            [tournament_id, tournament_id],
        )
        teams_count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM tournament_players
            WHERE tournament_id = %s
            """,
            [tournament_id],
        )
        players_count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COALESCE(SUM(i.total_runs), 0)
            FROM innings_summary AS i
            JOIN matches AS m ON m.match_id = i.match_id
            WHERE m.tournament_id = %s
            """,
            [tournament_id],
        )
        total_runs = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COALESCE(SUM(wickets), 0)
            FROM bowling_stats_by_tournament
            WHERE tournament_id = %s
            """,
            [tournament_id],
        )
        total_wickets = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT p.player_name, s.total_runs
            FROM batting_stats_by_tournament AS s
            JOIN players AS p ON p.player_id = s.player_id
            WHERE s.tournament_id = %s
            ORDER BY s.total_runs DESC, s.batting_average DESC, p.player_name
            LIMIT 1
            """,
            [tournament_id],
        )
        leading_run_scorer = _rows_as_dicts(cursor)

        cursor.execute(
            """
            SELECT p.player_name, s.wickets
            FROM bowling_stats_by_tournament AS s
            JOIN players AS p ON p.player_id = s.player_id
            WHERE s.tournament_id = %s
            ORDER BY s.wickets DESC, s.economy_rate ASC, p.player_name
            LIMIT 1
            """,
            [tournament_id],
        )
        leading_wicket_taker = _rows_as_dicts(cursor)

    return {
        "matches_played": matches_played,
        "teams_count": teams_count,
        "players_count": players_count,
        "total_runs": total_runs,
        "total_wickets": total_wickets,
        "leading_run_scorer": leading_run_scorer[0] if leading_run_scorer else None,
        "leading_wicket_taker": (
            leading_wicket_taker[0] if leading_wicket_taker else None
        ),
    }


def _npl_points_table(
    matches: list[dict[str, Any]],
    innings_by_match: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not matches:
        return [], None

    if any(not match.get("stage") for match in matches):
        return (
            None,
            "Match stage labels are incomplete, so the points table cannot be derived reliably.",
        )

    teams = {
        team_name
        for match in matches
        for team_name in (match["team_1_name"], match["team_2_name"])
    }
    group_matches = [
        match
        for match in matches
        if " ".join(match["stage"].casefold().replace("-", " ").split())
        in {"round robin", "league stage"}
    ]
    fixtures_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for match in group_matches:
        pair = tuple(sorted((match["team_1_name"], match["team_2_name"])))
        fixtures_by_pair.setdefault(pair, []).append(match)

    expected_round_robin_fixtures = len(teams) * (len(teams) - 1) // 2
    if (
        len(fixtures_by_pair) != expected_round_robin_fixtures
        or len(group_matches) != expected_round_robin_fixtures
        or any(len(fixtures) != 1 for fixtures in fixtures_by_pair.values())
    ):
        return (
            None,
            "Exactly one league-stage match for every team pairing is required to derive the points table.",
        )

    table = {
        team_name: {
            "team_name": team_name,
            "played": 0,
            "won": 0,
            "lost": 0,
            "tied": 0,
            "no_result": 0,
            "points": 0,
            "runs_for": 0,
            "balls_faced": 0,
            "runs_against": 0,
            "balls_bowled": 0,
        }
        for team_name in teams
    }
    for match in group_matches:
        team_1 = match["team_1_name"]
        team_2 = match["team_2_name"]
        first_innings = {
            innings["batting_team"]: innings
            for innings in innings_by_match.get(match["match_id"], [])
            if innings["innings_number"] in (1, 2)
        }
        score_1 = first_innings.get(team_1, {}).get("total_runs")
        score_2 = first_innings.get(team_2, {}).get("total_runs")
        winner = match["winner_name"]

        table[team_1]["played"] += 1
        table[team_2]["played"] += 1
        if winner == team_1:
            table[team_1]["won"] += 1
            table[team_2]["lost"] += 1
            table[team_1]["points"] += 2
        elif winner == team_2:
            table[team_2]["won"] += 1
            table[team_1]["lost"] += 1
            table[team_2]["points"] += 2
        elif score_1 is not None and score_1 == score_2:
            table[team_1]["tied"] += 1
            table[team_2]["tied"] += 1
            table[team_1]["points"] += 1
            table[team_2]["points"] += 1
        else:
            table[team_1]["no_result"] += 1
            table[team_2]["no_result"] += 1
            table[team_1]["points"] += 1
            table[team_2]["points"] += 1
            continue

        for batting_team, bowling_team in ((team_1, team_2), (team_2, team_1)):
            innings = first_innings.get(batting_team)
            if innings is None:
                continue
            legal_balls = innings["legal_balls"] or 0
            balls_for_nrr = (
                120 if innings["total_wickets"] >= 10 else legal_balls
            )
            table[batting_team]["runs_for"] += innings["total_runs"] or 0
            table[batting_team]["balls_faced"] += balls_for_nrr
            table[bowling_team]["runs_against"] += innings["total_runs"] or 0
            table[bowling_team]["balls_bowled"] += balls_for_nrr

    rows = []
    for entry in table.values():
        runs_per_over = (
            entry["runs_for"] * 6 / entry["balls_faced"]
            if entry["balls_faced"]
            else 0
        )
        conceded_per_over = (
            entry["runs_against"] * 6 / entry["balls_bowled"]
            if entry["balls_bowled"]
            else 0
        )
        rows.append(
            {
                **entry,
                "team_slug": slugify(_canonical_team_name(entry["team_name"])),
                "net_run_rate": runs_per_over - conceded_per_over,
            }
        )
    rows.sort(
        key=lambda row: (
            -row["points"],
            -row["net_run_rate"],
            -row["won"],
            row["team_name"],
        )
    )
    return rows, None


def get_npl_tournament_overview(
    tournament_id: int | None = None,
) -> dict[str, Any]:
    tournaments = [
        tournament
        for tournament in get_tournaments()
        if tournament["tournament_name"] == "Nepal Premier League"
    ]
    tournament_ids = [tournament["tournament_id"] for tournament in tournaments]
    if tournament_id is not None and tournament_id not in tournament_ids:
        raise ValueError(f"Unknown NPL tournament id: {tournament_id}")

    if not tournament_ids:
        return {
            "summary": {},
            "points_table": None,
            "points_table_limitation": "No Nepal Premier League records are available.",
            "batting_leaders": {},
            "bowling_leaders": {},
            "statistics": {},
            "recent_matches": [],
            "season_comparison": [],
        }

    selected_ids = tournament_ids
    selected_placeholders = ", ".join(["%s"] * len(selected_ids))
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            f"""
            SELECT m.match_id, m.match_date, m.stage, m.team_1_name, m.team_2_name,
                   m.winner_name, m.margin, m.margin_type, m.venue_name,
                   m.tournament_id, t.season,
                   (
                       SELECT GROUP_CONCAT(p.player_name, ', ')
                       FROM match_player_of_match AS award
                       JOIN players AS p ON p.player_id = award.player_id
                       WHERE award.match_id = m.match_id
                   ) AS player_of_match
            FROM matches AS m
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            WHERE m.tournament_id IN ({selected_placeholders})
            ORDER BY m.match_date DESC, m.match_id DESC
            """,
            selected_ids,
        )
        matches = _rows_as_dicts(cursor)

        cursor.execute(
            f"""
            SELECT i.match_id, i.innings_number, i.total_runs, i.total_wickets,
                   i.legal_balls, i.batting_team
            FROM innings_summary AS i
            JOIN matches AS m ON m.match_id = i.match_id
            WHERE m.tournament_id IN ({selected_placeholders})
            ORDER BY m.match_id, i.innings_number
            """,
            selected_ids,
        )
        innings = _rows_as_dicts(cursor)

        cursor.execute(
            f"""
            SELECT b.match_id, b.innings_number, p.player_id, p.player_name,
                   b.runs, b.balls_faced, b.is_out, b.dot_balls
            FROM batting_scorecards AS b
            JOIN matches AS m ON m.match_id = b.match_id
            JOIN players AS p ON p.player_id = b.player_id
            WHERE m.tournament_id IN ({selected_placeholders})
              AND b.innings_number IN (1, 2)
            """,
            selected_ids,
        )
        all_batting_rows = _rows_as_dicts(cursor)

        cursor.execute(
            f"""
            SELECT b.match_id, b.innings_number, p.player_id, p.player_name,
                   b.wickets, b.runs_conceded, b.legal_balls_bowled,
                   b.dot_balls, b.maidens
            FROM bowling_scorecards AS b
            JOIN matches AS m ON m.match_id = b.match_id
            JOIN players AS p ON p.player_id = b.player_id
            WHERE m.tournament_id IN ({selected_placeholders})
              AND b.innings_number IN (1, 2)
            """,
            selected_ids,
        )
        all_bowling_rows = _rows_as_dicts(cursor)

        cursor.execute(
            f"""
            SELECT tournament_id, COUNT(DISTINCT player_id) AS players
            FROM tournament_players
            WHERE tournament_id IN ({selected_placeholders})
            GROUP BY tournament_id
            """,
            selected_ids,
        )
        player_counts = {
            row["tournament_id"]: row["players"] for row in _rows_as_dicts(cursor)
        }

    match_by_id = {match["match_id"]: match for match in matches}
    selected_matches = [
        match
        for match in matches
        if tournament_id is None or match["tournament_id"] == tournament_id
    ]
    selected_match_ids = {match["match_id"] for match in selected_matches}
    batting_rows = [
        row for row in all_batting_rows if row["match_id"] in selected_match_ids
    ]
    bowling_rows = [
        row for row in all_bowling_rows if row["match_id"] in selected_match_ids
    ]
    innings_by_match: dict[str, list[dict[str, Any]]] = {}
    for row in innings:
        innings_by_match.setdefault(row["match_id"], []).append(row)
    selected_innings = [
        row for row in innings if row["match_id"] in selected_match_ids
    ]
    selected_innings_by_match: dict[str, list[dict[str, Any]]] = {}
    for row in selected_innings:
        selected_innings_by_match.setdefault(row["match_id"], []).append(row)

    summary = {
        "matches": len(selected_matches),
        "teams": len(
            {
                _canonical_team_name(name)
                for match in selected_matches
                for name in (match["team_1_name"], match["team_2_name"])
            }
        ),
        "players": player_counts.get(tournament_id, 0)
        if tournament_id is not None
        else 0,
        "total_runs": sum(
            row["total_runs"] or 0
            for row in selected_innings
            if row["innings_number"] in (1, 2)
        ),
        "total_wickets": sum(
            row["total_wickets"] or 0
            for row in selected_innings
            if row["innings_number"] in (1, 2)
        ),
    }
    if tournament_id is None:
        with connections[CRICKET_DATABASE].cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT player_id)
                FROM tournament_players
                WHERE tournament_id IN ({selected_placeholders})
                """,
                selected_ids,
            )
            summary["players"] = cursor.fetchone()[0]

    first_innings = [
        row for row in selected_innings if row["innings_number"] == 1
    ]
    first_innings_average = (
        sum(row["total_runs"] or 0 for row in first_innings) / len(first_innings)
        if first_innings
        else None
    )
    total_batting_dots = sum(row["dot_balls"] or 0 for row in batting_rows)
    total_batting_balls = sum(row["balls_faced"] or 0 for row in batting_rows)
    total_bowling_dots = sum(row["dot_balls"] or 0 for row in bowling_rows)
    total_bowling_balls = sum(
        row["legal_balls_bowled"] or 0 for row in bowling_rows
    )

    batting_by_player: dict[int, dict[str, Any]] = {}
    for row in batting_rows:
        stats = batting_by_player.setdefault(
            row["player_id"],
            {
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "matches": set(),
                "innings": 0,
                "runs": 0,
                "balls_faced": 0,
                "dismissals": 0,
            },
        )
        stats["matches"].add(row["match_id"])
        stats["innings"] += 1
        stats["runs"] += row["runs"] or 0
        stats["balls_faced"] += row["balls_faced"] or 0
        stats["dismissals"] += row["is_out"] or 0
    for stats in batting_by_player.values():
        stats["matches"] = len(stats["matches"])
        stats["average"] = (
            stats["runs"] / stats["dismissals"] if stats["dismissals"] else None
        )
        stats["strike_rate"] = (
            stats["runs"] * 100 / stats["balls_faced"]
            if stats["balls_faced"]
            else None
        )

    bowling_by_player: dict[int, dict[str, Any]] = {}
    for row in bowling_rows:
        stats = bowling_by_player.setdefault(
            row["player_id"],
            {
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "matches": set(),
                "innings": 0,
                "wickets": 0,
                "runs_conceded": 0,
                "legal_balls": 0,
            },
        )
        stats["matches"].add(row["match_id"])
        stats["innings"] += 1
        stats["wickets"] += row["wickets"] or 0
        stats["runs_conceded"] += row["runs_conceded"] or 0
        stats["legal_balls"] += row["legal_balls_bowled"] or 0
    for stats in bowling_by_player.values():
        stats["matches"] = len(stats["matches"])
        stats["average"] = (
            stats["runs_conceded"] / stats["wickets"] if stats["wickets"] else None
        )
        stats["economy"] = (
            stats["runs_conceded"] * 6 / stats["legal_balls"]
            if stats["legal_balls"]
            else None
        )

    def leaders(
        data: list[dict[str, Any]],
        metric: str,
        *,
        minimum=lambda row: True,
        descending: bool = True,
    ) -> list[dict[str, Any]]:
        eligible = [
            row
            for row in data
            if minimum(row) and row[metric] is not None
        ]
        if not eligible:
            return []
        best = (
            max(row[metric] for row in eligible)
            if descending
            else min(row[metric] for row in eligible)
        )
        return [
            row for row in eligible if abs(row[metric] - best) <= 1e-9
        ]

    best_bowling = []
    bowling_by_innings: dict[tuple[str, int, int], dict[str, Any]] = {}
    for row in bowling_rows:
        key = (row["match_id"], row["innings_number"], row["player_id"])
        stats = bowling_by_innings.setdefault(
            key,
            {
                "match_id": row["match_id"],
                "innings_number": row["innings_number"],
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "wickets": 0,
                "runs_conceded": 0,
            },
        )
        stats["wickets"] += row["wickets"] or 0
        stats["runs_conceded"] += row["runs_conceded"] or 0
    if bowling_by_innings:
        best_figures = max(
            (row["wickets"], -row["runs_conceded"])
            for row in bowling_by_innings.values()
        )
        best_bowling = [
            row
            for row in bowling_by_innings.values()
            if (row["wickets"], -row["runs_conceded"]) == best_figures
        ]
        for row in best_bowling:
            match = match_by_id[row["match_id"]]
            row["match_date"] = match["match_date"]
            bowling_innings = next(
                (
                    innings_row
                    for innings_row in innings_by_match[row["match_id"]]
                    if innings_row["innings_number"]
                    == row["innings_number"]
                ),
                None,
            )
            batting_team = (
                bowling_innings["batting_team"] if bowling_innings else None
            )
            row["opponent"] = batting_team
    selected_matches_oldest_first = sorted(
        selected_matches, key=lambda match: (match["match_date"], match["match_id"])
    )
    points_table, points_limitation = (
        _npl_points_table(selected_matches_oldest_first, selected_innings_by_match)
        if tournament_id is not None
        else (None, None)
    )

    for match in selected_matches:
        match_innings = selected_innings_by_match.get(match["match_id"], [])
        team_scores: dict[str, int] = {}
        for innings_row in match_innings:
            if innings_row["innings_number"] in (1, 2):
                team_scores[innings_row["batting_team"]] = (
                    team_scores.get(innings_row["batting_team"], 0)
                    + (innings_row["total_runs"] or 0)
                )
        match["team_1_score"] = team_scores.get(match["team_1_name"])
        match["team_2_score"] = team_scores.get(match["team_2_name"])
        if match["winner_name"]:
            match["result"] = f'{match["winner_name"]} won'
        elif (
            match["team_1_score"] is not None
            and match["team_1_score"] == match["team_2_score"]
        ):
            match["result"] = "Tied"
        else:
            match["result"] = "No result"

    champions = []
    for match in selected_matches:
        normalized_stage = (
            " ".join(match["stage"].casefold().replace("-", " ").split())
            if match["stage"]
            else ""
        )
        if normalized_stage != "final" or not match["winner_name"]:
            continue
        winner = match["winner_name"]
        opponent = (
            match["team_2_name"]
            if winner == match["team_1_name"]
            else match["team_1_name"]
        )
        champions.append(
            {
                "season": match["season"],
                "team_name": winner,
                "team_slug": slugify(_canonical_team_name(winner)),
                "opponent": opponent,
                "match_id": match["match_id"],
                "match_date": match["match_date"],
                "winner_score": match["team_1_score"]
                if winner == match["team_1_name"]
                else match["team_2_score"],
                "opponent_score": match["team_2_score"]
                if winner == match["team_1_name"]
                else match["team_1_score"],
                "margin": match["margin"],
                "margin_type": match["margin_type"],
            }
        )
    champions.sort(key=lambda champion: champion["match_date"], reverse=True)

    statistics = {
        "average_first_innings_score": first_innings_average,
        "highest_team_total": max(
            (
                row["total_runs"] or 0
                for row in selected_innings
                if row["innings_number"] in (1, 2)
            ),
            default=None,
        ),
        "highest_individual_score": max(
            (row["runs"] or 0 for row in batting_rows), default=None
        ),
        "best_bowling_figures": best_bowling,
        "batting_dot_ball_percentage": (
            total_batting_dots * 100 / total_batting_balls
            if total_batting_balls
            else None
        ),
        "bowling_dot_ball_percentage": (
            total_bowling_dots * 100 / total_bowling_balls
            if total_bowling_balls
            else None
        ),
    }
    recent_matches = sorted(
        selected_matches,
        key=lambda match: (match["match_date"], match["match_id"]),
        reverse=True,
    )[:5]

    comparison = []
    for season in tournaments:
        season_matches = [
            match
            for match in matches
            if match["tournament_id"] == season["tournament_id"]
        ]
        season_innings = [
            row
            for row in innings
            if match_by_id[row["match_id"]]["tournament_id"]
            == season["tournament_id"]
            and row["innings_number"] in (1, 2)
        ]
        season_batting_rows = [
            row
            for row in all_batting_rows
            if match_by_id[row["match_id"]]["tournament_id"]
            == season["tournament_id"]
        ]
        season_bowling_rows = [
            row
            for row in all_bowling_rows
            if match_by_id[row["match_id"]]["tournament_id"]
            == season["tournament_id"]
        ]
        season_table, _ = _npl_points_table(
            sorted(season_matches, key=lambda match: (match["match_date"], match["match_id"])),
            {
                match_id: season_innings
                for match_id, season_innings in innings_by_match.items()
                if match_by_id.get(match_id, {}).get("tournament_id")
                == season["tournament_id"]
            },
        )
        comparison.append(
            {
                "season": season["season"],
                "matches": len(season_matches),
                "total_runs": sum(row["total_runs"] or 0 for row in season_innings),
                "scoring_rate": (
                    sum(row["total_runs"] or 0 for row in season_innings)
                    * 6
                    / sum(row["legal_balls"] or 0 for row in season_innings)
                    if sum(row["legal_balls"] or 0 for row in season_innings)
                    else None
                ),
                "average_first_innings_score": (
                    sum(
                        row["total_runs"] or 0
                        for row in season_innings
                        if row["innings_number"] == 1
                    )
                    / sum(row["innings_number"] == 1 for row in season_innings)
                    if any(row["innings_number"] == 1 for row in season_innings)
                    else None
                ),
                "batting_dot_ball_percentage": (
                    sum(row["dot_balls"] or 0 for row in season_batting_rows)
                    * 100
                    / sum(row["balls_faced"] or 0 for row in season_batting_rows)
                    if sum(row["balls_faced"] or 0 for row in season_batting_rows)
                    else None
                ),
                "bowling_dot_ball_percentage": (
                    sum(row["dot_balls"] or 0 for row in season_bowling_rows)
                    * 100
                    / sum(
                        row["legal_balls_bowled"] or 0
                        for row in season_bowling_rows
                    )
                    if sum(
                        row["legal_balls_bowled"] or 0
                        for row in season_bowling_rows
                    )
                    else None
                ),
                "top_team": (
                    sorted(
                        (
                            row
                            for row in season_table or []
                            if row["won"]
                            == max(candidate["won"] for candidate in season_table)
                        ),
                        key=lambda row: row["team_name"],
                    )
                    if season_table
                    else []
                ),
            }
        )

    return {
        "summary": summary,
        "points_table": points_table,
        "points_table_limitation": points_limitation,
        "batting_leaders": {
            "runs": leaders(list(batting_by_player.values()), "runs"),
            "average": leaders(
                list(batting_by_player.values()),
                "average",
                minimum=lambda row: row["dismissals"] >= 3,
            ),
            "strike_rate": leaders(
                list(batting_by_player.values()),
                "strike_rate",
                minimum=lambda row: row["balls_faced"] >= 60,
            ),
        },
        "bowling_leaders": {
            "wickets": leaders(list(bowling_by_player.values()), "wickets"),
            "economy": leaders(
                list(bowling_by_player.values()),
                "economy",
                minimum=lambda row: row["legal_balls"] >= 72,
                descending=False,
            ),
            "figures": best_bowling,
        },
        "statistics": statistics,
        "recent_matches": recent_matches,
        "champions": champions,
        "season_comparison": comparison,
        "selected_season": next(
            (
                season
                for season in tournaments
                if season["tournament_id"] == tournament_id
            ),
            None,
        ),
        "seasons": tournaments,
    }


def get_teams(tournament_id: int) -> list[str]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT team_name
            FROM (
                SELECT team_1_name AS team_name
                FROM matches
                WHERE tournament_id = %s
                UNION
                SELECT team_2_name AS team_name
                FROM matches
                WHERE tournament_id = %s
            ) AS participating_teams
            ORDER BY team_name
            """,
            [tournament_id, tournament_id],
        )
        return [row[0] for row in cursor.fetchall()]


def _canonical_team_name(team_name: str) -> str:
    for canonical_name, aliases in TEAM_NAME_ALIASES.items():
        if team_name in aliases:
            return canonical_name
    return team_name


def _team_name_aliases(team_name: str) -> tuple[str, ...]:
    canonical_name = _canonical_team_name(team_name)
    return TEAM_NAME_ALIASES.get(canonical_name, (canonical_name,))


def _team_appearance_cte() -> str:
    return """
        WITH team_appearances AS (
            SELECT p.player_id, match_players.tournament_id,
                   match_players.team_name,
                   MAX(CASE WHEN batting.player_id IS NULL THEN 0 ELSE 1 END) AS batting,
                   MAX(CASE WHEN bowling.player_id IS NULL THEN 0 ELSE 1 END) AS bowling
            FROM match_players
            JOIN players AS p
              ON p.cricsheet_player_id = match_players.cricsheet_player_id
            LEFT JOIN (
                SELECT DISTINCT match_id, player_id
                FROM batting_scorecards
            ) AS batting
              ON batting.match_id = CAST(match_players.match_id AS TEXT)
             AND batting.player_id = p.player_id
            LEFT JOIN (
                SELECT DISTINCT match_id, player_id
                FROM bowling_scorecards
            ) AS bowling
              ON bowling.match_id = CAST(match_players.match_id AS TEXT)
             AND bowling.player_id = p.player_id
            GROUP BY p.player_id, match_players.tournament_id,
                     match_players.team_name
        )
    """


def _ranked_team_leaders(
    rows: list[dict[str, Any]], metric: str, *, highest_is_best: bool
) -> list[dict[str, Any]]:
    eligible = [row for row in rows if row[metric] is not None]
    if not eligible:
        return []
    best = (
        max(row[metric] for row in eligible)
        if highest_is_best
        else min(row[metric] for row in eligible)
    )
    return [
        row
        for row in eligible
        if abs(row[metric] - best) <= 1e-9
    ]


def _team_match_outcome(
    match: dict[str, Any], aliases: tuple[str, ...]
) -> tuple[str, str]:
    if match["winner_name"] is not None:
        if match["winner_name"] in aliases:
            return "Won", "win"
        return "Lost", "loss"
    if (
        (match["margin_type"] or "").lower() == "tie"
        or (
            match["team_score"] is not None
            and match["team_score"] == match["opponent_score"]
        )
    ):
        return "Tied", "neutral"
    return "No result", "neutral"


def get_team_directory() -> list[dict[str, Any]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT m.tournament_id, t.season, m.team_1_name, m.team_2_name,
                   m.winner_name
            FROM matches AS m
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            ORDER BY t.season DESC, m.match_date DESC
            """
        )
        matches = _rows_as_dicts(cursor)

        cursor.execute(
            _team_appearance_cte()
            + """
            SELECT tournament_id, team_name, player_id
            FROM team_appearances
            WHERE team_name IS NOT NULL AND (batting = 1 OR bowling = 1)
            """
        )
        player_rows = _rows_as_dicts(cursor)

    teams_by_name: dict[str, dict[str, Any]] = {}
    for match in matches:
        for raw_name in {match["team_1_name"], match["team_2_name"]}:
            name = _canonical_team_name(raw_name)
            team = teams_by_name.setdefault(
                name,
                {
                    "team_name": name,
                    "team_slug": slugify(name),
                    "seasons": [],
                    "participations": {},
                    "matches_played": 0,
                    "wins": 0,
                    "losses": 0,
                    "recorded_player_ids": set(),
                },
            )
            team["participations"][match["tournament_id"]] = match["season"]
            team["matches_played"] += 1
            if match["winner_name"] in _team_name_aliases(name):
                team["wins"] += 1
            elif match["winner_name"] is not None:
                team["losses"] += 1

    for row in player_rows:
        team = teams_by_name.get(_canonical_team_name(row["team_name"]))
        if team is not None:
            team["recorded_player_ids"].add(row["player_id"])

    for team in teams_by_name.values():
        team["participations"] = [
            {"tournament_id": tournament_id, "season": season}
            for tournament_id, season in sorted(
                team["participations"].items(),
                key=lambda participation: participation[1],
                reverse=True,
            )
        ]
        team["seasons"] = [
            participation["season"] for participation in team["participations"]
        ]
        team["players_with_recorded_appearances"] = len(
            team.pop("recorded_player_ids")
        )
    return sorted(teams_by_name.values(), key=lambda team: team["team_name"])


def _build_npl_team_directory(
    matches: list[dict[str, Any]],
    seasons: list[dict[str, Any]],
    tournament_id: int | None = None,
) -> dict[str, Any]:
    if tournament_id is not None:
        matches = [
            match for match in matches if match["tournament_id"] == tournament_id
        ]

    teams_by_key: dict[tuple[str, int | None], dict[str, Any]] = {}
    for match in matches:
        for raw_name in {match["team_1_name"], match["team_2_name"]}:
            franchise_name = _canonical_team_name(raw_name)
            key = (
                franchise_name,
                match["tournament_id"] if tournament_id is not None else None,
            )
            card = teams_by_key.setdefault(
                key,
                {
                    "team_name": (
                        raw_name if tournament_id is not None else franchise_name
                    ),
                    "team_slug": slugify(franchise_name),
                    "franchise_name": franchise_name,
                    "matches_played": 0,
                    "wins": 0,
                    "losses": 0,
                    "titles": 0,
                },
            )
            card["matches_played"] += 1
            if match["winner_name"] in _team_name_aliases(franchise_name):
                card["wins"] += 1
            elif match["winner_name"] is not None:
                card["losses"] += 1

            if (
                match["stage"]
                and match["stage"].strip().casefold() == "final"
                and match["winner_name"] in _team_name_aliases(franchise_name)
            ):
                card["titles"] += 1

    for card in teams_by_key.values():
        decisions = card["wins"] + card["losses"]
        card["win_percentage"] = (
            card["wins"] * 100 / decisions if decisions else None
        )

    return {
        "teams": sorted(
            teams_by_key.values(),
            key=lambda card: card["franchise_name"],
        ),
        "seasons": seasons,
        "selected_season": next(
            (
                season
                for season in seasons
                if season["tournament_id"] == tournament_id
            ),
            None,
        ),
    }


def get_npl_team_directory(
    tournament_id: int | None = None,
) -> dict[str, Any]:
    seasons = [
        tournament
        for tournament in get_tournaments()
        if tournament["tournament_name"] == "Nepal Premier League"
    ]
    tournament_ids = [season["tournament_id"] for season in seasons]
    if tournament_id is not None and tournament_id not in tournament_ids:
        raise ValueError(f"Unknown NPL tournament id: {tournament_id}")

    if not tournament_ids:
        return {"teams": [], "seasons": [], "selected_season": None}

    selected_ids = (
        [tournament_id] if tournament_id is not None else tournament_ids
    )
    placeholders = ", ".join(["%s"] * len(selected_ids))
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            f"""
            SELECT m.match_id, m.tournament_id, t.season,
                   m.team_1_name, m.team_2_name, m.winner_name, m.stage
            FROM matches AS m
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            WHERE m.tournament_id IN ({placeholders})
            ORDER BY t.season DESC, m.match_date, m.match_id
            """,
            selected_ids,
        )
        matches = _rows_as_dicts(cursor)

    return _build_npl_team_directory(matches, seasons, tournament_id)


def get_team_profile(
    team_name: str, tournament_id: int | None = None
) -> dict[str, Any] | None:
    team_name = _canonical_team_name(team_name)
    aliases = _team_name_aliases(team_name)
    placeholders = ", ".join(["%s"] * len(aliases))
    season_filter = "(%s IS NULL OR m.tournament_id = %s)"

    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            f"""
            SELECT m.match_id, m.match_date, m.team_1_name, m.team_2_name,
                   m.winner_name, m.margin, m.margin_type, m.venue_name,
                   m.tournament_id, t.season,
                   (
                       SELECT SUM(i.total_runs)
                       FROM innings_summary AS i
                       WHERE i.match_id = m.match_id
                         AND i.batting_team IN ({placeholders})
                   ) AS team_score,
                   (
                       SELECT SUM(i.total_runs)
                       FROM innings_summary AS i
                       WHERE i.match_id = m.match_id
                         AND i.batting_team NOT IN ({placeholders})
                   ) AS opponent_score,
                   (
                       SELECT GROUP_CONCAT(p.player_name, ', ')
                       FROM match_player_of_match AS award
                       JOIN players AS p ON p.player_id = award.player_id
                       WHERE award.match_id = m.match_id
                   ) AS player_of_match
            FROM matches AS m
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            WHERE (m.team_1_name IN ({placeholders})
                   OR m.team_2_name IN ({placeholders}))
              AND {season_filter}
            ORDER BY m.match_date DESC, m.match_id DESC
            """,
            [
                *aliases,
                *aliases,
                *aliases,
                *aliases,
                tournament_id,
                tournament_id,
            ],
        )
        matches = _rows_as_dicts(cursor)
        if not matches:
            known_team = any(
                team["team_name"] == team_name for team in get_team_directory()
            )
            if not known_team:
                return None

        for match in matches:
            raw_opponent = (
                match["team_2_name"]
                if match["team_1_name"] in aliases
                else match["team_1_name"]
            )
            match["opponent"] = raw_opponent
            match["opponent_slug"] = slugify(_canonical_team_name(raw_opponent))
            match["result"], match["result_class"] = _team_match_outcome(
                match, aliases
            )
            match["winning_margin"] = (
                f'{match["margin"]} '
                f'{"wickets" if match["margin_type"] == "wkts" else match["margin_type"]}'
                if match["margin"] is not None and match["margin_type"]
                else None
            )

        cursor.execute(
            f"""
            SELECT COALESCE(SUM(i.total_runs), 0) AS total_runs,
                   COALESCE(SUM(i.total_wickets), 0) AS wickets_lost,
                   COUNT(*) AS innings,
                   COALESCE(SUM(i.legal_balls), 0) AS legal_balls
            FROM innings_summary AS i
            JOIN matches AS m ON m.match_id = i.match_id
            WHERE i.batting_team IN ({placeholders})
              AND {season_filter}
            """,
            [*aliases, tournament_id, tournament_id],
        )
        batting_innings = _rows_as_dicts(cursor)[0]

        cursor.execute(
            f"""
            SELECT COALESCE(SUM(b.fours), 0) AS fours,
                   COALESCE(SUM(b.sixes), 0) AS sixes,
                   COALESCE(SUM(b.dot_balls), 0) AS dot_balls,
                   COALESCE(SUM(b.balls_faced), 0) AS balls_faced
            FROM batting_scorecards AS b
            JOIN innings_summary AS i
              ON i.match_id = b.match_id AND i.innings_number = b.innings_number
            JOIN matches AS m ON m.match_id = b.match_id
            WHERE i.batting_team IN ({placeholders})
              AND {season_filter}
            """,
            [*aliases, tournament_id, tournament_id],
        )
        batting_extras = _rows_as_dicts(cursor)[0]

        cursor.execute(
            f"""
            SELECT COALESCE(SUM(b.wickets), 0) AS wickets,
                   COALESCE(SUM(b.runs_conceded), 0) AS runs_conceded,
                   COALESCE(SUM(b.legal_balls_bowled), 0) AS legal_balls,
                   COALESCE(SUM(b.maidens), 0) AS maidens,
                   COALESCE(SUM(b.dot_balls), 0) AS dot_balls
            FROM bowling_scorecards AS b
            JOIN innings_summary AS i
              ON i.match_id = b.match_id AND i.innings_number = b.innings_number
            JOIN matches AS m ON m.match_id = b.match_id
            WHERE CASE
                      WHEN i.batting_team = m.team_1_name THEN m.team_2_name
                      WHEN i.batting_team = m.team_2_name THEN m.team_1_name
                  END IN ({placeholders})
              AND {season_filter}
            """,
            [*aliases, tournament_id, tournament_id],
        )
        bowling = _rows_as_dicts(cursor)[0]

        cursor.execute(
            f"""
            SELECT DISTINCT p.player_id, p.player_name
            FROM match_players AS mp
            JOIN players AS p ON p.cricsheet_player_id = mp.cricsheet_player_id
            WHERE mp.team_name IN ({placeholders})
              AND (%s IS NULL OR mp.tournament_id = %s)
            GROUP BY p.player_id, p.player_name
            ORDER BY lower(p.player_name), p.player_id
            """,
            [*aliases, tournament_id, tournament_id],
        )
        players = _rows_as_dicts(cursor)

        cursor.execute(
            f"""
            SELECT p.player_id,
                   p.player_name,
                   COUNT(DISTINCT b.match_id) AS matches,
                   COUNT(b.match_id) AS innings,
                   COALESCE(SUM(b.runs), 0) AS runs,
                   COALESCE(SUM(b.balls_faced), 0) AS balls_faced,
                   COALESCE(SUM(b.is_out), 0) AS dismissals,
                   COALESCE(SUM(b.fours), 0) AS fours,
                   COALESCE(SUM(b.sixes), 0) AS sixes
            FROM match_players AS mp
            JOIN players AS p ON p.cricsheet_player_id = mp.cricsheet_player_id
            JOIN batting_scorecards AS b
              ON b.player_id = p.player_id
             AND b.match_id = CAST(mp.match_id AS TEXT)
            WHERE mp.team_name IN ({placeholders})
              AND (%s IS NULL OR mp.tournament_id = %s)
            GROUP BY p.player_id, p.player_name
            """,
            [*aliases, tournament_id, tournament_id],
        )
        batting_players = _rows_as_dicts(cursor)

        cursor.execute(
            f"""
            SELECT p.player_id,
                   p.player_name,
                   COUNT(DISTINCT b.match_id) AS matches,
                   COUNT(b.match_id) AS innings,
                   COALESCE(SUM(b.wickets), 0) AS wickets,
                   COALESCE(SUM(b.runs_conceded), 0) AS runs_conceded,
                   COALESCE(SUM(b.legal_balls_bowled), 0) AS legal_balls,
                   COALESCE(SUM(b.maidens), 0) AS maidens
            FROM match_players AS mp
            JOIN players AS p ON p.cricsheet_player_id = mp.cricsheet_player_id
            JOIN bowling_scorecards AS b
              ON b.player_id = p.player_id
             AND b.match_id = CAST(mp.match_id AS TEXT)
            WHERE mp.team_name IN ({placeholders})
              AND (%s IS NULL OR mp.tournament_id = %s)
            GROUP BY p.player_id, p.player_name
            """,
            [*aliases, tournament_id, tournament_id],
        )
        bowling_players = _rows_as_dicts(cursor)

        cursor.execute(
            f"""
            SELECT p.player_id, COUNT(DISTINCT appearances.match_id) AS matches
            FROM match_players AS mp
            JOIN players AS p ON p.cricsheet_player_id = mp.cricsheet_player_id
            JOIN (
                SELECT match_id, player_id FROM batting_scorecards
                UNION
                SELECT match_id, player_id FROM bowling_scorecards
            ) AS appearances
              ON appearances.match_id = CAST(mp.match_id AS TEXT)
             AND appearances.player_id = p.player_id
            WHERE mp.team_name IN ({placeholders})
              AND (%s IS NULL OR mp.tournament_id = %s)
            GROUP BY p.player_id
            """,
            [*aliases, tournament_id, tournament_id],
        )
        scorecard_matches = {
            row["player_id"]: row["matches"] for row in _rows_as_dicts(cursor)
        }

        batting_leader_rows = batting_players
        for row in batting_leader_rows:
            row["average"] = (
                row["runs"] / row["dismissals"] if row["dismissals"] else None
            )
            row["strike_rate"] = (
                row["runs"] * 100 / row["balls_faced"]
                if row["balls_faced"]
                else None
            )

        bowling_leader_rows = bowling_players
        for row in bowling_leader_rows:
            row["average"] = (
                row["runs_conceded"] / row["wickets"] if row["wickets"] else None
            )
            row["economy"] = (
                row["runs_conceded"] * 6 / row["legal_balls"]
                if row["legal_balls"]
                else None
            )
            row["strike_rate"] = (
                row["legal_balls"] / row["wickets"] if row["wickets"] else None
            )

        cursor.execute(
            f"""
            SELECT p.player_id, p.player_name, b.match_id, m.match_date,
                   CASE
                       WHEN m.team_1_name IN ({placeholders}) THEN m.team_2_name
                       ELSE m.team_1_name
                   END AS opponent,
                   SUM(b.wickets) AS wickets,
                   SUM(b.runs_conceded) AS runs_conceded,
                   COUNT(b.match_id) AS innings
            FROM match_players AS mp
            JOIN players AS p ON p.cricsheet_player_id = mp.cricsheet_player_id
            JOIN bowling_scorecards AS b
              ON b.player_id = p.player_id
             AND b.match_id = CAST(mp.match_id AS TEXT)
            JOIN matches AS m ON m.match_id = b.match_id
            WHERE mp.team_name IN ({placeholders})
              AND (%s IS NULL OR mp.tournament_id = %s)
            GROUP BY p.player_id, p.player_name, b.match_id, m.match_date,
                     m.team_1_name, m.team_2_name
            """,
            [*aliases, *aliases, tournament_id, tournament_id],
        )
        bowling_figures = _rows_as_dicts(cursor)
        if bowling_figures:
            best_figures = max(
                (row["wickets"], -row["runs_conceded"])
                for row in bowling_figures
            )
            bowling_figures = [
                row
                for row in bowling_figures
                if (row["wickets"], -row["runs_conceded"]) == best_figures
            ]
            bowling_figures.sort(
                key=lambda row: (
                    row["match_date"],
                    row["match_id"],
                    row["player_name"].lower(),
                ),
                reverse=True,
            )

        cursor.execute(
            f"""
            SELECT DISTINCT t.tournament_id, t.season
            FROM matches AS m
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            WHERE m.team_1_name IN ({placeholders})
               OR m.team_2_name IN ({placeholders})
            ORDER BY t.season DESC, t.tournament_id DESC
            """,
            [*aliases, *aliases],
        )
        seasons = _rows_as_dicts(cursor)

    batting_player_metrics = {
        row["player_id"]: row for row in batting_players
    }
    bowling_player_metrics = {
        row["player_id"]: row for row in bowling_players
    }
    for player in players:
        player["matches"] = scorecard_matches.get(player["player_id"], 0)
        player["runs"] = batting_player_metrics.get(player["player_id"], {}).get(
            "runs", 0
        )
        player["wickets"] = bowling_player_metrics.get(
            player["player_id"], {}
        ).get("wickets", 0)

    batting = {
        **batting_innings,
        **batting_extras,
        "average": (
            batting_innings["total_runs"] / batting_innings["wickets_lost"]
            if batting_innings["wickets_lost"]
            else None
        ),
        "strike_rate": (
            batting_innings["total_runs"] * 100 / batting_extras["balls_faced"]
            if batting_extras["balls_faced"]
            else None
        ),
        "average_runs_per_innings": (
            batting_innings["total_runs"] / batting_innings["innings"]
            if batting_innings["innings"]
            else None
        ),
        "run_rate": (
            batting_innings["total_runs"] * 6 / batting_innings["legal_balls"]
            if batting_innings["legal_balls"]
            else None
        ),
        "dot_ball_percentage": (
            batting_extras["dot_balls"] * 100 / batting_extras["balls_faced"]
            if batting_extras["balls_faced"]
            else None
        ),
    }
    bowling.update(
        {
            "average": (
                bowling["runs_conceded"] / bowling["wickets"]
                if bowling["wickets"]
                else None
            ),
            "economy": (
                bowling["runs_conceded"] * 6 / bowling["legal_balls"]
                if bowling["legal_balls"]
                else None
            ),
            "strike_rate": (
                bowling["legal_balls"] / bowling["wickets"]
                if bowling["wickets"]
                else None
            ),
            "dot_ball_percentage": (
                bowling["dot_balls"] * 100 / bowling["legal_balls"]
                if bowling["legal_balls"]
                else None
            ),
        }
    )
    wins = sum(match["result"] == "Won" for match in matches)
    losses = sum(match["result"] == "Lost" for match in matches)
    ties = sum(match["result"] == "Tied" for match in matches)
    decision_matches = wins + losses + ties
    batting_average_qualifiers = [
        row for row in batting_leader_rows if row["dismissals"] >= 3
    ]
    batting_strike_rate_qualifiers = [
        row for row in batting_leader_rows if row["balls_faced"] >= 60
    ]
    bowling_economy_qualifiers = [
        row for row in bowling_leader_rows if row["legal_balls"] >= 72
    ]
    recent_form = sorted(
        matches,
        key=lambda match: (match["match_date"], match["match_id"]),
        reverse=True,
    )[:5]
    for match in recent_form:
        if match["winning_margin"]:
            match["recent_summary"] = (
                f'{match["result"]} by {match["winning_margin"]}'
                if match["result"] in {"Won", "Lost"}
                else f'{match["result"]} · {match["winning_margin"]}'
            )
        else:
            match["recent_summary"] = match["result"]
    display_team_name = team_name
    if tournament_id is not None and matches:
        historical_name = next(
            (
                name
                for match in matches
                for name in (match["team_1_name"], match["team_2_name"])
                if name in aliases
            ),
            None,
        )
        if historical_name:
            display_team_name = historical_name
    return {
        "team_name": display_team_name,
        "franchise_name": team_name,
        "team_slug": slugify(team_name),
        "is_kathmandu_brand_change": team_name == "Kathmandu Gorkhas",
        "seasons": seasons,
        "matches": matches,
        "recent_form": recent_form,
        "matches_played": len(matches),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "no_results": sum(match["result"] == "No result" for match in matches),
        "win_percentage": (
            wins * 100 / decision_matches if decision_matches else None
        ),
        "batting": batting,
        "bowling": bowling,
        "players": players,
        "top_batting": {
            "runs": _ranked_team_leaders(
                batting_leader_rows, "runs", highest_is_best=True
            ),
            "average": _ranked_team_leaders(
                batting_average_qualifiers, "average", highest_is_best=True
            ),
            "strike_rate": _ranked_team_leaders(
                batting_strike_rate_qualifiers,
                "strike_rate",
                highest_is_best=True,
            ),
        },
        "top_bowling": {
            "wickets": _ranked_team_leaders(
                bowling_leader_rows, "wickets", highest_is_best=True
            ),
            "economy": _ranked_team_leaders(
                bowling_economy_qualifiers, "economy", highest_is_best=False
            ),
            "figures": bowling_figures,
        },
    }


def get_matches(
    tournament_id: int, team_name: str | None = None
) -> list[dict[str, Any]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT m.match_id, m.match_date, m.team_1_name, m.team_2_name,
                   m.winner_name, m.margin, m.margin_type, m.venue_name,
                   (
                       SELECT GROUP_CONCAT(p.player_name, ', ')
                       FROM match_player_of_match AS award
                       JOIN players AS p ON p.player_id = award.player_id
                       WHERE award.match_id = m.match_id
                   ) AS player_of_match
            FROM matches AS m
            WHERE m.tournament_id = %s
              AND (
                  %s IS NULL
                  OR m.team_1_name = %s
                  OR m.team_2_name = %s
              )
            ORDER BY m.match_date DESC, m.match_id DESC
            """,
            [tournament_id, team_name, team_name, team_name],
        )
        return _rows_as_dicts(cursor)


def get_match_scorecard(match_id: str) -> dict[str, Any] | None:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT m.match_id, m.match_date, m.match_format, m.team_1_name,
                   m.team_2_name, m.winner_name, m.margin, m.margin_type,
                   m.venue_name, m.city, m.toss_winner_name, m.toss_decision,
                   m.tournament_id, t.tournament_name, t.season,
                   (
                       SELECT GROUP_CONCAT(p.player_name, ', ')
                       FROM match_player_of_match AS award
                       JOIN players AS p ON p.player_id = award.player_id
                       WHERE award.match_id = m.match_id
                   ) AS player_of_match
            FROM matches AS m
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            WHERE m.match_id = %s
            """,
            [match_id],
        )
        matches = _rows_as_dicts(cursor)
        if not matches:
            return None

        match = matches[0]
        match["team_1_slug"] = slugify(_canonical_team_name(match["team_1_name"]))
        match["team_2_slug"] = slugify(_canonical_team_name(match["team_2_name"]))
        match["winner_slug"] = (
            slugify(_canonical_team_name(match["winner_name"]))
            if match["winner_name"]
            else None
        )
        match["toss_winner_slug"] = (
            slugify(_canonical_team_name(match["toss_winner_name"]))
            if match["toss_winner_name"]
            else None
        )
        cursor.execute(
            """
            SELECT innings_number, total_runs, total_wickets, legal_balls, overs,
                   batting_team
            FROM innings_summary
            WHERE match_id = %s
            ORDER BY innings_number
            """,
            [match_id],
        )
        innings = _rows_as_dicts(cursor)
        innings_by_number = {row["innings_number"]: row for row in innings}

        for innings_row in innings:
            innings_row["batting_team_slug"] = (
                slugify(_canonical_team_name(innings_row["batting_team"]))
                if innings_row["batting_team"]
                else None
            )
            innings_row["batting"] = []
            innings_row["bowling"] = []

        cursor.execute(
            """
            SELECT b.innings_number, b.batting_position, b.player_id, p.player_name,
                   b.dismissal_type, b.dismissed_by_bowler,
                   b.dismissed_by_fielder, b.runs, b.balls_faced,
                   b.fours, b.sixes, b.strike_rate, b.is_out,
                   b.dot_balls, b.dot_ball_percentage
            FROM batting_scorecards AS b
            JOIN players AS p ON p.player_id = b.player_id
            WHERE b.match_id = %s
            ORDER BY b.innings_number, b.batting_position
            """,
            [match_id],
        )
        for row in _rows_as_dicts(cursor):
            innings_by_number[row["innings_number"]]["batting"].append(row)

        cursor.execute(
            """
            SELECT b.innings_number, b.player_id, p.player_name, b.overs_bowled,
                   b.runs_conceded, b.wickets, b.economy,
                   b.dot_balls, b.dot_ball_percentage
            FROM bowling_scorecards AS b
            JOIN players AS p ON p.player_id = b.player_id
            WHERE b.match_id = %s
            ORDER BY b.innings_number, b.legal_balls_bowled DESC, p.player_name
            """,
            [match_id],
        )
        for row in _rows_as_dicts(cursor):
            innings_by_number[row["innings_number"]]["bowling"].append(row)

        match["innings"] = innings
        return match


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


def _player_team_evidence_cte() -> str:
    return """
        WITH player_teams AS (
            SELECT DISTINCT p.player_id, match_players.tournament_id,
                            match_players.team_name
            FROM match_players
            JOIN players AS p
              ON p.cricsheet_player_id = match_players.cricsheet_player_id
        )
    """


def get_player_directory(search_term: str = "") -> list[dict[str, Any]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            _player_team_evidence_cte()
            + """
            SELECT p.player_id, p.player_name, t.tournament_id, t.season,
                   player_teams.team_name
            FROM players AS p
            LEFT JOIN player_teams
              ON player_teams.player_id = p.player_id
            LEFT JOIN tournaments AS t
              ON t.tournament_id = player_teams.tournament_id
            WHERE (%s = '' OR instr(lower(p.player_name), lower(%s)) > 0)
            ORDER BY lower(p.player_name), p.player_id, t.season DESC,
                     player_teams.team_name
            """,
            [search_term, search_term],
        )
        rows = _rows_as_dicts(cursor)

    players_by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        player = players_by_id.setdefault(
            row["player_id"],
            {
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "participations": {},
            },
        )
        if row["tournament_id"] is None:
            continue
        participation = player["participations"].setdefault(
            row["tournament_id"],
            {
                "season": row["season"],
                "teams": set(),
            },
        )
        if row["team_name"]:
            participation["teams"].add(row["team_name"])

    result = []
    for player in players_by_id.values():
        participations = sorted(
            (
                {
                    "season": participation["season"],
                    "teams": sorted(participation["teams"]),
                }
                for participation in player["participations"].values()
            ),
            key=lambda participation: participation["season"],
            reverse=True,
        )
        result.append(
            {
                "player_id": player["player_id"],
                "player_name": player["player_name"],
                "participations": participations,
            }
        )
    return result


def _sum_metric(rows: list[dict[str, Any]], column: str) -> int | float | None:
    values = [row[column] for row in rows if row[column] is not None]
    return sum(values) if values else None


def _ratio(numerator: int | float | None, denominator: int | float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _resolve_player_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    conflicts = {
        "bowling_attribute": bool(attributes["bowling_attribute_conflict"]),
        "batting_attribute": bool(attributes["batting_attribute_conflict"]),
        "is_wicketkeeper": bool(attributes["is_wicketkeeper_conflict"]),
    }
    return {
        "bowling_attribute": (
            None if conflicts["bowling_attribute"] else attributes["bowling_attribute"]
        ),
        "batting_attribute": (
            None if conflicts["batting_attribute"] else attributes["batting_attribute"]
        ),
        "is_wicketkeeper": (
            None
            if conflicts["is_wicketkeeper"] or attributes["is_wicketkeeper"] is None
            else bool(attributes["is_wicketkeeper"])
        ),
        "conflicts": conflicts,
    }


def get_player_profile(player_id: int) -> dict[str, Any] | None:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT player_id, player_name, cricsheet_player_id
            FROM players
            WHERE player_id = %s
            """,
            [player_id],
        )
        player_rows = _rows_as_dicts(cursor)
        if not player_rows:
            return None
        player = player_rows[0]

        cursor.execute(
            """
            SELECT t.tournament_id, t.season,
                   batting.matches_played AS batting_matches_played,
                   batting.innings_played, batting.times_out, batting.total_runs,
                   batting.highest_score, batting.total_balls_faced,
                   batting.total_dot_balls, batting.total_fours, batting.total_sixes,
                   batting.batting_average, batting.batting_strike_rate,
                   batting.dot_ball_percentage,
                   bowling.matches_played AS bowling_matches_played,
                   bowling.innings_bowled, bowling.total_legal_balls,
                   bowling.runs_conceded, bowling.wickets,
                   bowling.bowling_average, bowling.economy_rate,
                   bowling.bowling_strike_rate, bowling.maidens,
                   bowling.total_dot_balls AS bowling_dot_balls,
                   bowling.dot_ball_percentage AS bowling_dot_ball_percentage
            FROM tournament_players AS tp
            JOIN tournaments AS t ON t.tournament_id = tp.tournament_id
            LEFT JOIN batting_stats_by_tournament AS batting
              ON batting.tournament_id = tp.tournament_id
             AND batting.player_id = tp.player_id
            LEFT JOIN bowling_stats_by_tournament AS bowling
              ON bowling.tournament_id = tp.tournament_id
             AND bowling.player_id = tp.player_id
            WHERE tp.player_id = %s
            ORDER BY t.season DESC, t.tournament_id DESC
            """,
            [player_id],
        )
        season_stats = _rows_as_dicts(cursor)

        cursor.execute(
            """
            SELECT tournament_id, match_id
            FROM (
                SELECT m.tournament_id, b.match_id
                FROM batting_scorecards AS b
                JOIN matches AS m ON m.match_id = b.match_id
                WHERE b.player_id = %s
                UNION
                SELECT m.tournament_id, b.match_id
                FROM bowling_scorecards AS b
                JOIN matches AS m ON m.match_id = b.match_id
                WHERE b.player_id = %s
            ) AS player_matches
            """,
            [player_id, player_id],
        )
        match_rows = _rows_as_dicts(cursor)

        cursor.execute(
            """
            WITH player_tournaments AS (
                SELECT tournament_id
                FROM tournament_players
                WHERE player_id = %s
                UNION
                SELECT match_players.tournament_id
                FROM match_players
                WHERE cricsheet_player_id = %s
            )
            SELECT player_tournaments.tournament_id, t.season,
                   match_players.team_name
            FROM player_tournaments
            JOIN tournaments AS t
              ON t.tournament_id = player_tournaments.tournament_id
            LEFT JOIN match_players
              ON match_players.tournament_id = player_tournaments.tournament_id
             AND match_players.cricsheet_player_id = %s
            ORDER BY t.season DESC, match_players.team_name
            """,
            [player_id, player["cricsheet_player_id"], player["cricsheet_player_id"]],
        )
        team_rows = _rows_as_dicts(cursor)

        cursor.execute(
            """
            SELECT MIN(bowling_attribute) AS bowling_attribute,
                   MIN(batting_attribute) AS batting_attribute,
                   MIN(is_wicketkeeper) AS is_wicketkeeper,
                   COUNT(DISTINCT bowling_attribute) > 1
                       AS bowling_attribute_conflict,
                   COUNT(DISTINCT batting_attribute) > 1
                       AS batting_attribute_conflict,
                   COUNT(DISTINCT is_wicketkeeper) > 1
                       AS is_wicketkeeper_conflict
            FROM match_players
            WHERE cricsheet_player_id = %s
            """,
            [player["cricsheet_player_id"]],
        )
        attributes = _rows_as_dicts(cursor)[0]

    match_counts: dict[int, int] = {}
    for row in match_rows:
        match_counts[row["tournament_id"]] = (
            match_counts.get(row["tournament_id"], 0) + 1
        )
    participation_by_tournament = {
        row["tournament_id"]: {
            "tournament_id": row["tournament_id"],
            "season": row["season"],
            "teams": set(),
        }
        for row in season_stats
    }
    for row in team_rows:
        participation = participation_by_tournament.setdefault(
            row["tournament_id"],
            {
                "tournament_id": row["tournament_id"],
                "season": row["season"],
                "teams": set(),
            },
        )
        if row["team_name"]:
            participation["teams"].add(row["team_name"])
    participations = sorted(
        (
            {
                **participation,
                "teams": sorted(participation["teams"]),
            }
            for participation in participation_by_tournament.values()
        ),
        key=lambda participation: (participation["season"], participation["tournament_id"]),
        reverse=True,
    )
    for row in season_stats:
        row["matches_played"] = match_counts.get(row["tournament_id"], 0)
        row["has_batting_stats"] = row["total_runs"] is not None
        row["has_bowling_stats"] = row["wickets"] is not None

    batting_rows = [row for row in season_stats if row["total_runs"] is not None]
    total_runs = _sum_metric(batting_rows, "total_runs")
    total_balls_faced = _sum_metric(batting_rows, "total_balls_faced")
    total_batting_dots = _sum_metric(batting_rows, "total_dot_balls")
    total_dismissals = _sum_metric(batting_rows, "times_out")
    batting_overall = {
        "runs": total_runs,
        "average": _ratio(total_runs, total_dismissals),
        "strike_rate": (
            _ratio(total_runs * 100, total_balls_faced)
            if total_runs is not None
            else None
        ),
        "highest_score": max(
            (row["highest_score"] for row in batting_rows if row["highest_score"] is not None),
            default=None,
        ),
        "fours": _sum_metric(batting_rows, "total_fours"),
        "sixes": _sum_metric(batting_rows, "total_sixes"),
        "dot_balls": total_batting_dots,
        "dot_ball_percentage": (
            _ratio(total_batting_dots * 100, total_balls_faced)
            if total_batting_dots is not None
            else None
        ),
    }

    bowling_rows = [row for row in season_stats if row["wickets"] is not None]
    bowling_runs = _sum_metric(bowling_rows, "runs_conceded")
    bowling_wickets = _sum_metric(bowling_rows, "wickets")
    total_legal_balls = _sum_metric(bowling_rows, "total_legal_balls")
    total_bowling_dots = _sum_metric(bowling_rows, "bowling_dot_balls")
    bowling_overall = {
        "wickets": bowling_wickets,
        "average": _ratio(bowling_runs, bowling_wickets),
        "economy": (
            _ratio(bowling_runs * 6, total_legal_balls)
            if bowling_runs is not None
            else None
        ),
        "strike_rate": _ratio(total_legal_balls, bowling_wickets),
        "maidens": _sum_metric(bowling_rows, "maidens"),
        "dot_balls": total_bowling_dots,
        "dot_ball_percentage": (
            _ratio(total_bowling_dots * 100, total_legal_balls)
            if total_bowling_dots is not None
            else None
        ),
    }
    return {
        "player_id": player["player_id"],
        "player_name": player["player_name"],
        "participations": participations,
        "attributes": _resolve_player_attributes(attributes),
        "season_stats": season_stats,
        "matches_played": sum(match_counts.values()),
        "overall": {
            "batting": batting_overall,
            "bowling": bowling_overall,
        },
        "has_batting_stats": bool(batting_rows),
        "has_bowling_stats": bool(bowling_rows),
    }


def get_player_radar_comparison(
    tournament_id: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT player_id,
                   SUM(total_runs) AS total_runs,
                   CASE
                       WHEN %s IS NULL THEN
                           SUM(total_runs) * 100.0
                           / NULLIF(SUM(total_balls_faced), 0)
                       ELSE MAX(batting_strike_rate)
                   END AS strike_rate,
                   SUM(total_dot_balls) AS total_dot_balls,
                   SUM(total_balls_faced) AS total_balls_faced,
                   SUM(total_fours) AS total_fours,
                   SUM(total_sixes) AS total_sixes,
                   CASE
                       WHEN %s IS NULL THEN
                           SUM(total_dot_balls) * 100.0
                           / NULLIF(SUM(total_balls_faced), 0)
                       ELSE MAX(dot_ball_percentage)
                   END AS dot_ball_percentage
            FROM batting_stats_by_tournament
            WHERE (%s IS NULL OR tournament_id = %s)
            GROUP BY player_id
            """,
            [tournament_id, tournament_id, tournament_id, tournament_id],
        )
        batting = _rows_as_dicts(cursor)

        cursor.execute(
            """
            SELECT player_id,
                   SUM(wickets) AS wickets,
                   SUM(matches_played) AS matches_bowled,
                   SUM(runs_conceded) AS runs_conceded,
                   SUM(total_legal_balls) AS total_legal_balls,
                   CASE
                       WHEN %s IS NULL THEN
                           SUM(total_legal_balls) * 1.0 / NULLIF(SUM(wickets), 0)
                       ELSE MAX(bowling_strike_rate)
                   END AS strike_rate,
                   SUM(maidens) AS maidens,
                   SUM(total_dot_balls) AS total_dot_balls,
                   CASE
                       WHEN %s IS NULL THEN
                           SUM(runs_conceded) * 6.0
                           / NULLIF(SUM(total_legal_balls), 0)
                       ELSE MAX(economy_rate)
                   END AS economy,
                   CASE
                       WHEN %s IS NULL THEN
                           SUM(total_dot_balls) * 100.0
                           / NULLIF(SUM(total_legal_balls), 0)
                       ELSE MAX(dot_ball_percentage)
                   END AS dot_ball_percentage
            FROM bowling_stats_by_tournament
            WHERE (%s IS NULL OR tournament_id = %s)
            GROUP BY player_id
            """,
            [
                tournament_id,
                tournament_id,
                tournament_id,
                tournament_id,
                tournament_id,
            ],
        )
        bowling = _rows_as_dicts(cursor)

    return {"batting": batting, "bowling": bowling}


def get_player_match_performance(
    player_id: int, tournament_id: int | None = None
) -> dict[str, list[dict[str, Any]]]:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            """
            SELECT m.match_id, m.match_date, m.tournament_id, t.season,
                   b.innings_number, b.runs, b.balls_faced, b.fours, b.sixes,
                   b.strike_rate, b.dismissal_type, b.dismissed_by_bowler,
                   b.dismissed_by_fielder, b.is_out,
                   CASE
                       WHEN i.batting_team = m.team_1_name THEN m.team_2_name
                       WHEN i.batting_team = m.team_2_name THEN m.team_1_name
                   END AS opponent
            FROM batting_scorecards AS b
            JOIN matches AS m ON m.match_id = b.match_id
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            JOIN innings_summary AS i
              ON i.match_id = b.match_id AND i.innings_number = b.innings_number
            WHERE b.player_id = %s AND (%s IS NULL OR m.tournament_id = %s)
            ORDER BY m.match_date DESC, m.match_id DESC, b.innings_number
            """,
            [player_id, tournament_id, tournament_id],
        )
        batting = _rows_as_dicts(cursor)

        cursor.execute(
            """
            SELECT m.match_id, m.match_date, m.tournament_id, t.season,
                   b.innings_number, b.overs_bowled, b.maidens,
                   b.runs_conceded, b.wickets, b.economy, b.dot_balls,
                   b.dot_ball_percentage, i.batting_team AS opponent
            FROM bowling_scorecards AS b
            JOIN matches AS m ON m.match_id = b.match_id
            JOIN tournaments AS t ON t.tournament_id = m.tournament_id
            JOIN innings_summary AS i
              ON i.match_id = b.match_id AND i.innings_number = b.innings_number
            WHERE b.player_id = %s AND (%s IS NULL OR m.tournament_id = %s)
            ORDER BY m.match_date DESC, m.match_id DESC, b.innings_number
            """,
            [player_id, tournament_id, tournament_id],
        )
        bowling = _rows_as_dicts(cursor)
    return {"batting": batting, "bowling": bowling}


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
