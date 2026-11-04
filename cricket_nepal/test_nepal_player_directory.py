from unittest.mock import patch

from django.test import Client, SimpleTestCase
from django.urls import reverse

from cricket_nepal.nepal_data_access import (
    NEPAL_PLAYER_FORMATS,
    _nepal_batting_format_stats,
    _nepal_bowling_format_stats,
    get_nepal_player_directory,
    get_nepal_player_profile,
)


class NepalPlayerDirectoryViewTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    def test_directory_shows_gender_participation_count_and_profile_link(self):
        players = [
            {
                "nepal_player_id": 7,
                "player_name": "A Player",
                "gender": "female",
                "participations": [
                    {
                        "tournament_id": 12,
                        "tournament_name": "T20I Cup",
                        "season": "2025",
                    }
                ],
            }
        ]
        with patch(
            "cricket_nepal.views.get_nepal_player_directory", return_value=players
        ) as directory_query:
            response = self.client.get(
                reverse("cricket_nepal:national_team_players"),
                {"q": " Player ", "gender": "female"},
            )

        self.assertEqual(response.status_code, 200)
        directory_query.assert_called_once_with("Player", gender="female")
        self.assertEqual(response.context["player_count"], 1)
        self.assertContains(response, "Female")
        self.assertContains(response, "T20I Cup")
        self.assertContains(
            response,
            reverse("cricket_nepal:national_team_player_profile", args=[7]),
        )
        self.assertContains(response, 'name="gender"')

    def test_invalid_gender_defaults_to_all_and_search_is_limited(self):
        with patch(
            "cricket_nepal.views.get_nepal_player_directory", return_value=[]
        ) as directory_query:
            response = self.client.get(
                reverse("cricket_nepal:national_team_players"),
                {"q": "x" * 120, "gender": "invalid"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_gender"], "all")
        self.assertEqual(len(response.context["search_term"]), 100)
        directory_query.assert_called_once_with("x" * 100, gender=None)

    def test_empty_directory_result_reports_zero(self):
        with patch(
            "cricket_nepal.views.get_nepal_player_directory", return_value=[]
        ):
            response = self.client.get(reverse("cricket_nepal:national_team_players"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0 players")
        self.assertContains(response, "No players match")

    def test_profile_separates_supported_formats_and_missing_stats(self):
        profile = {
            "nepal_player_id": 7,
            "player_name": "A Player",
            "gender": "female",
            "recorded_scorecard_appearances": 4,
            "participations": [],
            "formats": [
                {"name": "ODI", "batting": None, "bowling": None},
                {
                    "name": "T20I",
                    "batting": {"runs": 45, "innings": 2, "highest_score": 30},
                    "bowling": None,
                },
                {
                    "name": "T20",
                    "batting": None,
                    "bowling": {
                        "wickets": 3,
                        "innings": 2,
                        "overs": "5.2",
                        "best_figures": {"wickets": 2, "runs_conceded": 12},
                    },
                },
            ],
        }
        with patch(
            "cricket_nepal.views.get_nepal_player_profile", return_value=profile
        ):
            response = self.client.get(
                reverse("cricket_nepal:national_team_player_profile", args=[7])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Female")
        self.assertContains(response, "Recorded scorecard appearances")
        self.assertContains(response, "ODI")
        self.assertContains(response, "T20I")
        self.assertContains(response, "T20")
        self.assertNotContains(response, "Others")
        self.assertContains(response, "Batting statistics unavailable for this format.")
        self.assertContains(response, "Bowling statistics unavailable for this format.")
        self.assertContains(response, "Tournament participation")
        self.assertNotContains(response, "Overall statistics")

    def test_unknown_profile_returns_404(self):
        with patch(
            "cricket_nepal.views.get_nepal_player_profile", return_value=None
        ):
            response = self.client.get(
                reverse("cricket_nepal:national_team_player_profile", args=[999999])
            )
        self.assertEqual(response.status_code, 404)


class FakeCursor:
    def __init__(self):
        self.description = []
        self.rows = []
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        return False

    def execute(self, query, parameters=None):
        parameters = tuple(parameters or ())
        self.executions.append((query, parameters))
        if "COUNT(DISTINCT match_id)" in query:
            self.description = [("count",)]
            self.rows = [(2,)]
        elif "FROM nepal_players" in query:
            self.description = [
                ("nepal_player_id",),
                ("player_name",),
                ("gender",),
            ]
            self.rows = [(7, "A Player", "female")]
        elif "FROM nepal_tournament_players" in query:
            self.description = [
                ("nepal_player_id",),
                ("tournament_id",),
                ("tournament_name",),
                ("season",),
            ]
            self.rows = [(7, 12, "T20I Cup", "2025")]
        elif "FROM nepal_batting_scorecards" in query:
            self.description = [
                ("match_format",),
                ("match_id",),
                ("runs",),
                ("balls_faced",),
                ("fours",),
                ("sixes",),
                ("dot_balls",),
                ("is_out",),
            ]
            self.rows = [
                ("ODI", "odi-1", 50, 40, 4, 1, 12, 1),
                ("T20", "t20-1", 20, 10, 2, 0, 3, 0),
            ]
        elif "FROM nepal_bowling_scorecards" in query:
            self.description = [
                ("match_format",),
                ("match_id",),
                ("innings_number",),
                ("legal_balls_bowled",),
                ("runs_conceded",),
                ("wickets",),
                ("maidens",),
                ("dot_balls",),
                ("wides",),
                ("no_balls",),
            ]
            self.rows = [
                ("T20", "t20-1", 1, 24, 20, 2, 1, 10, 1, 0),
            ]
        else:
            raise AssertionError(f"Unexpected query: {query}")

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor

    def cursor(self):
        return self.fake_cursor


class NepalPlayerDataAccessTests(SimpleTestCase):
    def test_directory_filters_gender_and_search_and_batches_participations(self):
        cursor = FakeCursor()
        with patch(
            "cricket_nepal.nepal_data_access.connections",
            {"cricket": FakeConnection(cursor)},
        ):
            players = get_nepal_player_directory("Player", gender="female")

        self.assertEqual(len(cursor.executions), 2)
        self.assertEqual(players[0]["nepal_player_id"], 7)
        self.assertEqual(players[0]["participations"][0]["tournament_name"], "T20I Cup")
        self.assertEqual(cursor.executions[0][1], ("Player", "Player", "female", "female"))
        self.assertIn("match_format IN", cursor.executions[1][0])

    def test_profile_scopes_all_statistics_and_appearances_to_supported_formats(self):
        cursor = FakeCursor()
        with patch(
            "cricket_nepal.nepal_data_access.connections",
            {"cricket": FakeConnection(cursor)},
        ):
            profile = get_nepal_player_profile(7)

        self.assertEqual([row["name"] for row in profile["formats"]], list(NEPAL_PLAYER_FORMATS))
        self.assertEqual(profile["formats"][0]["batting"]["runs"], 50)
        self.assertIsNone(profile["formats"][0]["bowling"])
        self.assertIsNone(profile["formats"][1]["batting"])
        self.assertEqual(profile["formats"][2]["bowling"]["best_figures"]["wickets"], 2)
        self.assertEqual(profile["recorded_scorecard_appearances"], 2)
        format_queries = [
            (query, params)
            for query, params in cursor.executions
            if "match_format IN" in query
        ]
        self.assertEqual(len(format_queries), 4)
        for _, parameters in format_queries:
            self.assertNotIn("Others", parameters)


class NepalPlayerStatsCalculationTests(SimpleTestCase):
    def test_batting_statistics_are_aggregated_independently_for_one_format(self):
        stats = _nepal_batting_format_stats(
            [
                {
                    "match_id": "1",
                    "runs": 60,
                    "balls_faced": 40,
                    "fours": 5,
                    "sixes": 2,
                    "dot_balls": 10,
                    "is_out": 1,
                },
                {
                    "match_id": "2",
                    "runs": 30,
                    "balls_faced": 20,
                    "fours": 3,
                    "sixes": 1,
                    "dot_balls": 5,
                    "is_out": 0,
                },
            ]
        )
        self.assertEqual(stats["matches"], 2)
        self.assertEqual(stats["runs"], 90)
        self.assertEqual(stats["average"], 90)
        self.assertEqual(stats["strike_rate"], 150)
        self.assertEqual(stats["highest_score"], 60)

    def test_bowling_statistics_use_legal_balls_for_overs_and_economy(self):
        stats = _nepal_bowling_format_stats(
            [
                {
                    "match_id": "1",
                    "innings_number": 1,
                    "legal_balls_bowled": 25,
                    "runs_conceded": 20,
                    "wickets": 2,
                    "maidens": 1,
                    "dot_balls": 10,
                    "wides": 1,
                    "no_balls": 0,
                },
                {
                    "match_id": "1",
                    "innings_number": 1,
                    "legal_balls_bowled": 12,
                    "runs_conceded": 8,
                    "wickets": 1,
                    "maidens": 0,
                    "dot_balls": 6,
                    "wides": 0,
                    "no_balls": 0,
                },
            ]
        )
        self.assertEqual(stats["overs"], "6.1")
        self.assertAlmostEqual(stats["economy"], 28 * 6 / 37)
        self.assertEqual(stats["best_figures"], {"wickets": 3, "runs_conceded": 28})
