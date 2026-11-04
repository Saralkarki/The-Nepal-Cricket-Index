from unittest import TestCase
from unittest.mock import patch

from django.test import Client, SimpleTestCase
from django.urls import reverse

from cricket_nepal.nepal_data_access import (
    LEAGUE_2_CYCLES,
    _build_nepal_performance,
    _nepal_match_outcome,
    _nepal_match_result,
    get_nepal_tournament_overview,
)


OVERVIEW = {
    "tournament_name": "Test Cup",
    "genders": ["male"],
    "match_formats": ["ODI"],
    "performance": {
        "matches_played": 1,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "no_results": 0,
        "unclassified": 1,
        "win_percentage": None,
    },
    "batting": {
        "most_runs": {"batsman": "Test Batter", "runs": 100},
        "highest_score": {"batsman": "Test Batter", "runs": 75},
    },
    "bowling": {
        "most_wickets": {"bowler": "Test Bowler", "wickets": 5},
        "best_figures": {
            "bowler": "Test Bowler",
            "wickets": 4,
            "runs_conceded": 10,
        },
    },
    "matches": [
        {
            "match_id": "test-match",
            "match_date": "2024-01-01",
            "opponent": "Test Opponent",
            "result": "Outcome unavailable",
            "scores": [{"batting_team": "Nepal", "score": "100/3 (20 ov)"}],
        }
    ],
}


class NepalTournamentOverviewViewTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    def test_standard_overview_uses_tournament_id_and_renders_nepal_records(self):
        with patch(
            "cricket_nepal.views.get_nepal_tournament_overview",
            return_value=OVERVIEW,
        ) as overview_query:
            response = self.client.get(
                reverse("cricket_nepal:nepal_tournament_overview", args=[42])
            )

        self.assertEqual(response.status_code, 200)
        overview_query.assert_called_once_with((42,))
        self.assertFalse(response.context["is_league_2"])
        self.assertNotContains(response, 'id="league-2-cycle"')
        self.assertContains(response, "Test Cup")
        self.assertContains(response, "Unclassified")
        self.assertContains(response, "Outcome unavailable")
        self.assertContains(response, "Test Batter")
        self.assertContains(response, "Test Bowler")
        self.assertContains(
            response,
            reverse("cricket_nepal:nepal_match_detail", args=["test-match"]),
        )
        self.assertNotContains(response, "Points table")
        self.assertNotContains(response, reverse("cricket_nepal:player_profile", args=[1]))

    def test_league_2_ids_select_exact_default_and_requested_cycles(self):
        with patch(
            "cricket_nepal.views.get_nepal_tournament_overview",
            return_value=OVERVIEW,
        ) as overview_query:
            old_cycle = self.client.get(
                reverse("cricket_nepal:nepal_tournament_overview", args=[1097])
            )
            self.assertEqual(old_cycle.status_code, 200)
            overview_query.assert_called_with(LEAGUE_2_CYCLES["2019-2023"])
            self.assertEqual(old_cycle.context["selected_cycle"], "2019-2023")
            self.assertContains(old_cycle, "2019–2023")
            self.assertContains(old_cycle, "2024–2027")

            default_new_cycle = self.client.get(
                reverse("cricket_nepal:nepal_tournament_overview", args=[2177])
            )
            self.assertEqual(default_new_cycle.status_code, 200)
            overview_query.assert_called_with(LEAGUE_2_CYCLES["2024-2027"])
            self.assertEqual(default_new_cycle.context["selected_cycle"], "2024-2027")

            new_cycle = self.client.get(
                reverse("cricket_nepal:nepal_tournament_overview", args=[1097]),
                {"cycle": "2024-2027"},
            )
            self.assertEqual(new_cycle.status_code, 200)
            overview_query.assert_called_with(LEAGUE_2_CYCLES["2024-2027"])
            self.assertEqual(new_cycle.context["selected_cycle"], "2024-2027")

    def test_missing_tournament_returns_404(self):
        with patch(
            "cricket_nepal.views.get_nepal_tournament_overview", return_value=None
        ):
            response = self.client.get(
                reverse("cricket_nepal:nepal_tournament_overview", args=[999999])
            )
        self.assertEqual(response.status_code, 404)

    def test_missing_statistics_and_matches_render_as_unavailable(self):
        overview = {
            **OVERVIEW,
            "performance": {
                "matches_played": 0,
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "no_results": 0,
                "unclassified": 0,
                "win_percentage": None,
            },
            "batting": {"most_runs": None, "highest_score": None},
            "bowling": {"most_wickets": None, "best_figures": None},
            "matches": [],
        }
        with patch(
            "cricket_nepal.views.get_nepal_tournament_overview",
            return_value=overview,
        ):
            response = self.client.get(
                reverse("cricket_nepal:nepal_tournament_overview", args=[42])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unavailable (no classified outcomes)")
        self.assertContains(response, "Batting records")
        self.assertContains(response, "Bowling records")
        self.assertContains(response, "No Nepal matches are available")

    def test_nepal_match_detail_is_separate_and_uses_plain_names(self):
        match = {
            "match_id": "123",
            "team_1_name": "Nepal",
            "team_2_name": "Opponent",
            "match_date": "2024-01-01",
            "match_format": "ODI",
            "winner_name": None,
            "result": "Outcome unavailable",
            "venue_name": "Ground",
            "gender": "male",
            "tournament_id": 42,
            "tournament_name": "Test Cup",
            "innings": [
                {
                    "innings_number": 1,
                    "batting_team": "Nepal",
                    "total_runs": 100,
                    "total_wickets": 3,
                    "overs": "20.0",
                    "batting": [{"batsman": "Plain Batter", "runs": 42}],
                    "bowling": [{"bowler": "Plain Bowler", "wickets": 2}],
                }
            ],
        }
        with patch(
            "cricket_nepal.views.get_nepal_match_scorecard", return_value=match
        ) as detail_query:
            response = self.client.get(
                reverse("cricket_nepal:nepal_match_detail", args=["123"])
            )

        self.assertEqual(response.status_code, 200)
        detail_query.assert_called_once_with("123")
        self.assertContains(response, "Outcome unavailable")
        self.assertContains(response, "Plain Batter")
        self.assertContains(response, "Plain Bowler")
        self.assertNotContains(response, reverse("cricket_nepal:player_profile", args=[1]))
        self.assertContains(
            response,
            reverse("cricket_nepal:nepal_tournament_overview", args=[42]),
        )

    def test_existing_npl_match_route_keeps_its_npl_lookup(self):
        with (
            patch(
                "cricket_nepal.views.get_match_scorecard",
                return_value={"match_id": "123"},
            ) as npl_query,
            patch("cricket_nepal.views.get_nepal_match_scorecard") as nepal_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:match_detail", args=["123"])
            )

        self.assertEqual(response.status_code, 200)
        npl_query.assert_called_once_with("123")
        nepal_query.assert_not_called()


class NepalTournamentDirectoryLinkTests(SimpleTestCase):
    def test_national_team_instances_link_by_tournament_id(self):
        npl_tournaments = [
            {"tournament_id": 1, "tournament_name": "Nepal Premier League", "season": "2024/25"}
        ]
        nepal_tournaments = [
            {
                "tournament_id": 1097,
                "tournament_name": "ICC Men's Cricket World Cup League 2",
                "season": "2019/23",
                "gender": "male",
            }
        ]
        match_formats = [
            {
                "source": "NPL",
                "tournament_name": "Nepal Premier League",
                "season": "2024/25",
                "gender": "male",
                "match_format": "T20",
            },
            {
                "source": "Nepal national team",
                "tournament_name": "ICC Men's Cricket World Cup League 2",
                "season": "2019/23",
                "gender": "male",
                "match_format": "ODI",
            },
        ]
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=npl_tournaments),
            patch(
                "cricket_nepal.views.get_nepal_tournaments",
                return_value=nepal_tournaments,
            ),
            patch(
                "cricket_nepal.views.get_tournament_match_formats",
                return_value=match_formats,
            ),
        ):
            response = Client().get(reverse("cricket_nepal:tournaments"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("cricket_nepal:nepal_tournament_overview", args=[1097]),
        )
        self.assertNotContains(
            response,
            reverse("cricket_nepal:tournament_overview", args=["nepal-premier-league"]),
        )
        self.assertContains(response, reverse("cricket_nepal:npl_home"))


class FakeCursor:
    def __init__(self, match_rows, empty_statistics=False):
        self.match_rows = match_rows
        self.empty_statistics = empty_statistics
        self.executions = []
        self.description = None
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        return False

    def execute(self, query, params=None):
        parameters = tuple(params or ())
        self.executions.append((query, parameters))
        if "SELECT DISTINCT tournament_name" in query:
            self.description = [
                ("tournament_name",),
                ("gender",),
                ("match_format",),
            ]
            self.rows = [("League 2", "male", "ODI")]
        elif "FROM nepal_matches" in query:
            self.description = [
                ("match_id",),
                ("match_date",),
                ("team_1_name",),
                ("team_2_name",),
                ("winner_name",),
                ("margin",),
                ("margin_type",),
            ]
            self.rows = self.match_rows
        elif "FROM nepal_innings_summary" in query:
            self.description = [
                ("match_id",),
                ("batting_team",),
                ("total_runs",),
                ("total_wickets",),
                ("overs",),
            ]
            self.rows = [
                (match_id, "Nepal", 100, 3, "20.0")
                for match_id in parameters
            ]
        elif "FROM nepal_batting_stats_by_tournament" in query:
            self.description = [("batsman",), ("runs",)]
            self.rows = [] if self.empty_statistics else [("Cycle Batter", 100)]
        elif "FROM nepal_batting_scorecards" in query:
            self.description = [("batsman",), ("runs",), ("match_id",)]
            self.rows = (
                [] if self.empty_statistics else [("Cycle Batter", 60, "cycle-match")]
            )
        elif "FROM nepal_bowling_stats_by_tournament" in query:
            self.description = [("bowler",), ("wickets",)]
            self.rows = [] if self.empty_statistics else [("Cycle Bowler", 5)]
        elif "FROM nepal_bowling_scorecards" in query:
            self.description = [
                ("bowler",),
                ("match_id",),
                ("innings_number",),
                ("wickets",),
                ("runs_conceded",),
            ]
            self.rows = (
                []
                if self.empty_statistics
                else [("Cycle Bowler", "cycle-match", 1, 4, 10)]
            )
        else:
            raise AssertionError(f"Unexpected query: {query}")
        return None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor

    def cursor(self):
        return self.fake_cursor


class NepalTournamentDataAccessTests(TestCase):
    def test_every_cycle_query_is_scoped_to_its_exact_tournament_id_group(self):
        for cycle, tournament_ids in LEAGUE_2_CYCLES.items():
            match_rows = [
                ("cycle-match", "2024-01-01", "Nepal", "Opponent", "Nepal", 5, "runs"),
                ("unclassified-match", "2024-01-02", "Nepal", "Opponent", None, None, None),
            ]
            cursor = FakeCursor(match_rows)
            with patch(
                "cricket_nepal.nepal_data_access.connections",
                {"cricket": FakeConnection(cursor)},
            ):
                overview = get_nepal_tournament_overview(tournament_ids)

            tournament_queries = [
                parameters
                for query, parameters in cursor.executions
                if "tournament_id IN" in query
            ]
            self.assertEqual(tournament_queries, [tournament_ids] * 6)
            self.assertEqual(
                cursor.executions[2][1],
                ("cycle-match", "unclassified-match"),
            )
            self.assertEqual(overview["performance"]["matches_played"], 2)
            self.assertEqual(overview["performance"]["wins"], 1)
            self.assertEqual(overview["performance"]["unclassified"], 1)
            self.assertEqual(overview["performance"]["ties"], 0)
            self.assertEqual(overview["performance"]["no_results"], 0)
            self.assertEqual(overview["performance"]["win_percentage"], 100)
            self.assertEqual(
                overview["matches"][1]["result"], "Outcome unavailable"
            )
            self.assertEqual(overview["matches"][0]["scores"][0]["score"], "100/3 (20.0 ov)")
            self.assertEqual(overview["batting"]["most_runs"]["batsman"], "Cycle Batter")
            self.assertEqual(overview["bowling"]["best_figures"]["wickets"], 4)

    def test_win_percentage_excludes_unclassified_matches(self):
        performance = _build_nepal_performance(
            [
                {
                    "match_id": "win",
                    "winner_name": "Nepal",
                    "team_1_name": "Nepal",
                    "team_2_name": "Opponent",
                },
                {
                    "match_id": "loss",
                    "winner_name": "Opponent",
                    "team_1_name": "Nepal",
                    "team_2_name": "Opponent",
                },
                {
                    "match_id": "unknown",
                    "winner_name": None,
                    "team_1_name": "Nepal",
                    "team_2_name": "Opponent",
                },
            ]
        )
        self.assertEqual(performance["matches_played"], 3)
        self.assertEqual(performance["wins"], 1)
        self.assertEqual(performance["losses"], 1)
        self.assertEqual(performance["ties"], 0)
        self.assertEqual(performance["no_results"], 0)
        self.assertEqual(performance["unclassified"], 1)
        self.assertEqual(performance["win_percentage"], 50)

    def test_zero_classified_matches_has_no_percentage(self):
        performance = _build_nepal_performance(
            [
                {
                    "match_id": "unknown",
                    "winner_name": None,
                    "team_1_name": "Nepal",
                    "team_2_name": "Opponent",
                }
            ]
        )
        self.assertEqual(performance["win_percentage"], None)
        self.assertEqual(performance["unclassified"], 1)

    def test_confirmed_league_two_outcomes_and_percentage_denominator(self):
        old_cycle_matches = [
            {
                "match_id": "1312806",
                "match_date": "2022-06-11",
                "team_1_name": "Nepal",
                "team_2_name": "United States of America",
                "winner_name": None,
            },
            {
                "match_id": "1341976",
                "match_date": "2022-12-02",
                "team_1_name": "Nepal",
                "team_2_name": "Namibia",
                "winner_name": None,
            },
            {
                "match_id": "old-win",
                "team_1_name": "Nepal",
                "team_2_name": "Opponent",
                "winner_name": "Nepal",
            },
            {
                "match_id": "old-loss",
                "team_1_name": "Nepal",
                "team_2_name": "Opponent",
                "winner_name": "Opponent",
            },
            {
                "match_id": "old-unknown",
                "team_1_name": "Nepal",
                "team_2_name": "Opponent",
                "winner_name": None,
            },
        ]
        old_performance = _build_nepal_performance(old_cycle_matches)
        self.assertEqual(old_performance["ties"], 1)
        self.assertEqual(old_performance["no_results"], 1)
        self.assertEqual(old_performance["wins"], 1)
        self.assertEqual(old_performance["losses"], 1)
        self.assertEqual(old_performance["unclassified"], 1)
        self.assertAlmostEqual(old_performance["win_percentage"], 100 / 3)

        new_cycle_matches = [
            {
                "match_id": "1450700",
                "match_date": "2024-09-24",
                "team_1_name": "Nepal",
                "team_2_name": "Oman",
                "winner_name": None,
            },
            {
                "match_id": "1450707",
                "match_date": "2024-11-04",
                "team_1_name": "Nepal",
                "team_2_name": "Scotland",
                "winner_name": None,
            },
            {
                "match_id": "new-win",
                "team_1_name": "Nepal",
                "team_2_name": "Opponent",
                "winner_name": "Nepal",
            },
            {
                "match_id": "new-loss",
                "team_1_name": "Nepal",
                "team_2_name": "Opponent",
                "winner_name": "Opponent",
            },
            {
                "match_id": "new-unknown",
                "team_1_name": "Nepal",
                "team_2_name": "Opponent",
                "winner_name": None,
            },
        ]
        new_performance = _build_nepal_performance(new_cycle_matches)
        self.assertEqual(new_performance["wins"], 1)
        self.assertEqual(new_performance["losses"], 1)
        self.assertEqual(new_performance["ties"], 0)
        self.assertEqual(new_performance["no_results"], 2)
        self.assertEqual(new_performance["unclassified"], 1)
        self.assertEqual(new_performance["win_percentage"], 50)

    def test_confirmed_matches_render_tie_and_no_result_labels(self):
        matches = [
            {
                "match_id": "1312806",
                "match_date": "2022-06-11",
                "team_1_name": "Nepal",
                "team_2_name": "United States of America",
                "winner_name": None,
                "margin": None,
                "margin_type": None,
            },
            {
                "match_id": "1341976",
                "match_date": "2022-12-02",
                "team_1_name": "Nepal",
                "team_2_name": "Namibia",
                "winner_name": None,
                "margin": None,
                "margin_type": None,
            },
            {
                "match_id": "1450700",
                "match_date": "2024-09-24",
                "team_1_name": "Nepal",
                "team_2_name": "Oman",
                "winner_name": None,
                "margin": None,
                "margin_type": None,
            },
            {
                "match_id": "1450707",
                "match_date": "2024-11-04",
                "team_1_name": "Nepal",
                "team_2_name": "Scotland",
                "winner_name": None,
                "margin": None,
                "margin_type": None,
            },
        ]
        self.assertEqual(
            [_nepal_match_outcome(match) for match in matches],
            ["tie", "no_result", "no_result", "no_result"],
        )
        self.assertEqual(
            [
                _nepal_match_result(match, _nepal_match_outcome(match))
                for match in matches
            ],
            [
                "Tie",
                "No Result (NR)",
                "No Result (NR) — Abandoned without a ball being bowled",
                "No Result (NR)",
            ],
        )

    def test_summary_displays_ties_and_no_results(self):
        overview = {
            **OVERVIEW,
            "performance": {
                "matches_played": 4,
                "wins": 1,
                "losses": 1,
                "ties": 1,
                "no_results": 1,
                "unclassified": 0,
                "win_percentage": 33.333333,
            },
        }
        with patch(
            "cricket_nepal.views.get_nepal_tournament_overview",
            return_value=overview,
        ):
            response = Client().get(
                reverse("cricket_nepal:nepal_tournament_overview", args=[1097])
            )

        rendered = response.content.decode()
        self.assertIn("<dt>Ties</dt><dd>1</dd>", rendered)
        self.assertIn("<dt>No Results</dt><dd>1</dd>", rendered)
        self.assertNotIn("Unclassified outcomes", rendered)

    def test_missing_statistics_return_none_without_failure(self):
        tournament_ids = (1097,)
        cursor = FakeCursor([], empty_statistics=True)
        with patch(
            "cricket_nepal.nepal_data_access.connections",
            {"cricket": FakeConnection(cursor)},
        ):
            overview = get_nepal_tournament_overview(tournament_ids)

        self.assertEqual(overview["performance"]["matches_played"], 0)
        self.assertIsNone(overview["batting"]["most_runs"])
        self.assertIsNone(overview["batting"]["highest_score"])
        self.assertIsNone(overview["bowling"]["most_wickets"])
        self.assertIsNone(overview["bowling"]["best_figures"])
        self.assertEqual(overview["matches"], [])
