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
            SELECT DISTINCT b.player_id, m.tournament_id, i.batting_team AS team_name
            FROM batting_scorecards AS b
            JOIN innings_summary AS i
              ON i.match_id = b.match_id AND i.innings_number = b.innings_number
            JOIN matches AS m ON m.match_id = b.match_id
            WHERE i.batting_team IS NOT NULL
            UNION
            SELECT DISTINCT b.player_id, m.tournament_id,
                   CASE
                       WHEN i.batting_team = m.team_1_name THEN m.team_2_name
                       WHEN i.batting_team = m.team_2_name THEN m.team_1_name
                   END AS team_name
            FROM bowling_scorecards AS b
            JOIN innings_summary AS i
              ON i.match_id = b.match_id AND i.innings_number = b.innings_number
            JOIN matches AS m ON m.match_id = b.match_id
            WHERE i.batting_team IN (m.team_1_name, m.team_2_name)
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
            LEFT JOIN tournament_players AS tp ON tp.player_id = p.player_id
            LEFT JOIN tournaments AS t ON t.tournament_id = tp.tournament_id
            LEFT JOIN player_teams
              ON player_teams.player_id = p.player_id
             AND player_teams.tournament_id = t.tournament_id
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


def get_player_profile(player_id: int) -> dict[str, Any] | None:
    with connections[CRICKET_DATABASE].cursor() as cursor:
        cursor.execute(
            "SELECT player_id, player_name FROM players WHERE player_id = %s",
            [player_id],
        )
        player_rows = _rows_as_dicts(cursor)
        if not player_rows:
            return None

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
            _player_team_evidence_cte()
            + """
            SELECT DISTINCT player_teams.tournament_id, t.season,
                            player_teams.team_name
            FROM player_teams
            JOIN tournaments AS t ON t.tournament_id = player_teams.tournament_id
            WHERE player_teams.player_id = %s
            ORDER BY t.season DESC, player_teams.team_name
            """,
            [player_id],
        )
        team_rows = _rows_as_dicts(cursor)

    match_counts: dict[int, int] = {}
    for row in match_rows:
        match_counts[row["tournament_id"]] = (
            match_counts.get(row["tournament_id"], 0) + 1
        )
    teams_by_tournament: dict[int, set[str]] = {}
    for row in team_rows:
        teams_by_tournament.setdefault(row["tournament_id"], set()).add(
            row["team_name"]
        )
    participations = [
        {
            "tournament_id": row["tournament_id"],
            "season": row["season"],
            "teams": sorted(teams_by_tournament.get(row["tournament_id"], set())),
        }
        for row in season_stats
    ]
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
        **player_rows[0],
        "participations": participations,
        "season_stats": season_stats,
        "matches_played": sum(match_counts.values()),
        "overall": {
            "batting": batting_overall,
            "bowling": bowling_overall,
        },
        "has_batting_stats": bool(batting_rows),
        "has_bowling_stats": bool(bowling_rows),
    }


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
