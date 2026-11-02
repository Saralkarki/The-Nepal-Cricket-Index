import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from cricket_nepal.data_access import _npl_points_table
from scripts.import_parquet_to_sqlite import read_source_data, rebuild_database


class MatchPlayersImportTests(SimpleTestCase):
    def test_import_preserves_match_player_rows_and_null_attributes(self):
        source_dir = Path(__file__).resolve().parents[1] / "data" / "npl"
        source_data = read_source_data(source_dir)
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "cricket.sqlite3"
            validation = rebuild_database(database_path, source_data)
            with sqlite3.connect(database_path) as connection:
                row_count = connection.execute(
                    "SELECT COUNT(*) FROM match_players"
                ).fetchone()[0]
                player_count = connection.execute(
                    "SELECT COUNT(DISTINCT cricsheet_player_id) FROM match_players"
                ).fetchone()[0]
                null_counts = connection.execute(
                    """
                    SELECT COUNT(*) - COUNT(bowling_attribute),
                           COUNT(*) - COUNT(batting_attribute),
                           COUNT(*) - COUNT(is_wicketkeeper)
                    FROM match_players
                    """
                ).fetchone()
                columns = [
                    row[1]
                    for row in connection.execute("PRAGMA table_info(match_players)")
                ]
                indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(match_players)")
                }
                match_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(matches)")
                }
                imported_stages = dict(
                    connection.execute("SELECT match_id, stage FROM matches")
                )
                imported_stage_orders = dict(
                    connection.execute("SELECT match_id, stage_order FROM matches")
                )

        self.assertEqual(row_count, 1408)
        self.assertEqual(player_count, 193)
        self.assertEqual(null_counts, (1408, 1408, 1408))
        self.assertIn("stage", match_columns)
        self.assertEqual(
            imported_stages,
            {row["match_id"]: row["stage"] for row in source_data["matches"]},
        )
        self.assertIn("stage_order", match_columns)
        self.assertEqual(
            imported_stage_orders,
            {row["match_id"]: row["stage_order"] for row in source_data["matches"]},
        )
        self.assertEqual(
            columns,
            [
                "match_id",
                "tournament_id",
                "team_name",
                "player_name",
                "cricsheet_player_id",
                "bowling_attribute",
                "batting_attribute",
                "is_wicketkeeper",
            ],
        )
        self.assertIn("idx_match_players_player_tournament", indexes)
        self.assertIn("idx_match_players_match", indexes)
        self.assertIn("idx_match_players_tournament_team", indexes)
        self.assertIn("idx_match_players_player_name", indexes)
        self.assertEqual(validation["foreign_key_violations"], 0)
        self.assertEqual(validation["players_with_attribute_conflicts"], 0)


class PlayerAttributeResolutionTests(SimpleTestCase):
    def test_consistent_values_and_false_wicketkeeper_are_preserved(self):
        from cricket_nepal.data_access import _resolve_player_attributes

        attributes = _resolve_player_attributes(
            {
                "bowling_attribute": "Off-spin",
                "batting_attribute": "RHB",
                "is_wicketkeeper": 0,
                "bowling_attribute_conflict": 0,
                "batting_attribute_conflict": 0,
                "is_wicketkeeper_conflict": 0,
            }
        )

        self.assertEqual(attributes["bowling_attribute"], "Off-spin")
        self.assertEqual(attributes["batting_attribute"], "RHB")
        self.assertIs(attributes["is_wicketkeeper"], False)
        self.assertFalse(any(attributes["conflicts"].values()))

    def test_conflicting_values_are_flagged_and_not_selected(self):
        from cricket_nepal.data_access import _resolve_player_attributes

        attributes = _resolve_player_attributes(
            {
                "bowling_attribute": "Fast",
                "batting_attribute": None,
                "is_wicketkeeper": 1,
                "bowling_attribute_conflict": 1,
                "batting_attribute_conflict": 0,
                "is_wicketkeeper_conflict": 1,
            }
        )

        self.assertIsNone(attributes["bowling_attribute"])
        self.assertIsNone(attributes["batting_attribute"])
        self.assertIsNone(attributes["is_wicketkeeper"])
        self.assertEqual(
            attributes["conflicts"],
            {
                "bowling_attribute": True,
                "batting_attribute": False,
                "is_wicketkeeper": True,
            },
        )


class HomepageTests(SimpleTestCase):
    tournaments = [
        {
            "tournament_id": 1998,
            "tournament_name": "Nepal Premier League",
            "season": "2025/26",
        },
        {
            "tournament_id": 1783,
            "tournament_name": "Nepal Premier League",
            "season": "2024/25",
        },
    ]
    def test_homepage_is_general_and_has_no_npl_statistics(self):
        with patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments):
            response = self.client.get(reverse("cricket_nepal:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nepal Cricket Dataset")
        self.assertContains(response, "Tournaments")
        self.assertContains(response, "Players")
        self.assertContains(response, "Matches")
        self.assertContains(response, "Nepal Premier League")
        self.assertNotContains(response, "Total runs")
        self.assertNotContains(response, "Leading run scorer")

    def test_tournament_directory_links_to_npl_overview(self):
        with patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments):
            response = self.client.get(reverse("cricket_nepal:tournaments"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "cricket_nepal:tournament_overview",
                kwargs={"tournament_slug": "nepal-premier-league"},
            ),
        )
        self.assertContains(response, "Seasons 2025/26 · 2024/25")

    def _overview(self):
        return {
            "seasons": self.tournaments,
            "summary": {"matches": 64, "teams": 8, "players": 193, "total_runs": 10},
            "points_table": None,
            "points_table_limitation": None,
            "batting_leaders": {},
            "bowling_leaders": {},
            "statistics": {},
            "recent_matches": [],
            "season_comparison": [],
        }

    def _overview_url(self):
        return reverse(
            "cricket_nepal:tournament_overview",
            kwargs={"tournament_slug": "nepal-premier-league"},
        )

    def test_npl_overview_defaults_to_overall(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch(
                "cricket_nepal.views.get_npl_tournament_overview",
                return_value=self._overview(),
            ) as overview_query,
        ):
            response = self.client.get(self._overview_url())

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_season"])
        overview_query.assert_called_once_with(None)
        self.assertContains(response, "All NPL seasons")
        self.assertNotContains(response, "Points table")

    def test_npl_overview_selects_requested_season(self):
        overview = self._overview()
        overview["summary"]["matches"] = 32
        overview["summary"]["players"] = 126
        overview["points_table"] = []
        overview["points_table_limitation"] = "No standings available."
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch(
                "cricket_nepal.views.get_npl_tournament_overview",
                return_value=overview,
            ) as overview_query,
        ):
            response = self.client.get(self._overview_url(), {"season_id": "1783"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_season"]["season"], "2024/25")
        overview_query.assert_called_once_with(1783)
        self.assertContains(response, "Points table · 2024/25")

    def test_npl_overview_invalid_season_falls_back_to_overall(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch(
                "cricket_nepal.views.get_npl_tournament_overview",
                return_value=self._overview(),
            ) as overview_query,
        ):
            response = self.client.get(
                self._overview_url(), {"season_id": "not-a-season"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_season"])
        overview_query.assert_called_once_with(None)

    def test_npl_overview_links_leaders_and_recent_matches(self):
        overview = self._overview()
        overview["batting_leaders"] = {
            "runs": [
                {
                    "player_id": 42,
                    "player_name": "Top Batter",
                    "runs": 300,
                    "matches": 7,
                }
            ],
            "average": [],
            "strike_rate": [],
        }
        overview["bowling_leaders"] = {
            "wickets": [],
            "economy": [],
            "figures": [],
        }
        overview["recent_matches"] = [
            {
                "match_id": "1462596",
                "match_date": "2024-11-30",
                "team_1_name": "Biratnagar Kings",
                "team_1_score": 120,
                "team_2_name": "Janakpur Bolts",
                "team_2_score": 121,
                "result": "Janakpur Bolts won",
                "player_of_match": "Top Batter",
            }
        ]
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch(
                "cricket_nepal.views.get_npl_tournament_overview",
                return_value=overview,
            ),
        ):
            response = self.client.get(self._overview_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, reverse("cricket_nepal:player_profile", args=[42])
        )
        self.assertContains(
            response,
            reverse("cricket_nepal:match_detail", args=["1462596"]),
        )
        self.assertContains(response, "Top Batter")
        self.assertContains(response, "Player of the Match: Top Batter")

    def test_npl_overview_shows_champions_with_team_and_final_links(self):
        overview = self._overview()
        overview["champions"] = [
            {
                "season": "2025/26",
                "team_name": "Lumbini Lions",
                "team_slug": "lumbini-lions",
                "opponent": "Sudur Paschim Royals",
                "match_id": "1511008",
                "match_date": "2025-12-13",
                "winner_score": 112,
                "opponent_score": 111,
                "margin": 1,
                "margin_type": "runs",
            }
        ]
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch(
                "cricket_nepal.views.get_npl_tournament_overview",
                return_value=overview,
            ),
        ):
            response = self.client.get(self._overview_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NPL champions")
        self.assertContains(response, "2025/26 · Champions")
        self.assertContains(response, "Lumbini Lions")
        self.assertContains(response, "112–111 vs Sudur Paschim Royals")
        self.assertContains(
            response,
            reverse("cricket_nepal:team_profile", args=["lumbini-lions"]),
        )
        self.assertContains(
            response,
            reverse("cricket_nepal:match_detail", args=["1511008"]),
        )

    def test_unknown_tournament_returns_404(self):
        response = self.client.get(
            reverse(
                "cricket_nepal:tournament_overview",
                kwargs={"tournament_slug": "unknown-tournament"},
            )
        )
        self.assertEqual(response.status_code, 404)


class NplPointsTableTests(SimpleTestCase):
    def test_points_use_only_round_robin_and_count_all_out_as_full_overs(self):
        matches = [
            {"match_id": "1", "match_date": "2024-01-01", "stage": "Round Robin", "team_1_name": "A", "team_2_name": "B", "winner_name": "B"},
            {"match_id": "2", "match_date": "2024-01-02", "stage": "League Stage", "team_1_name": "B", "team_2_name": "C", "winner_name": None},
            {"match_id": "3", "match_date": "2024-01-03", "stage": "Round Robin", "team_1_name": "C", "team_2_name": "A", "winner_name": "A"},
            {"match_id": "4", "match_date": "2024-01-04", "stage": "Final", "team_1_name": "A", "team_2_name": "B", "winner_name": "A"},
        ]
        innings = {
            "1": [
                {"innings_number": 1, "batting_team": "A", "total_runs": 100, "total_wickets": 10, "legal_balls": 90},
                {"innings_number": 2, "batting_team": "B", "total_runs": 101, "total_wickets": 3, "legal_balls": 60},
            ],
            "2": [
                {"innings_number": 1, "batting_team": "B", "total_runs": 90, "total_wickets": 4, "legal_balls": 120},
                {"innings_number": 2, "batting_team": "C", "total_runs": 91, "total_wickets": 2, "legal_balls": 72},
            ],
            "3": [
                {"innings_number": 1, "batting_team": "C", "total_runs": 50, "total_wickets": 10, "legal_balls": 60},
                {"innings_number": 2, "batting_team": "A", "total_runs": 51, "total_wickets": 0, "legal_balls": 45},
            ],
            "4": [
                {"innings_number": 1, "batting_team": "A", "total_runs": 200, "total_wickets": 1, "legal_balls": 120},
                {"innings_number": 2, "batting_team": "B", "total_runs": 190, "total_wickets": 3, "legal_balls": 120},
            ],
        }

        table, limitation = _npl_points_table(matches, innings)

        self.assertIsNone(limitation)
        by_team = {row["team_name"]: row for row in table}
        self.assertEqual(by_team["A"]["played"], 2)
        self.assertEqual(by_team["A"]["runs_for"], 151)
        self.assertEqual(by_team["A"]["balls_faced"], 165)
        self.assertEqual(by_team["A"]["runs_against"], 151)
        self.assertEqual(by_team["A"]["balls_bowled"], 180)
        self.assertEqual(by_team["B"]["no_result"], 1)
        self.assertEqual(by_team["B"]["points"], 3)
        self.assertAlmostEqual(by_team["B"]["net_run_rate"], 5.1)
        self.assertAlmostEqual(
            by_team["A"]["net_run_rate"],
            (151 * 6 / 165) - (151 * 6 / 180),
        )

    def test_incomplete_stage_labels_suppress_points_table(self):
        matches = [
            {"match_id": "1", "match_date": "2024-01-01", "stage": None, "team_1_name": "A", "team_2_name": "B", "winner_name": "A"},
        ]

        table, limitation = _npl_points_table(matches, {})

        self.assertIsNone(table)
        self.assertIn("stage labels are incomplete", limitation)


class MatchesPageTests(SimpleTestCase):
    tournaments = HomepageTests.tournaments
    teams = ["Biratnagar Kings", "Janakpur Bolts"]
    sample_match = {
        "match_id": "1462596",
        "match_date": "2024-11-30",
        "team_1_name": "Biratnagar Kings",
        "team_2_name": "Janakpur Bolts",
        "winner_name": "Janakpur Bolts",
        "margin": 8,
        "margin_type": "wkts",
        "venue_name": "TU International Cricket Ground",
        "player_of_match": "BKEL Milantha",
    }

    def test_match_list_renders_data_and_links_to_detail(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch("cricket_nepal.views.get_teams", return_value=self.teams),
            patch("cricket_nepal.views.get_matches", return_value=[self.sample_match]),
        ):
            response = self.client.get(
                reverse("cricket_nepal:matches"), {"tournament_id": "1783"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Biratnagar Kings")
        self.assertContains(response, "Janakpur Bolts won")
        self.assertContains(response, "by 8 wkts")
        self.assertContains(response, "1 match</h2>")
        self.assertContains(
            response,
            reverse("cricket_nepal:match_detail", args=["1462596"]),
        )

    def test_match_filter_is_scoped_to_selected_tournament_and_team(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch("cricket_nepal.views.get_teams", return_value=self.teams) as team_query,
            patch(
                "cricket_nepal.views.get_matches", return_value=[self.sample_match]
            ) as matches_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:matches"),
                {"tournament_id": "1783", "team": "Janakpur Bolts"},
            )

        self.assertEqual(response.status_code, 200)
        team_query.assert_called_once_with(1783)
        matches_query.assert_called_once_with(1783, "Janakpur Bolts")
        self.assertEqual(response.context["selected_team"], "Janakpur Bolts")

    def test_missing_result_fields_render_gracefully(self):
        match_without_result = {
            **self.sample_match,
            "winner_name": None,
            "margin": None,
            "margin_type": None,
            "venue_name": None,
            "player_of_match": None,
        }
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch("cricket_nepal.views.get_teams", return_value=self.teams),
            patch(
                "cricket_nepal.views.get_matches",
                return_value=[match_without_result],
            ),
        ):
            response = self.client.get(reverse("cricket_nepal:matches"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Result unavailable")
        self.assertContains(response, "Venue unavailable")
        self.assertContains(response, "Not recorded")

    def test_match_detail_renders_innings_and_player_scorecards(self):
        with patch(
            "cricket_nepal.views.get_match_scorecard",
            return_value={
                **self.sample_match,
                "match_format": "T20",
                "city": "Kirtipur",
                "toss_winner_name": "Janakpur Bolts",
                "toss_decision": "field",
                "tournament_id": 1783,
                "tournament_name": "Nepal Premier League",
                "season": "2024/25",
                "innings": [
                    {
                        "innings_number": 1,
                        "total_runs": 127,
                        "total_wickets": 10,
                        "overs": "19.0.0",
                        "batting_team": "Biratnagar Kings",
                        "batting": [
                            {
                                "player_id": 101,
                                "player_name": "First Batter",
                                "is_out": True,
                                "dismissal_type": "caught",
                                "dismissed_by_bowler": "First Bowler",
                                "dismissed_by_fielder": "First Fielder",
                                "runs": 42,
                                "balls_faced": 30,
                                "fours": 4,
                                "sixes": 2,
                                "strike_rate": 140.0,
                                "dot_balls": 12,
                                "dot_ball_percentage": 40.0,
                            },
                            {
                                "player_id": 102,
                                "player_name": "Second Batter",
                                "is_out": False,
                                "runs": 10,
                                "balls_faced": 8,
                                "fours": 1,
                                "sixes": 0,
                                "strike_rate": 125.0,
                                "dot_balls": 3,
                                "dot_ball_percentage": 37.5,
                            },
                        ],
                        "bowling": [
                            {
                                "player_id": 103,
                                "player_name": "First Bowler",
                                "overs_bowled": "4.0",
                                "runs_conceded": 24,
                                "wickets": 3,
                                "economy": 6.0,
                                "dot_balls": 18,
                                "dot_ball_percentage": 30.0,
                            },
                        ],
                    },
                    {
                        "innings_number": 2,
                        "total_runs": 131,
                        "total_wickets": 2,
                        "overs": "15.0.3",
                        "batting_team": "Janakpur Bolts",
                        "batting": [],
                        "bowling": [],
                    },
                ],
            },
        ):
            response = self.client.get(
                reverse("cricket_nepal:match_detail", args=["1462596"])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Innings 1")
        self.assertContains(response, "Innings 2")
        self.assertContains(response, "127/10")
        self.assertContains(response, "131/2")
        self.assertContains(response, "Biratnagar Kings")
        self.assertContains(response, "Janakpur Bolts")
        self.assertContains(response, "First Batter")
        self.assertContains(response, "First Bowler")
        self.assertContains(
            response,
            reverse("cricket_nepal:player_profile", args=[101]),
        )
        self.assertContains(response, "140.00")
        self.assertContains(response, "125.00")
        self.assertContains(response, "12")
        self.assertContains(response, "40.00")
        self.assertContains(response, "37.50")
        self.assertContains(response, "Dot Balls")
        self.assertContains(response, "Dot Ball %")
        self.assertContains(response, "140.00")
        self.assertContains(response, "not out")
        self.assertContains(response, "Bowling scorecard unavailable")

    def test_match_without_result_or_innings_renders(self):
        incomplete_match = {
            **self.sample_match,
            "winner_name": None,
            "margin": None,
            "margin_type": None,
            "match_format": "T20",
            "city": None,
            "toss_winner_name": None,
            "toss_decision": None,
            "tournament_id": 1783,
            "tournament_name": "Nepal Premier League",
            "season": "2024/25",
            "innings": [],
        }
        with patch(
            "cricket_nepal.views.get_match_scorecard",
            return_value=incomplete_match,
        ):
            response = self.client.get(
                reverse("cricket_nepal:match_detail", args=["no-result"])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Result unavailable")
        self.assertContains(response, "No innings summary is available")

    def test_missing_match_returns_404(self):
        with patch("cricket_nepal.views.get_match_scorecard", return_value=None):
            missing_response = self.client.get(
                reverse("cricket_nepal:match_detail", args=["unknown"])
            )
        self.assertEqual(missing_response.status_code, 404)


class PlayerDirectoryTests(SimpleTestCase):
    def test_directory_lists_participation_and_links_to_profiles(self):
        players = [
            {
                "player_id": 25,
                "player_name": "A Player",
                "participations": [
                    {"season": "2025/26", "teams": ["Kathmandu Gorkhas"]},
                    {"season": "2024/25", "teams": ["Biratnagar Kings"]},
                ],
            }
        ]
        with patch("cricket_nepal.views.get_player_directory", return_value=players):
            response = self.client.get(reverse("cricket_nepal:players"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A Player")
        self.assertContains(response, "2025/26")
        self.assertContains(response, "Kathmandu Gorkhas")
        self.assertContains(response, reverse("cricket_nepal:player_profile", args=[25]))

    def test_directory_search_is_trimmed_and_passed_to_query(self):
        with patch(
            "cricket_nepal.views.get_player_directory", return_value=[]
        ) as directory_query:
            response = self.client.get(reverse("cricket_nepal:players"), {"q": "  Milan  "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["search_term"], "Milan")
        directory_query.assert_called_once_with("Milan")
        self.assertContains(response, "No players match")


class TeamDirectoryTests(SimpleTestCase):
    teams = [
        {
            "team_name": "Biratnagar Kings",
            "team_slug": "biratnagar-kings",
            "seasons": ["2025/26", "2024/25"],
            "participations": [
                {"tournament_id": 1998, "season": "2025/26"},
                {"tournament_id": 1783, "season": "2024/25"},
            ],
            "matches_played": 30,
            "wins": 15,
            "losses": 15,
            "players_with_recorded_appearances": 25,
        },
        {
            "team_name": "Kathmandu Gorkhas",
            "team_slug": "kathmandu-gorkhas",
            "seasons": ["2025/26", "2024/25"],
            "participations": [
                {"tournament_id": 1998, "season": "2025/26"},
                {"tournament_id": 1783, "season": "2024/25"},
            ],
            "matches_played": 30,
            "wins": 14,
            "losses": 16,
            "players_with_recorded_appearances": 24,
        },
    ]

    def test_directory_shows_team_records_and_profile_links(self):
        with patch("cricket_nepal.views.get_team_directory", return_value=self.teams):
            response = self.client.get(reverse("cricket_nepal:teams"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Biratnagar Kings")
        self.assertContains(response, "2025/26 · 2024/25")
        self.assertContains(response, "Players with appearances")
        self.assertContains(
            response,
            reverse("cricket_nepal:team_profile", args=["biratnagar-kings"]),
        )
        self.assertContains(
            response,
            reverse("cricket_nepal:team_profile", args=["kathmandu-gorkhas"]),
        )


class TeamOutcomeAndRankingTests(SimpleTestCase):
    def test_outcome_does_not_count_no_result_as_loss(self):
        from cricket_nepal.data_access import _team_match_outcome

        outcome = _team_match_outcome(
            {
                "winner_name": None,
                "margin_type": None,
                "team_score": 144,
                "opponent_score": 157,
            },
            ("Biratnagar Kings",),
        )
        self.assertEqual(outcome, ("No result", "neutral"))

    def test_tied_score_and_explicit_tie_are_neutral(self):
        from cricket_nepal.data_access import _team_match_outcome

        tied_score = _team_match_outcome(
            {
                "winner_name": None,
                "margin_type": None,
                "team_score": 150,
                "opponent_score": 150,
            },
            ("Biratnagar Kings",),
        )
        explicit_tie = _team_match_outcome(
            {
                "winner_name": None,
                "margin_type": "tie",
                "team_score": None,
                "opponent_score": None,
            },
            ("Biratnagar Kings",),
        )
        self.assertEqual(tied_score, ("Tied", "neutral"))
        self.assertEqual(explicit_tie, ("Tied", "neutral"))

    def test_leader_ranking_keeps_tied_players(self):
        from cricket_nepal.data_access import _ranked_team_leaders

        leaders = _ranked_team_leaders(
            [
                {"player_name": "A", "average": 25.0},
                {"player_name": "B", "average": 25.0},
                {"player_name": "C", "average": 19.0},
            ],
            "average",
            highest_is_best=True,
        )
        self.assertEqual([leader["player_name"] for leader in leaders], ["A", "B"])


class TeamProfileTests(SimpleTestCase):
    teams = TeamDirectoryTests.teams
    profile = {
        "team_name": "Biratnagar Kings",
        "team_slug": "biratnagar-kings",
        "is_kathmandu_brand_change": False,
        "seasons": [
            {"tournament_id": 1998, "season": "2025/26"},
            {"tournament_id": 1783, "season": "2024/25"},
        ],
        "matches": [
            {
                "match_id": "1462596",
                "match_date": "2024-11-30",
                "opponent": "Janakpur Bolts",
                "result": "Won",
                "team_score": 151,
                "opponent_score": 143,
                "season": "2024/25",
                "venue_name": "Tribhuvan University International Cricket Ground",
                "winning_margin": "5 wickets",
                "player_of_match": "A Player",
                "result_class": "win",
                "recent_summary": "Won by 5 wickets",
            }
        ],
        "recent_form": [
            {
                "match_id": "1462596",
                "match_date": "2024-11-30",
                "opponent": "Janakpur Bolts",
                "result": "Won",
                "result_class": "win",
                "recent_summary": "Won by 5 wickets",
            }
        ],
        "matches_played": 30,
        "wins": 15,
        "losses": 15,
        "ties": 0,
        "no_results": 0,
        "win_percentage": 50.0,
        "batting": {
            "total_runs": 1000,
            "innings": 10,
            "legal_balls": 600,
            "wickets_lost": 50,
            "fours": 80,
            "sixes": 20,
            "dot_balls": 200,
            "balls_faced": 800,
            "average": 20.0,
            "strike_rate": 125.0,
            "average_runs_per_innings": 100.0,
            "run_rate": 10.0,
            "dot_ball_percentage": 25.0,
        },
        "bowling": {
            "wickets": 50,
            "runs_conceded": 900,
            "legal_balls": 600,
            "maidens": 3,
            "dot_balls": 200,
            "average": 18.0,
            "economy": 9.0,
            "strike_rate": 12.0,
            "dot_ball_percentage": 33.33,
        },
        "top_batting": {
            "runs": [
                {
                    "player_id": 25,
                    "player_name": "A Player",
                    "runs": 300,
                    "matches": 10,
                    "innings": 10,
                }
            ],
            "average": [
                {
                    "player_id": 25,
                    "player_name": "A Player",
                    "average": 30.0,
                    "matches": 10,
                    "dismissals": 10,
                }
            ],
            "strike_rate": [
                {
                    "player_id": 25,
                    "player_name": "A Player",
                    "strike_rate": 125.0,
                    "matches": 10,
                    "balls_faced": 240,
                }
            ],
        },
        "top_bowling": {
            "wickets": [
                {
                    "player_id": 25,
                    "player_name": "A Player",
                    "wickets": 15,
                    "matches": 10,
                    "innings": 10,
                }
            ],
            "economy": [
                {
                    "player_id": 25,
                    "player_name": "A Player",
                    "economy": 7.5,
                    "matches": 10,
                    "legal_balls": 180,
                }
            ],
            "figures": [
                {
                    "player_id": 25,
                    "player_name": "A Player",
                    "wickets": 4,
                    "runs_conceded": 18,
                    "match_id": "1462596",
                    "opponent": "Janakpur Bolts",
                    "match_date": "2024-11-30",
                }
            ],
        },
        "players": [
            {
                "player_id": 25,
                "player_name": "A Player",
                "batting_attribute": None,
                "bowling_attribute": None,
                "is_wicketkeeper": None,
                "batting_attribute_conflict": 0,
                "bowling_attribute_conflict": 0,
                "is_wicketkeeper_conflict": 0,
                "matches": 10,
                "runs": 300,
                "wickets": 15,
            },
            {
                "player_id": 133,
                "player_name": "R Rijal",
                "batting_attribute": None,
                "bowling_attribute": None,
                "is_wicketkeeper": None,
                "batting_attribute_conflict": 0,
                "bowling_attribute_conflict": 0,
                "is_wicketkeeper_conflict": 0,
                "matches": 0,
                "runs": 0,
                "wickets": 0,
            },
        ],
    }

    def test_profile_season_filter_applies_to_all_team_sections(self):
        with (
            patch("cricket_nepal.views.get_team_directory", return_value=self.teams),
            patch(
                "cricket_nepal.views.get_team_profile", return_value=self.profile
            ) as profile_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:team_profile", args=["biratnagar-kings"]),
                {"season_id": "1783"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_season"]["season"], "2024/25")
        profile_query.assert_called_once_with("Biratnagar Kings", 1783)
        self.assertContains(response, "2024/25")
        self.assertContains(response, "Team batting performance")
        self.assertContains(response, "Team bowling performance")
        self.assertContains(response, "Match history")
        self.assertContains(response, "Team players")
        self.assertContains(response, "Top performers")
        self.assertContains(response, "Recent form")
        self.assertContains(response, "A Player")
        self.assertContains(response, "R Rijal")
        self.assertContains(response, "Best batting average")
        self.assertContains(response, "Best economy")
        self.assertContains(response, "4/18")
        self.assertContains(response, "Winning margin")
        self.assertContains(response, "Player of the Match")
        self.assertNotContains(response, "Batting style")
        self.assertNotContains(response, "Bowling style")
        self.assertNotContains(response, "Wicketkeeper")
        self.assertNotContains(response, ">False<")
        self.assertNotContains(response, "Batting appearances")
        self.assertNotContains(response, "Bowling appearances")
        self.assertContains(
            response,
            reverse("cricket_nepal:player_profile", args=[25]),
        )
        self.assertContains(
            response,
            reverse("cricket_nepal:player_profile", args=[133]),
        )
        self.assertContains(
            response,
            reverse("cricket_nepal:match_detail", args=["1462596"]),
        )

    def test_profile_defaults_to_overall_and_shows_both_season_options(self):
        with (
            patch("cricket_nepal.views.get_team_directory", return_value=self.teams),
            patch(
                "cricket_nepal.views.get_team_profile", return_value=self.profile
            ) as profile_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:team_profile", args=["biratnagar-kings"])
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_season"])
        profile_query.assert_called_once_with("Biratnagar Kings", None)
        self.assertContains(response, '<option value="">Overall</option>')
        self.assertContains(response, "2025/26")
        self.assertContains(response, "2024/25")

    def test_kathmandu_profile_explains_branding_change(self):
        kathmandu_profile = {
            **self.profile,
            "team_name": "Kathmandu Gorkhas",
            "team_slug": "kathmandu-gorkhas",
            "is_kathmandu_brand_change": True,
        }
        with (
            patch("cricket_nepal.views.get_team_directory", return_value=self.teams),
            patch(
                "cricket_nepal.views.get_team_profile",
                return_value=kathmandu_profile,
            ),
        ):
            response = self.client.get(
                reverse("cricket_nepal:team_profile", args=["kathmandu-gorkhas"])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Known as Kathmandu Gurkhas in 2024/25")

    def test_unknown_team_returns_404(self):
        with patch("cricket_nepal.views.get_team_directory", return_value=self.teams):
            response = self.client.get(
                reverse("cricket_nepal:team_profile", args=["not-a-team"])
            )

        self.assertEqual(response.status_code, 404)


class PlayerProfileTests(SimpleTestCase):
    profile = {
        "player_id": 25,
        "player_name": "A Player",
        "attributes": {
            "bowling_attribute": None,
            "batting_attribute": None,
            "is_wicketkeeper": None,
            "conflicts": {
                "bowling_attribute": False,
                "batting_attribute": False,
                "is_wicketkeeper": False,
            },
        },
        "participations": [
            {
                "tournament_id": 1998,
                "season": "2025/26",
                "teams": ["Kathmandu Gorkhas"],
            },
            {
                "tournament_id": 1783,
                "season": "2024/25",
                "teams": ["Biratnagar Kings"],
            },
        ],
        "season_stats": [
            {
                "tournament_id": 1998,
                "season": "2025/26",
                "matches_played": 4,
                "total_runs": 100,
                "batting_average": 25.0,
                "batting_strike_rate": 120.0,
                "highest_score": 50,
                "total_fours": 10,
                "total_sixes": 2,
                "total_dot_balls": 20,
                "dot_ball_percentage": 24.0,
                "has_batting_stats": True,
                "wickets": None,
                "has_bowling_stats": False,
            },
            {
                "tournament_id": 1783,
                "season": "2024/25",
                "matches_played": 3,
                "total_runs": None,
                "has_batting_stats": False,
                "wickets": 5,
                "bowling_average": 12.0,
                "economy_rate": 6.0,
                "bowling_strike_rate": 12.0,
                "maidens": 1,
                "bowling_dot_balls": 30,
                "bowling_dot_ball_percentage": 50.0,
                "has_bowling_stats": True,
            },
        ],
        "matches_played": 7,
        "overall": {
            "batting": {
                "runs": 100,
                "average": 25.0,
                "strike_rate": 120.0,
                "highest_score": 50,
                "fours": 10,
                "sixes": 2,
                "dot_balls": 20,
                "dot_ball_percentage": 24.0,
            },
            "bowling": {
                "wickets": 5,
                "average": 12.0,
                "economy": 6.0,
                "strike_rate": 12.0,
                "maidens": 1,
                "dot_balls": 30,
                "dot_ball_percentage": 50.0,
            },
        },
        "has_batting_stats": True,
        "has_bowling_stats": True,
    }

    def test_profile_renders_stats_and_performances_for_selected_season(self):
        batting = [
            {
                "match_id": "1462596",
                "match_date": "2024-11-30",
                "season": "2024/25",
                "opponent": "Janakpur Bolts",
                "runs": 42,
                "balls_faced": 30,
                "fours": 4,
                "sixes": 2,
                "strike_rate": 140.0,
                "is_out": True,
                "dismissal_type": "caught",
            }
        ]
        bowling = [
            {
                "match_id": "1462596",
                "match_date": "2024-11-30",
                "season": "2024/25",
                "opponent": "Biratnagar Kings",
                "overs_bowled": "4.0",
                "maidens": 1,
                "runs_conceded": 24,
                "wickets": 3,
                "economy": 6.0,
                "dot_balls": 18,
                "dot_ball_percentage": 37.5,
            }
        ]
        with (
            patch("cricket_nepal.views.get_player_profile", return_value=self.profile),
            patch(
                "cricket_nepal.views.get_player_radar_comparison",
                return_value={"batting": [], "bowling": []},
            ),
            patch(
                "cricket_nepal.views.get_player_match_performance",
                return_value={"batting": batting, "bowling": bowling},
            ) as performance_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:player_profile", args=[25]),
                {"season_id": "1783"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_season"]["season"], "2024/25")
        self.assertEqual(
            [row["season"] for row in response.context["profile"]["display_season_stats"]],
            ["2024/25"],
        )
        performance_query.assert_called_once_with(25, tournament_id=1783)
        self.assertContains(response, "A Player")
        self.assertContains(response, "140.00")
        self.assertContains(response, "Janakpur Bolts")
        self.assertContains(response, "Biratnagar Kings")
        self.assertContains(response, "37.50")
        self.assertContains(
            response,
            reverse("cricket_nepal:match_detail", args=["1462596"]),
        )
        self.assertNotContains(response, "No bowling statistics available.")

    def test_profile_shows_neutral_placeholders_for_unknown_attributes(self):
        with (
            patch("cricket_nepal.views.get_player_profile", return_value=self.profile),
            patch(
                "cricket_nepal.views.get_player_radar_comparison",
                return_value={"batting": [], "bowling": []},
            ),
            patch(
                "cricket_nepal.views.get_player_match_performance",
                return_value={"batting": [], "bowling": []},
            ),
        ):
            response = self.client.get(
                reverse("cricket_nepal:player_profile", args=[25])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Batting style")
        self.assertContains(response, "Bowling style")
        self.assertContains(response, "Wicketkeeper")
        self.assertEqual(response.content.count(b"Not available"), 3)
        self.assertNotContains(response, ">None<")
        self.assertNotContains(response, ">False<")

    def test_profile_displays_populated_attributes_and_flags_conflicts(self):
        profile = {
            **self.profile,
            "attributes": {
                "bowling_attribute": None,
                "batting_attribute": "RHB",
                "is_wicketkeeper": False,
                "conflicts": {
                    "bowling_attribute": True,
                    "batting_attribute": False,
                    "is_wicketkeeper": False,
                },
            },
        }
        with (
            patch("cricket_nepal.views.get_player_profile", return_value=profile),
            patch(
                "cricket_nepal.views.get_player_radar_comparison",
                return_value={"batting": [], "bowling": []},
            ),
            patch(
                "cricket_nepal.views.get_player_match_performance",
                return_value={"batting": [], "bowling": []},
            ),
        ):
            response = self.client.get(
                reverse("cricket_nepal:player_profile", args=[25])
            )

        self.assertContains(response, "RHB")
        self.assertContains(response, "Conflicting data")
        self.assertContains(response, "<dt>Wicketkeeper</dt>\n                <dd>No</dd>", html=True)

    def test_profile_handles_player_without_one_discipline(self):
        batter_only = {
            **self.profile,
            "has_bowling_stats": False,
            "overall": {**self.profile["overall"], "bowling": {}},
            "season_stats": [
                {
                    **self.profile["season_stats"][0],
                    "has_bowling_stats": False,
                }
            ],
        }
        with (
            patch("cricket_nepal.views.get_player_profile", return_value=batter_only),
            patch(
                "cricket_nepal.views.get_player_radar_comparison",
                return_value={"batting": [], "bowling": []},
            ),
            patch(
                "cricket_nepal.views.get_player_match_performance",
                return_value={"batting": [], "bowling": []},
            ),
        ):
            response = self.client.get(
                reverse("cricket_nepal:player_profile", args=[25])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No bowling statistics available.")
        self.assertContains(response, "No bowling performances for this selection.")
        self.assertContains(response, "No bowling records available.")

    def test_missing_player_returns_404(self):
        with (
            patch("cricket_nepal.views.get_player_profile", return_value=None),
            patch("cricket_nepal.views.get_player_radar_comparison") as radar_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:player_profile", args=[999999])
            )
        self.assertEqual(response.status_code, 404)
        radar_query.assert_not_called()

    @staticmethod
    def _radar_cohort():
        return {
            "batting": [
                {
                    "player_id": 25,
                    "total_runs": 100,
                    "strike_rate": 100.0,
                    "dot_ball_percentage": 20.0,
                    "total_fours": 10,
                    "total_sixes": 2,
                },
                {
                    "player_id": 26,
                    "total_runs": 200,
                    "strike_rate": 150.0,
                    "dot_ball_percentage": 10.0,
                    "total_fours": 5,
                    "total_sixes": 0,
                },
            ],
            "bowling": [
                {
                    "player_id": 25,
                    "wickets": 5,
                    "matches_bowled": 4,
                    "strike_rate": 12.0,
                    "economy": 6.0,
                    "maidens": 1,
                    "dot_ball_percentage": 20.0,
                },
                {
                    "player_id": 26,
                    "wickets": 3,
                    "matches_bowled": 2,
                    "strike_rate": 8.0,
                    "economy": 9.0,
                    "maidens": 3,
                    "dot_ball_percentage": 50.0,
                },
            ],
        }

    def test_radar_charts_use_selected_season_cohort_and_directions(self):
        cohort = self._radar_cohort()
        with (
            patch("cricket_nepal.views.get_player_profile", return_value=self.profile),
            patch(
                "cricket_nepal.views.get_player_radar_comparison",
                return_value=cohort,
            ) as comparison_query,
            patch(
                "cricket_nepal.views.get_player_match_performance",
                return_value={"batting": [], "bowling": []},
            ),
        ):
            response = self.client.get(
                reverse("cricket_nepal:player_profile", args=[25]),
                {"season_id": "1783"},
            )

        self.assertEqual(response.status_code, 200)
        comparison_query.assert_called_once_with(1783)
        batting = response.context["radar_charts"]["batting"]
        bowling = response.context["radar_charts"]["bowling"]
        self.assertTrue(batting["available"])
        self.assertTrue(bowling["available"])
        self.assertEqual(
            [axis["normalized"] for axis in batting["axes"]],
            [0, 0, 0, 100, 100],
        )
        self.assertEqual(
            [axis["normalized"] for axis in bowling["axes"]],
            [100, 0, 100, 0, 100],
        )
        self.assertEqual(batting["axes"][0]["tooltip"], "Total runs: 100")
        self.assertEqual(batting["axes"][1]["label"], "Strike Rate")
        self.assertEqual(batting["axes"][1]["value"], 100.0)
        self.assertEqual(batting["axes"][1]["actual"], "100")
        self.assertEqual(batting["axes"][1]["tooltip"], "Strike Rate: 100")
        self.assertEqual(bowling["axes"][1]["label"], "Bowling Strike Rate")
        self.assertEqual(bowling["axes"][1]["value"], 12.0)
        self.assertEqual(bowling["axes"][1]["actual"], "12")
        self.assertEqual(bowling["axes"][1]["tooltip"], "Bowling Strike Rate: 12")
        self.assertEqual(batting["season_label"], "2024/25")
        self.assertContains(response, "batting-radar-data")
        self.assertContains(response, "bowling-radar-data")
        self.assertContains(response, '<option value="">Overall</option>')
        self.assertContains(response, "Total runs: 100")
        self.assertContains(response, "Economy: 6")

    def test_radar_charts_use_the_other_selected_season(self):
        cohort = self._radar_cohort()
        cohort["batting"][0]["total_runs"] = 300
        cohort["batting"][0]["strike_rate"] = 125.0
        cohort["bowling"][0]["strike_rate"] = 7.0
        with (
            patch("cricket_nepal.views.get_player_profile", return_value=self.profile),
            patch(
                "cricket_nepal.views.get_player_radar_comparison",
                return_value=cohort,
            ) as comparison_query,
            patch(
                "cricket_nepal.views.get_player_match_performance",
                return_value={"batting": [], "bowling": []},
            ) as performance_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:player_profile", args=[25]),
                {"season_id": "1998"},
            )

        self.assertEqual(response.status_code, 200)
        comparison_query.assert_called_once_with(1998)
        performance_query.assert_called_once_with(25, tournament_id=1998)
        charts = response.context["radar_charts"]
        self.assertEqual(charts["batting"]["season_label"], "2025/26")
        self.assertEqual(charts["batting"]["axes"][0]["value"], 300)
        self.assertEqual(charts["batting"]["axes"][0]["normalized"], 100)
        self.assertEqual(charts["batting"]["axes"][1]["value"], 125.0)
        self.assertEqual(charts["bowling"]["season_label"], "2025/26")
        self.assertEqual(charts["bowling"]["axes"][1]["value"], 7.0)
        self.assertEqual(charts["bowling"]["axes"][1]["normalized"], 100)

    def test_combined_radar_cohort_and_missing_metrics_are_not_zero_filled(self):
        from cricket_nepal.views import _build_radar_chart

        cohort = {
            "batting": [
                {
                    "player_id": 25,
                    "total_runs": 0,
                    "strike_rate": None,
                    "dot_ball_percentage": None,
                    "total_fours": 0,
                    "total_sixes": 0,
                },
                {
                    "player_id": 26,
                    "total_runs": 0,
                    "strike_rate": None,
                    "dot_ball_percentage": 50.0,
                    "total_fours": 1,
                    "total_sixes": 0,
                },
            ],
            "bowling": [],
        }
        with (
            patch("cricket_nepal.views.get_player_profile", return_value=self.profile),
            patch(
                "cricket_nepal.views.get_player_radar_comparison",
                return_value=cohort,
            ) as comparison_query,
            patch(
                "cricket_nepal.views.get_player_match_performance",
                return_value={"batting": [], "bowling": []},
            ),
        ):
            response = self.client.get(
                reverse("cricket_nepal:player_profile", args=[25])
            )

        comparison_query.assert_called_once_with(None)
        chart = response.context["radar_charts"]["batting"]
        self.assertEqual(chart["season_label"], "All seasons")
        self.assertTrue(chart["available"])
        self.assertEqual(chart["axes"][0]["normalized"], 100)
        self.assertEqual(chart["axes"][1]["normalized"], None)
        self.assertEqual(chart["axes"][1]["actual"], "Not available")
        self.assertEqual(chart["axes"][2]["normalized"], None)
        self.assertEqual(chart["axes"][2]["actual"], "Not available")
        self.assertFalse(response.context["radar_charts"]["bowling"]["available"])
        self.assertContains(response, "No bowling records available.")
        missing_player_chart = _build_radar_chart(
            cohort["batting"],
            player_id=99,
            axis_definitions=(
                ("Total runs", "total_runs", True, ""),
            ),
            season_label="All seasons",
        )
        self.assertFalse(missing_player_chart["available"])
