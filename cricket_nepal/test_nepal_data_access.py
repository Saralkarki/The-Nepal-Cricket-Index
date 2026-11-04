from unittest import TestCase
from unittest.mock import MagicMock, patch

from cricket_nepal.nepal_data_access import (
    get_nepal_matches,
    get_nepal_tournaments,
)


class NepalTournamentAccessTests(TestCase):
    @patch("cricket_nepal.nepal_data_access.connections")
    def test_returns_distinct_tournaments_as_dictionaries(self, connections):
        cursor = MagicMock()
        cursor.description = [
            ("tournament_id",),
            ("tournament_name",),
            ("season",),
            ("gender",),
        ]
        cursor.fetchall.return_value = [
            (2177, "ICC Men's Cricket World Cup League 2", "2026/27", "male"),
            (2158, "United Arab Emirates tour of Nepal", "2026", "male"),
        ]
        connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = (
            cursor
        )

        tournaments = get_nepal_tournaments()

        self.assertEqual(
            tournaments,
            [
                {
                    "tournament_id": 2177,
                    "tournament_name": "ICC Men's Cricket World Cup League 2",
                    "season": "2026/27",
                    "gender": "male",
                },
                {
                    "tournament_id": 2158,
                    "tournament_name": "United Arab Emirates tour of Nepal",
                    "season": "2026",
                    "gender": "male",
                },
            ],
        )
        query = cursor.execute.call_args.args[0]
        self.assertIn("SELECT DISTINCT", query)
        self.assertIn("FROM nepal_matches", query)
        self.assertIn("gender", query)
        connections.__getitem__.assert_called_once_with("cricket")

    @patch("cricket_nepal.nepal_data_access.connections")
    def test_returns_empty_list_when_there_are_no_tournaments(self, connections):
        cursor = MagicMock()
        cursor.description = [
            ("tournament_id",),
            ("tournament_name",),
            ("season",),
            ("gender",),
        ]
        cursor.fetchall.return_value = []
        connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = (
            cursor
        )

        self.assertEqual(get_nepal_tournaments(), [])


class NepalMatchAccessTests(TestCase):
    @patch("cricket_nepal.nepal_data_access.connections")
    def test_tournament_and_gender_filters_are_independently_optional(
        self, connections
    ):
        cursor = MagicMock()
        cursor.description = [("match_id",)]
        cursor.fetchall.return_value = []
        connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = (
            cursor
        )

        self.assertEqual(get_nepal_matches(), [])
        self.assertEqual(get_nepal_matches(tournament_id=2121), [])
        self.assertEqual(get_nepal_matches(gender="female"), [])

        calls = cursor.execute.call_args_list
        self.assertNotIn(" WHERE ", calls[0].args[0])
        self.assertIn("tournament_id = %s", calls[1].args[0])
        self.assertNotIn("gender = %s", calls[1].args[0])
        self.assertNotIn("tournament_id = %s", calls[2].args[0])
        self.assertIn("gender = %s", calls[2].args[0])
        self.assertEqual(
            [call.args[1] for call in calls],
            [[], [2121], ["female"]],
        )

    @patch("cricket_nepal.nepal_data_access.connections")
    def test_filters_by_tournament_and_gender_with_parameters(self, connections):
        cursor = MagicMock()
        cursor.description = [
            ("match_id",),
            ("match_date",),
            ("match_format",),
            ("team_1_name",),
            ("team_2_name",),
            ("venue_name",),
            ("tournament_id",),
            ("tournament_name",),
            ("season",),
            ("gender",),
            ("winner_name",),
            ("margin",),
            ("margin_type",),
            ("player_of_match",),
        ]
        cursor.fetchall.return_value = [
            (
                "match-1",
                "2026-01-01",
                "T20",
                "Nepal",
                "Malaysia",
                "Kathmandu",
                2121,
                "Nepal T20I Series",
                "2026",
                "female",
                "Nepal",
                5,
                "wickets",
                "Player One",
            )
        ]
        connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = (
            cursor
        )

        matches = get_nepal_matches(tournament_id=2121, gender="female")

        self.assertEqual(matches[0]["match_id"], "match-1")
        self.assertEqual(matches[0]["tournament_id"], 2121)
        self.assertEqual(matches[0]["winner_name"], "Nepal")
        self.assertEqual(matches[0]["margin"], 5)
        query, parameters = cursor.execute.call_args.args
        self.assertIn("tournament_id = %s", query)
        self.assertIn("gender = %s", query)
        self.assertEqual(parameters, [2121, "female"])
        connections.__getitem__.assert_called_once_with("cricket")

    @patch("cricket_nepal.nepal_data_access.connections")
    def test_returns_empty_list_when_filters_match_no_records(self, connections):
        cursor = MagicMock()
        cursor.description = [("match_id",)]
        cursor.fetchall.return_value = []
        connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = (
            cursor
        )

        matches = get_nepal_matches(tournament_id=-1, gender="unknown")

        self.assertEqual(matches, [])
        self.assertEqual(cursor.execute.call_args.args[1], [-1, "unknown"])
