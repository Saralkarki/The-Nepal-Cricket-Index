from unittest import TestCase
from unittest.mock import MagicMock, patch

from cricket_nepal.tournament_data_access import get_tournament_match_formats


class TournamentMatchFormatAccessTests(TestCase):
    @patch("cricket_nepal.tournament_data_access.connections")
    def test_reads_distinct_match_formats_for_both_datasets(self, connections):
        cursor = MagicMock()
        cursor.description = [
            ("source",),
            ("tournament_name",),
            ("season",),
            ("gender",),
            ("match_format",),
        ]
        cursor.fetchall.return_value = [
            ("NPL", "Nepal Premier League", "2025/26", "male", "T20"),
            (
                "Nepal national team",
                "ICC Men's Cricket World Cup League 2",
                "2026/27",
                "male",
                "ODI",
            ),
        ]
        connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = (
            cursor
        )

        formats = get_tournament_match_formats()

        self.assertEqual(
            formats,
            [
                {
                    "source": "NPL",
                    "tournament_name": "Nepal Premier League",
                    "season": "2025/26",
                    "gender": "male",
                    "match_format": "T20",
                },
                {
                    "source": "Nepal national team",
                    "tournament_name": "ICC Men's Cricket World Cup League 2",
                    "season": "2026/27",
                    "gender": "male",
                    "match_format": "ODI",
                },
            ],
        )
        query = cursor.execute.call_args.args[0]
        self.assertIn("FROM matches AS m", query)
        self.assertIn("FROM nepal_matches", query)
        self.assertIn("match_format", query)
        connections.__getitem__.assert_called_once_with("cricket")
