import re
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from django.test import Client, SimpleTestCase
from django.urls import reverse

from cricket_nepal.data_access import (
    _build_npl_team_directory,
    list_tables,
    get_player_profile,
    get_player_statistics,
    get_tournaments,
    _npl_points_table,
)
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
        self.assertContains(response, "NPL matches")
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
        self.assertContains(
            response,
            f'href="{reverse("cricket_nepal:teams")}?season_id=1783"',
        )

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


class AboutPageTests(SimpleTestCase):
    def test_about_page_explains_dataset_pipeline_and_source_limitations(self):
        response = self.client.get(reverse("cricket_nepal:about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prepared Parquet exports")
        self.assertContains(response, "Cricsheet player identifiers")
        self.assertContains(response, "licensing details are still being confirmed")
        self.assertContains(response, "Howzat Analytics")

    def test_about_page_describes_consulting_work_and_links_to_company(self):
        response = self.client.get(reverse("cricket_nepal:about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data analysis and consulting practice")
        self.assertContains(response, "data visualization")
        self.assertContains(response, "research and automation")
        self.assertContains(response, 'href="https://howzatanalytics.com/"')
        self.assertContains(response, 'rel="noopener noreferrer"')

    def test_about_page_is_available_from_primary_navigation(self):
        response = self.client.get(reverse("cricket_nepal:about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">About</a>")


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

    def test_npl_match_listing_has_specific_route_and_generic_listing_is_unrouted(self):
        self.assertEqual(reverse("cricket_nepal:npl_matches"), "/npl-matches/")
        self.assertEqual(self.client.get("/matches/").status_code, 404)
        self.assertEqual(
            reverse("cricket_nepal:match_detail", args=["1462596"]),
            "/matches/1462596/",
        )

    def test_match_list_renders_data_and_links_to_detail(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch("cricket_nepal.views.get_teams", return_value=self.teams),
            patch("cricket_nepal.views.get_matches", return_value=[self.sample_match]),
        ):
            response = self.client.get(
                reverse("cricket_nepal:npl_matches"), {"tournament_id": "1783"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Biratnagar Kings")
        self.assertContains(response, "Janakpur Bolts won")
        self.assertContains(response, "by 8 wkts")
        self.assertContains(response, "1 match</h2>")
        self.assertContains(response, "<h1>NPL Matches</h1>", html=True)
        primary_nav = (
            response.content.decode()
            .split('<nav class="primary-nav" aria-label="Main navigation">', 1)[1]
            .split("</nav>", 1)[0]
        )
        self.assertNotIn(">NPL Matches</a>", primary_nav)
        self.assertNotIn(">Matches</a>", primary_nav)
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
                reverse("cricket_nepal:npl_matches"),
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
            response = self.client.get(reverse("cricket_nepal:npl_matches"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Result unavailable")
        self.assertContains(response, "Venue unavailable")
        self.assertContains(response, "Not recorded")

    def test_match_detail_renders_innings_and_player_scorecards(self):
        with patch(
            "cricket_nepal.views.get_match_scorecard",
            return_value={
                **self.sample_match,
                "team_1_slug": "biratnagar-kings",
                "team_2_slug": "janakpur-bolts",
                "winner_slug": "janakpur-bolts",
                "match_format": "T20",
                "city": "Kirtipur",
                "toss_winner_name": "Janakpur Bolts",
                "toss_winner_slug": "janakpur-bolts",
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
                        "batting_team_slug": "biratnagar-kings",
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
        self.assertContains(
            response,
            f'href="{reverse("cricket_nepal:team_profile", args=["biratnagar-kings"])}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("cricket_nepal:team_profile", args=["janakpur-bolts"])}"',
        )
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
    def test_npl_directory_uses_specific_route_and_generic_players_path_is_unrouted(self):
        self.assertEqual(reverse("cricket_nepal:players"), "/npl-players/")
        self.assertEqual(
            self.client.get("/players/").status_code,
            404,
        )
        self.assertEqual(
            reverse("cricket_nepal:player_profile", args=[25]),
            "/players/25/",
        )

    def test_header_players_menu_links_to_npl_and_national_team_pages(self):
        with patch("cricket_nepal.views.get_player_directory", return_value=[]):
            response = self.client.get(reverse("cricket_nepal:players"))

        self.assertEqual(response.status_code, 200)
        rendered = response.content.decode()
        primary_nav = (
            rendered.split('<nav class="primary-nav" aria-label="Main navigation">', 1)[1]
            .split("</nav>", 1)[0]
        )
        self.assertIn(">Players</a>", primary_nav)
        self.assertIn(">NPL Players</a>", primary_nav)
        self.assertIn(">Nepal National Team</a>", primary_nav)
        self.assertIn(reverse("cricket_nepal:players"), primary_nav)
        self.assertIn(reverse("cricket_nepal:national_team_players"), primary_nav)
        self.assertEqual(
            reverse("cricket_nepal:national_team_players"),
            "/nepal-national-team/",
        )

    def test_national_team_page_is_a_placeholder_without_invented_players(self):
        response = self.client.get(reverse("cricket_nepal:national_team_players"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nepal National Team")
        self.assertContains(response, "No Nepal national team player data is available yet.")
        self.assertNotContains(response, "Player profiles")
        self.assertContains(response, reverse("cricket_nepal:players"))

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
    seasons = HomepageTests.tournaments
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
            "titles": 0,
            "win_percentage": 50,
        },
        {
            "team_name": "Kathmandu Gurkhas",
            "team_slug": "kathmandu-gorkhas",
            "seasons": ["2024/25"],
            "participations": [
                {"tournament_id": 1783, "season": "2024/25"},
            ],
            "matches_played": 7,
            "wins": 4,
            "losses": 3,
            "titles": 0,
            "win_percentage": 57.1,
        },
    ]
    overall_directory = {
        "teams": teams,
        "seasons": seasons,
        "selected_season": None,
    }

    def test_directory_shows_team_records_and_profile_links(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.seasons),
            patch(
                "cricket_nepal.views.get_npl_team_directory",
                return_value=self.overall_directory,
            ),
        ):
            response = self.client.get(reverse("cricket_nepal:teams"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Explore all eight NPL franchises")
        self.assertContains(response, "Biratnagar Kings")
        self.assertContains(response, "50.0%")
        self.assertContains(response, "Overall")
        primary_nav = (
            response.content.decode()
            .split('<nav class="primary-nav" aria-label="Main navigation">', 1)[1]
            .split("</nav>", 1)[0]
        )
        self.assertNotIn(">Teams<", primary_nav)
        self.assertContains(
            response,
            reverse("cricket_nepal:team_profile", args=["biratnagar-kings"]),
        )
        self.assertContains(
            response,
            reverse("cricket_nepal:team_profile", args=["kathmandu-gorkhas"]),
        )

    def test_directory_season_filter_preserves_historical_name_and_champion(self):
        selected_season = self.seasons[1]
        season_directory = {
            "teams": [self.teams[1]],
            "seasons": self.seasons,
            "selected_season": selected_season,
        }
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.seasons),
            patch(
                "cricket_nepal.views.get_npl_team_directory",
                return_value=season_directory,
            ) as directory_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:teams"), {"season_id": "1783"}
            )

        self.assertEqual(response.status_code, 200)
        directory_query.assert_called_once_with(1783)
        self.assertContains(response, "Kathmandu Gurkhas")
        self.assertContains(response, "2024/25")

    def test_directory_displays_titles_for_overall_and_season_views(self):
        champions = [
            {
                **self.teams[0],
                "team_name": "Janakpur Bolts",
                "team_slug": "janakpur-bolts",
                "titles": 1,
            },
            {
                **self.teams[0],
                "team_name": "Lumbini Lions",
                "team_slug": "lumbini-lions",
                "titles": 1,
            },
        ]
        overall_directory = {
            "teams": champions,
            "seasons": self.seasons,
            "selected_season": None,
        }
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.seasons),
            patch(
                "cricket_nepal.views.get_npl_team_directory",
                return_value=overall_directory,
            ),
        ):
            response = self.client.get(reverse("cricket_nepal:teams"))

        self.assertContains(response, "1 title")


class NplTeamDirectoryDataTests(SimpleTestCase):
    seasons = HomepageTests.tournaments
    names_by_season = {
        1783: [
            "Biratnagar Kings",
            "Chitwan Rhinos",
            "Janakpur Bolts",
            "Karnali Yaks",
            "Kathmandu Gurkhas",
            "Lumbini Lions",
            "Pokhara Avengers",
            "Sudur Paschim Royals",
        ],
        1998: [
            "Biratnagar Kings",
            "Chitwan Rhinos",
            "Janakpur Bolts",
            "Karnali Yaks",
            "Kathmandu Gorkhas",
            "Lumbini Lions",
            "Pokhara Avengers",
            "Sudur Paschim Royals",
        ],
    }

    def setUp(self):
        self.matches = []
        for season in self.seasons:
            names = self.names_by_season[season["tournament_id"]]
            for index in range(0, len(names), 2):
                self.matches.append(
                    {
                        "tournament_id": season["tournament_id"],
                        "season": season["season"],
                        "team_1_name": names[index],
                        "team_2_name": names[index + 1],
                        "winner_name": names[index],
                        "stage": "League Stage",
                    }
                )
        self.matches.extend(
            [
                {
                    "tournament_id": 1783,
                    "season": "2024/25",
                    "team_1_name": "Janakpur Bolts",
                    "team_2_name": "Sudur Paschim Royals",
                    "winner_name": "Janakpur Bolts",
                    "stage": "Final",
                },
                {
                    "tournament_id": 1998,
                    "season": "2025/26",
                    "team_1_name": "Lumbini Lions",
                    "team_2_name": "Sudur Paschim Royals",
                    "winner_name": "Lumbini Lions",
                    "stage": "Final",
                },
            ]
        )

    def test_teams_route_renders_all_eight_franchises(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.seasons),
            patch(
                "cricket_nepal.views.get_npl_team_directory",
                return_value=_build_npl_team_directory(
                    self.matches, self.seasons
                ),
            ),
        ):
            response = self.client.get(reverse("cricket_nepal:teams"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["teams"]), 8)
        for team in response.context["teams"]:
            self.assertContains(response, team["team_name"])
            self.assertContains(
                response,
                reverse("cricket_nepal:team_profile", args=[team["team_slug"]]),
            )

    def test_all_franchises_have_profile_links_and_overall_titles(self):
        directory = _build_npl_team_directory(self.matches, self.seasons)
        by_name = {team["team_name"]: team for team in directory["teams"]}
        expected_names = {
            "Biratnagar Kings",
            "Chitwan Rhinos",
            "Janakpur Bolts",
            "Karnali Yaks",
            "Kathmandu Gorkhas",
            "Lumbini Lions",
            "Pokhara Avengers",
            "Sudur Paschim Royals",
        }

        self.assertEqual(set(by_name), expected_names)
        self.assertEqual(len(directory["teams"]), 8)
        self.assertEqual(by_name["Janakpur Bolts"]["titles"], 1)
        self.assertEqual(by_name["Lumbini Lions"]["titles"], 1)
        self.assertEqual(by_name["Kathmandu Gorkhas"]["titles"], 0)
        for team in directory["teams"]:
            self.assertEqual(
                reverse("cricket_nepal:team_profile", args=[team["team_slug"]]),
                f"/teams/{team['team_slug']}/",
            )

    def test_season_data_preserves_kathmandu_names_and_finals(self):
        older = _build_npl_team_directory(self.matches, self.seasons, 1783)
        newer = _build_npl_team_directory(self.matches, self.seasons, 1998)
        older_by_name = {team["team_name"]: team for team in older["teams"]}
        newer_by_name = {team["team_name"]: team for team in newer["teams"]}

        self.assertEqual(len(older["teams"]), 8)
        self.assertEqual(len(newer["teams"]), 8)
        self.assertIn("Kathmandu Gurkhas", older_by_name)
        self.assertNotIn("Kathmandu Gorkhas", older_by_name)
        self.assertIn("Kathmandu Gorkhas", newer_by_name)
        self.assertNotIn("Kathmandu Gurkhas", newer_by_name)
        self.assertEqual(older["selected_season"]["season"], "2024/25")
        self.assertEqual(newer["selected_season"]["season"], "2025/26")
        self.assertEqual(older_by_name["Janakpur Bolts"]["titles"], 1)
        self.assertEqual(newer_by_name["Lumbini Lions"]["titles"], 1)

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
                "opponent_slug": "janakpur-bolts",
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
        rendered_profile = response.content.decode()
        self.assertLess(
            rendered_profile.index('id="team-players-heading"'),
            rendered_profile.index('id="team-batting-heading"'),
        )
        self.assertContains(response, "Team batting performance")
        self.assertContains(response, "Team bowling performance")
        self.assertContains(response, "Match history")
        self.assertContains(
            response,
            f'href="{reverse("cricket_nepal:team_profile", args=["janakpur-bolts"])}"',
        )
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

    def test_recent_form_indicator_runs_oldest_to_newest_left_to_right(self):
        profile = {
            **self.profile,
            "recent_form": [
                {
                    "match_id": "newest",
                    "match_date": "2025-12-11",
                    "opponent": "Newest Opponent",
                    "result": "Lost",
                    "result_class": "loss",
                    "recent_summary": "Lost by 5 wickets",
                },
                {
                    "match_id": "second",
                    "match_date": "2025-12-09",
                    "opponent": "Second Opponent",
                    "result": "Lost",
                    "result_class": "loss",
                    "recent_summary": "Lost by 77 runs",
                },
                {
                    "match_id": "middle",
                    "match_date": "2025-12-06",
                    "opponent": "Middle Opponent",
                    "result": "Won",
                    "result_class": "win",
                    "recent_summary": "Won by 10 runs",
                },
                {
                    "match_id": "fourth",
                    "match_date": "2025-12-03",
                    "opponent": "Fourth Opponent",
                    "result": "Lost",
                    "result_class": "loss",
                    "recent_summary": "Lost by 5 wickets",
                },
                {
                    "match_id": "oldest",
                    "match_date": "2025-11-28",
                    "opponent": "Oldest Opponent",
                    "result": "Won",
                    "result_class": "win",
                    "recent_summary": "Won by 3 wickets",
                },
            ],
        }
        with (
            patch("cricket_nepal.views.get_team_directory", return_value=self.teams),
            patch("cricket_nepal.views.get_team_profile", return_value=profile),
        ):
            response = self.client.get(
                reverse("cricket_nepal:team_profile", args=["biratnagar-kings"])
            )

        self.assertEqual(response.status_code, 200)
        rendered_profile = response.content.decode()
        indicator_start = rendered_profile.index('class="team-form-indicator"')
        indicator_end = rendered_profile.index("</div>", indicator_start)
        indicator = rendered_profile[indicator_start:indicator_end]
        self.assertIn('dir="ltr"', indicator)
        self.assertLess(indicator.index("Oldest Opponent"), indicator.index("Fourth Opponent"))
        self.assertLess(indicator.index("Fourth Opponent"), indicator.index("Middle Opponent"))
        self.assertLess(indicator.index("Middle Opponent"), indicator.index("Second Opponent"))
        self.assertLess(indicator.index("Second Opponent"), indicator.index("Newest Opponent"))
        self.assertEqual(
            re.findall(
                r'class="team-form-result [^"]+" title="[^"]+">\s*(\w+)\s*</span>',
                indicator,
            ),
            ["W", "L", "W", "L", "L"],
        )

        recent_list_start = rendered_profile.index('<ol class="team-recent-list">')
        recent_list_end = rendered_profile.index("</ol>", recent_list_start)
        recent_list = rendered_profile[recent_list_start:recent_list_end]
        self.assertLess(recent_list.index("Newest Opponent"), recent_list.index("Second Opponent"))
        self.assertLess(recent_list.index("Second Opponent"), recent_list.index("Middle Opponent"))
        self.assertLess(recent_list.index("Middle Opponent"), recent_list.index("Fourth Opponent"))
        self.assertLess(recent_list.index("Fourth Opponent"), recent_list.index("Oldest Opponent"))

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


class PlayerStatisticsPageTests(TestCase):
    def test_overall_rates_match_existing_player_profile_aggregates(self):
        statistics = get_player_statistics(minimum_matches=0)
        multi_season_player = next(
            (
                row
                for row in statistics["batting"]
                if len(get_player_profile(row["player_id"])["season_stats"]) > 1
            ),
            None,
        )
        self.assertIsNotNone(multi_season_player)

        profile = get_player_profile(multi_season_player["player_id"])
        batting = profile["overall"]["batting"]
        row = multi_season_player
        self.assertEqual(row["runs"], batting["runs"])
        self.assertAlmostEqual(row["average"], batting["average"])
        self.assertAlmostEqual(row["strike_rate"], batting["strike_rate"])
        self.assertAlmostEqual(
            row["dot_ball_percentage"], batting["dot_ball_percentage"]
        )

        bowling_row = next(
            item
            for item in statistics["bowling"]
            if item["player_id"] == multi_season_player["player_id"]
        )
        bowling = profile["overall"]["bowling"]
        self.assertEqual(bowling_row["wickets"], bowling["wickets"])
        self.assertAlmostEqual(bowling_row["average"], bowling["average"])
        self.assertAlmostEqual(bowling_row["economy"], bowling["economy"])
        self.assertAlmostEqual(bowling_row["strike_rate"], bowling["strike_rate"])

    def test_tournament_and_season_filters_match_profile_season_totals(self):
        tournament = get_tournaments()[0]
        statistics = get_player_statistics(
            tournament_name=tournament["tournament_name"],
            season=tournament["season"],
            minimum_matches=0,
        )
        self.assertEqual(
            statistics["selected_tournament"], tournament["tournament_name"]
        )
        self.assertEqual(statistics["selected_season"], tournament["season"])
        self.assertIn(tournament["season"], statistics["season_options"])

        row = statistics["batting"][0]
        profile = get_player_profile(row["player_id"])
        profile_season = next(
            season
            for season in profile["season_stats"]
            if season["tournament_id"] == tournament["tournament_id"]
        )
        self.assertEqual(row["runs"], profile_season["total_runs"])
        self.assertAlmostEqual(
            row["average"], profile_season["batting_average"], places=2
        )
        self.assertAlmostEqual(
            row["strike_rate"], profile_season["batting_strike_rate"], places=2
        )

    def test_team_search_and_minimum_match_filters_combine(self):
        all_statistics = get_player_statistics(minimum_matches=0)
        target = all_statistics["batting"][0]
        target_team = target["teams"][0]["team_name"]
        search_text = target["player_name"][:4]
        filtered = get_player_statistics(
            team_name=target_team,
            search_term=search_text,
            minimum_matches=1,
        )
        self.assertEqual(filtered["selected_team"], target_team)
        self.assertTrue(filtered["batting"])
        self.assertTrue(
            all(
                search_text.casefold() in row["player_name"].casefold()
                for row in filtered["batting"]
            )
        )
        self.assertTrue(
            all(
                team["team_name"] == target_team
                for row in filtered["batting"]
                for team in row["teams"]
            )
        )
        self.assertTrue(
            all(
                record["team_name"] == target_team
                and search_text.casefold() in record["player_name"].casefold()
                for records in filtered["best_performances"].values()
                for record in records
            )
        )

        qualified = get_player_statistics(minimum_matches=3)
        self.assertTrue(all(row["matches"] >= 3 for row in qualified["batting"]))
        self.assertTrue(all(row["matches"] >= 3 for row in qualified["bowling"]))

    def test_leaderboard_sorting_and_rate_qualifications(self):
        runs = get_player_statistics(
            minimum_matches=0,
            batting_sort="runs",
            bowling_sort="wickets",
        )
        self.assertEqual(
            [row["runs"] for row in runs["batting"]],
            sorted((row["runs"] for row in runs["batting"]), reverse=True),
        )
        self.assertEqual(
            [row["wickets"] for row in runs["bowling"]],
            sorted((row["wickets"] for row in runs["bowling"]), reverse=True),
        )

        rate_sorted = get_player_statistics(
            minimum_matches=0,
            batting_sort="average",
            bowling_sort="economy",
        )
        qualified_batting = [
            row for row in rate_sorted["batting"] if row["average_qualified"]
        ]
        self.assertEqual(
            [row["average"] for row in qualified_batting],
            sorted(
                (row["average"] for row in qualified_batting),
                reverse=True,
            ),
        )
        self.assertTrue(
            all(
                row["rank"] is None
                for row in rate_sorted["batting"]
                if not row["average_qualified"]
            )
        )
        qualified_bowling = [
            row for row in rate_sorted["bowling"] if row["economy_qualified"]
        ]
        self.assertEqual(
            [row["economy"] for row in qualified_bowling],
            sorted(row["economy"] for row in qualified_bowling),
        )
        self.assertTrue(
            all(
                row["rank"] is None
                for row in rate_sorted["bowling"]
                if not row["economy_qualified"]
            )
        )

    def test_zero_dismissal_and_zero_wicket_rates_are_unranked(self):
        statistics = get_player_statistics(
            minimum_matches=0,
            batting_sort="average",
            bowling_sort="average",
        )
        zero_dismissal = [
            row for row in statistics["batting"] if row["dismissals"] == 0
        ]
        zero_wicket = [
            row for row in statistics["bowling"] if row["wickets"] == 0
        ]
        self.assertTrue(zero_dismissal)
        self.assertTrue(zero_wicket)
        self.assertTrue(
            all(
                row["average"] is None and row["rank"] is None
                for row in zero_dismissal
            )
        )
        self.assertTrue(
            all(
                row["average"] is None and row["rank"] is None
                for row in zero_wicket
            )
        )

    def test_kathmandu_historical_names_are_preserved_by_season(self):
        for season, historical_name in (
            ("2024/25", "Kathmandu Gurkhas"),
            ("2025/26", "Kathmandu Gorkhas"),
        ):
            statistics = get_player_statistics(
                season=season,
                team_name=historical_name,
                minimum_matches=0,
            )
            self.assertEqual(statistics["selected_team"], historical_name)
            self.assertTrue(statistics["batting"])
            self.assertTrue(
                all(
                    team["team_name"] == historical_name
                    for row in statistics["batting"]
                    for team in row["teams"]
                )
            )

        overall = get_player_statistics(
            team_name="Kathmandu Gorkhas",
            minimum_matches=0,
        )
        self.assertIn("Kathmandu Gorkhas", overall["team_options"])
        self.assertNotIn("Kathmandu Gurkhas", overall["team_options"])
        self.assertTrue(
            all(
                team["team_name"] == "Kathmandu Gorkhas"
                for row in overall["batting"]
                for team in row["teams"]
            )
        )

    def test_best_performance_qualifications_apply_to_selected_scope(self):
        statistics = get_player_statistics(minimum_matches=0)
        self.assertTrue(statistics["best_performances"]["highest_strike_rate"])
        self.assertTrue(statistics["best_performances"]["best_economy"])
        self.assertTrue(
            all(
                row["extra_value"] >= 10
                for row in statistics["best_performances"]["highest_strike_rate"]
            )
        )
        self.assertTrue(
            all(
                row["extra_value"] >= 24
                for row in statistics["best_performances"]["best_economy"]
            )
        )

    def test_page_links_to_players_teams_tournaments_and_scorecards(self):
        response = Client().get(reverse("cricket_nepal:player_statistics"))
        self.assertEqual(response.status_code, 200)
        rendered = response.content.decode()
        self.assertIn("Player Statistics", rendered)
        self.assertIn("All Tournaments", rendered)

        statistics = response.context["statistics"]
        self.assertIn(
            reverse(
                "cricket_nepal:player_profile",
                args=[statistics["batting"][0]["player_id"]],
            ),
            rendered,
        )
        self.assertIn(
            reverse(
                "cricket_nepal:team_profile",
                args=[statistics["batting"][0]["teams"][0]["team_slug"]],
            ),
            rendered,
        )
        self.assertIn(
            reverse(
                "cricket_nepal:tournament_overview",
                kwargs={"tournament_slug": "nepal-premier-league"},
            ),
            rendered,
        )
        best_score = statistics["best_performances"]["highest_score"][0]
        self.assertIn(
            reverse("cricket_nepal:match_detail", args=[best_score["match_id"]]),
            rendered,
        )

    def test_statistics_views_separate_batting_bowling_and_comparison(self):
        client = Client()
        batting_response = client.get(
            reverse("cricket_nepal:player_statistics_batting")
        )
        batting_html = batting_response.content.decode()
        self.assertEqual(batting_response.status_code, 200)
        self.assertIn("Batting statistics", batting_html)
        self.assertNotIn("Bowling statistics", batting_html)
        self.assertNotIn("Not qualified", batting_html)

        bowling_response = client.get(
            reverse("cricket_nepal:player_statistics_bowling")
        )
        bowling_html = bowling_response.content.decode()
        self.assertEqual(bowling_response.status_code, 200)
        self.assertIn("Bowling statistics", bowling_html)
        self.assertNotIn("Batting statistics", bowling_html)
        self.assertNotIn("Not qualified", bowling_html)

        compare_response = client.get(
            reverse("cricket_nepal:player_statistics_compare")
        )
        self.assertEqual(compare_response.status_code, 302)
        self.assertEqual(
            compare_response["Location"],
            reverse("cricket_nepal:player_comparison"),
        )

    def test_fielding_page_has_active_submenu_and_data_unavailable_state(self):
        response = Client().get(reverse("cricket_nepal:player_statistics_fielding"))

        self.assertEqual(response.status_code, 200)
        rendered = response.content.decode()
        nav = rendered.split(
            '<div class="nav-dropdown-menu">', 2
        )[2].split("</div>", 1)[0]
        self.assertIn(
            f'href="{reverse("cricket_nepal:player_statistics_fielding")}" aria-current="page">Fielding</a>',
            nav,
        )
        self.assertNotIn(
            f'href="{reverse("cricket_nepal:player_statistics_batting")}" aria-current="page"',
            nav,
        )
        self.assertNotIn(
            f'href="{reverse("cricket_nepal:player_statistics_bowling")}" aria-current="page"',
            nav,
        )
        self.assertNotIn("<details", rendered)
        self.assertIn('<div class="nav-dropdown">', rendered)
        for heading in (
            "Rank",
            "Player",
            "Team",
            "Tournament",
            "Season",
            "Matches",
            "Catches",
            "Stumpings",
            "Run-outs",
            "Total dismissals",
            "Dismissals per match",
        ):
            self.assertIn(heading, rendered)
        self.assertIn("Fielding records are not available", rendered)
        self.assertIn("No statistics are inferred", rendered)
        self.assertNotIn("fielding_stats_by_match", list_tables())

    def test_fielding_page_uses_dynamic_filters_and_preserves_filter_state(self):
        tournament = get_tournaments()[0]
        metadata = get_player_statistics(
            tournament_name=tournament["tournament_name"],
            season=tournament["season"],
            minimum_matches=0,
            player_ids=(),
            include_best_performances=False,
        )
        self.assertTrue(metadata["team_options"])
        team = metadata["team_options"][0]
        response = Client().get(
            reverse("cricket_nepal:player_statistics_fielding"),
            {
                "tournament": tournament["tournament_name"],
                "season": tournament["season"],
                "team": team,
                "q": "K",
                "minimum_matches": "3",
                "fielding_sort": "catches",
            },
        )

        self.assertEqual(response.status_code, 200)
        statistics = response.context["statistics"]
        self.assertEqual(statistics["selected_tournament"], tournament["tournament_name"])
        self.assertEqual(statistics["selected_season"], tournament["season"])
        self.assertEqual(statistics["selected_team"], team)
        self.assertEqual(statistics["search_term"], "K")
        self.assertEqual(statistics["minimum_matches"], 3)
        self.assertEqual(
            statistics["tournament_options"],
            metadata["tournament_options"],
        )
        self.assertEqual(
            statistics["season_options"],
            metadata["season_options"],
        )
        self.assertEqual(
            statistics["team_options"],
            metadata["team_options"],
        )
        self.assertEqual(response.context["fielding_sort"], "catches")
        rendered = response.content.decode()
        self.assertIn(f'<option value="{team}" selected>', rendered)
        self.assertIn('<option value="catches" selected>', rendered)

    def test_fielding_filter_values_are_bounded_and_sort_is_validated(self):
        response = Client().get(
            reverse("cricket_nepal:player_statistics_fielding"),
            {
                "minimum_matches": "99",
                "q": "x" * 150,
                "fielding_sort": "unknown",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["statistics"]["minimum_matches"], 20)
        self.assertEqual(len(response.context["statistics"]["search_term"]), 100)
        self.assertEqual(response.context["fielding_sort"], "dismissals")

    def test_player_statistics_header_has_three_separate_pages(self):
        response = Client().get(reverse("cricket_nepal:player_statistics"))
        rendered = response.content.decode()
        self.assertEqual(response.status_code, 200)
        for page_name in (
            "player_statistics_batting",
            "player_statistics_bowling",
            "player_statistics_fielding",
        ):
            self.assertIn(reverse(f"cricket_nepal:{page_name}"), rendered)
        self.assertIn(reverse("cricket_nepal:player_comparison"), rendered)
        self.assertNotIn('name="view"', rendered)

    def test_filters_reject_unknown_values_and_search_is_case_insensitive(self):
        statistics = get_player_statistics(
            tournament_name="Not a tournament",
            season="Not a season",
            team_name="Not a team",
            search_term="rk paudel",
            minimum_matches=0,
        )
        self.assertEqual(statistics["selected_tournament"], "")
        self.assertEqual(statistics["selected_season"], "")
        self.assertEqual(statistics["selected_team"], "")
        self.assertEqual(
            set(statistics["tournament_options"]),
            {tournament["tournament_name"] for tournament in get_tournaments()},
        )
        self.assertTrue(statistics["batting"])
        self.assertTrue(
            all(
                "rk paudel" in row["player_name"].casefold()
                for row in statistics["batting"]
            )
        )


class PlayerComparisonPageTests(TestCase):
    def test_comparison_page_has_two_initial_cards_and_shared_filters(self):
        response = Client().get(reverse("cricket_nepal:player_comparison"))
        self.assertEqual(response.status_code, 200)
        rendered = response.content.decode()
        self.assertIn("Build your comparison", rendered)
        self.assertIn("Add Player", rendered)
        self.assertIn("All Tournaments", rendered)
        self.assertIn("All Seasons", rendered)
        self.assertIn("All Teams", rendered)
        self.assertIn("player-comparison.js", rendered)
        script_path = (
            Path(__file__).parent
            / "static"
            / "cricket_nepal"
            / "js"
            / "player-comparison.js"
        )
        script = script_path.read_text()
        self.assertIn("addCard();\n    addCard();", script)

    def test_player_search_returns_profile_links(self):
        players = get_player_statistics(minimum_matches=0)["batting"]
        player_name = players[0]["player_name"]
        response = Client().get(
            reverse("cricket_nepal:player_comparison_search"),
            {"q": player_name[:4]},
        )
        self.assertEqual(response.status_code, 200)
        matches = response.json()["players"]
        self.assertTrue(matches)
        self.assertTrue(
            all(
                "profile_url" in player
                and player_name[:4].casefold() in player["player_name"].casefold()
                for player in matches
            )
        )

    def test_comparison_accepts_multiple_players_and_deduplicates_ids(self):
        statistics = get_player_statistics(minimum_matches=0)
        player_ids = [
            row["player_id"] for row in statistics["batting"][:3]
        ]
        self.assertEqual(len(set(player_ids)), 3)
        response = Client().get(
            reverse("cricket_nepal:player_comparison_data"),
            [("player", player_ids[0]), ("player", player_ids[0])]
            + [("player", player_id) for player_id in player_ids[1:]],
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [player["player_id"] for player in payload["players"]],
            player_ids,
        )
        self.assertTrue(all(player["profile_url"] for player in payload["players"]))

    def test_comparison_uses_validated_rates_and_full_cohort_radar_normalization(self):
        statistics = get_player_statistics(minimum_matches=0)
        run_values = [row["runs"] for row in statistics["batting"]]
        minimum_runs = min(run_values)
        maximum_runs = max(run_values)
        candidates = [
            row
            for row in statistics["batting"]
            if row["average"] is not None
            and row["strike_rate"] is not None
            and minimum_runs < row["runs"] < maximum_runs
        ][:2]
        self.assertEqual(len(candidates), 2)
        player_ids = [row["player_id"] for row in candidates]
        response = Client().get(
            reverse("cricket_nepal:player_comparison_data"),
            [("player", player_id) for player_id in player_ids],
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        by_id = {player["player_id"]: player for player in payload["players"]}
        single_player_response = Client().get(
            reverse("cricket_nepal:player_comparison_data"),
            {"player": player_ids[0]},
        )
        self.assertEqual(single_player_response.status_code, 200)
        single_player = single_player_response.json()["players"][0]

        for expected in candidates:
            actual = by_id[expected["player_id"]]["batting"]
            self.assertEqual(actual["runs"], expected["runs"])
            self.assertAlmostEqual(actual["average"], expected["average"])
            self.assertAlmostEqual(actual["strike_rate"], expected["strike_rate"])

        batting_axes = by_id[player_ids[0]]["radar"]["batting"]["axes"]
        self.assertEqual(
            [axis["label"] for axis in batting_axes],
            [
                "Runs",
                "Batting Average",
                "Strike Rate",
                "Fours",
                "Sixes",
                "Dot-ball %",
            ],
        )
        runs_axis = batting_axes[0]
        expected_normalized_runs = (
            (candidates[0]["runs"] - minimum_runs)
            * 100
            / (maximum_runs - minimum_runs)
        )
        self.assertAlmostEqual(runs_axis["normalized"], expected_normalized_runs)
        self.assertAlmostEqual(
            single_player["radar"]["batting"]["axes"][0]["normalized"],
            expected_normalized_runs,
        )
        self.assertTrue(
            all(axis["normalized"] is not None for axis in batting_axes)
        )

    def test_comparison_radar_uses_the_current_filter_cohort(self):
        tournament = get_tournaments()[0]
        statistics = get_player_statistics(
            tournament_name=tournament["tournament_name"],
            season=tournament["season"],
            minimum_matches=0,
        )
        run_values = [row["runs"] for row in statistics["batting"]]
        minimum_runs = min(run_values)
        maximum_runs = max(run_values)
        batting_candidate = next(
            row
            for row in statistics["batting"]
            if minimum_runs < row["runs"] < maximum_runs
        )
        wicket_values = [row["wickets"] for row in statistics["bowling"]]
        minimum_wickets = min(wicket_values)
        maximum_wickets = max(wicket_values)
        bowling_candidate = next(
            row
            for row in statistics["bowling"]
            if minimum_wickets < row["wickets"] < maximum_wickets
        )
        player_ids = list(
            dict.fromkeys(
                (batting_candidate["player_id"], bowling_candidate["player_id"])
            )
        )
        filters = {
            "tournament": tournament["tournament_name"],
            "season": tournament["season"],
        }
        response = Client().get(
            reverse("cricket_nepal:player_comparison_data"),
            [("player", player_id) for player_id in player_ids]
            + list(filters.items()),
        )
        self.assertEqual(response.status_code, 200)
        players_by_id = {
            player["player_id"]: player for player in response.json()["players"]
        }
        expected_normalized_runs = (
            (batting_candidate["runs"] - minimum_runs)
            * 100
            / (maximum_runs - minimum_runs)
        )
        expected_normalized_wickets = (
            (bowling_candidate["wickets"] - minimum_wickets)
            * 100
            / (maximum_wickets - minimum_wickets)
        )
        self.assertAlmostEqual(
            players_by_id[batting_candidate["player_id"]]["radar"]["batting"]["axes"][
                0
            ]["normalized"],
            expected_normalized_runs,
        )
        self.assertAlmostEqual(
            players_by_id[bowling_candidate["player_id"]]["radar"]["bowling"]["axes"][
                0
            ]["normalized"],
            expected_normalized_wickets,
        )
        for candidate, kind, axis_index, expected in (
            (batting_candidate, "batting", 0, expected_normalized_runs),
            (bowling_candidate, "bowling", 0, expected_normalized_wickets),
        ):
            single_response = Client().get(
                reverse("cricket_nepal:player_comparison_data"),
                {"player": candidate["player_id"], **filters},
            )
            self.assertEqual(single_response.status_code, 200)
            single_player = single_response.json()["players"][0]
            self.assertAlmostEqual(
                single_player["radar"][kind]["axes"][axis_index]["normalized"],
                expected,
            )

    def test_radar_normalization_respects_batting_and_bowling_metric_direction(self):
        statistics = get_player_statistics(minimum_matches=0)
        batting_pair = next(
            (
                (left, right)
                for index, left in enumerate(statistics["batting"])
                for right in statistics["batting"][index + 1 :]
                if left["dot_ball_percentage"] is not None
                and right["dot_ball_percentage"] is not None
                and left["dot_ball_percentage"] != right["dot_ball_percentage"]
            )
        )
        batting_response = Client().get(
            reverse("cricket_nepal:player_comparison_data"),
            [("player", row["player_id"]) for row in batting_pair],
        )
        batting_players = {
            player["player_id"]: player
            for player in batting_response.json()["players"]
        }
        lower_dots = min(batting_pair, key=lambda row: row["dot_ball_percentage"])
        higher_dots = max(batting_pair, key=lambda row: row["dot_ball_percentage"])
        self.assertGreater(
            batting_players[lower_dots["player_id"]]["radar"]["batting"]["axes"][5][
                "normalized"
            ],
            batting_players[higher_dots["player_id"]]["radar"]["batting"]["axes"][5][
                "normalized"
            ],
        )

        bowling_pair = next(
            (
                (left, right)
                for index, left in enumerate(statistics["bowling"])
                for right in statistics["bowling"][index + 1 :]
                if left["average"] is not None
                and right["average"] is not None
                and left["average"] != right["average"]
            )
        )
        bowling_response = Client().get(
            reverse("cricket_nepal:player_comparison_data"),
            [("player", row["player_id"]) for row in bowling_pair],
        )
        bowling_players = {
            player["player_id"]: player
            for player in bowling_response.json()["players"]
        }
        lower_average = min(bowling_pair, key=lambda row: row["average"])
        higher_average = max(bowling_pair, key=lambda row: row["average"])
        self.assertGreater(
            bowling_players[lower_average["player_id"]]["radar"]["bowling"]["axes"][1][
                "normalized"
            ],
            bowling_players[higher_average["player_id"]]["radar"]["bowling"]["axes"][1][
                "normalized"
            ],
        )

    def test_comparison_filters_apply_and_recalculate_selected_scope(self):
        tournament = get_tournaments()[0]
        scoped_stats = get_player_statistics(
            tournament_name=tournament["tournament_name"],
            season=tournament["season"],
            minimum_matches=0,
        )
        player_id = scoped_stats["batting"][0]["player_id"]
        response = Client().get(
            reverse("cricket_nepal:player_comparison_data"),
            {
                "player": player_id,
                "tournament": tournament["tournament_name"],
                "season": tournament["season"],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        player = payload["players"][0]
        self.assertEqual(payload["filters"]["selected_tournament"], tournament["tournament_name"])
        self.assertEqual(payload["filters"]["selected_season"], tournament["season"])
        profile = get_player_profile(player_id)
        profile_season = next(
            row
            for row in profile["season_stats"]
            if row["tournament_id"] == tournament["tournament_id"]
        )
        self.assertEqual(player["batting"]["runs"], profile_season["total_runs"])
        self.assertAlmostEqual(
            player["batting"]["average"],
            profile_season["batting_average"],
            places=2,
        )

    def test_comparison_team_filter_applies_to_every_selected_player(self):
        statistics = get_player_statistics(minimum_matches=0)
        player = statistics["batting"][0]
        team_name = player["teams"][0]["team_name"]
        response = Client().get(
            reverse("cricket_nepal:player_comparison_data"),
            {"player": player["player_id"], "team": team_name},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["filters"]["selected_team"], team_name)
        self.assertIsNotNone(payload["players"][0]["batting"])

    def test_empty_and_missing_statistics_are_graceful(self):
        client = Client()
        empty_response = client.get(reverse("cricket_nepal:player_comparison_data"))
        self.assertEqual(empty_response.status_code, 200)
        self.assertEqual(empty_response.json()["players"], [])

        statistics = get_player_statistics(minimum_matches=0)
        selected = statistics["batting"][0]
        other_team = next(
            team
            for team in statistics["team_options"]
            if team not in {entry["team_name"] for entry in selected["teams"]}
        )
        missing_response = client.get(
            reverse("cricket_nepal:player_comparison_data"),
            {"player": selected["player_id"], "team": other_team},
        )
        self.assertEqual(missing_response.status_code, 200)
        missing_player = missing_response.json()["players"][0]
        self.assertIsNone(missing_player["batting"])
        self.assertIsNone(missing_player["bowling"])
        self.assertFalse(missing_player["radar"]["batting"]["available"])
        self.assertFalse(missing_player["radar"]["bowling"]["available"])

    def test_batting_only_and_bowling_only_players_have_partial_comparisons(self):
        statistics = get_player_statistics(minimum_matches=0)
        batting_ids = {row["player_id"] for row in statistics["batting"]}
        bowling_ids = {row["player_id"] for row in statistics["bowling"]}
        batting_only = next(iter(batting_ids - bowling_ids))
        bowling_only = next(iter(bowling_ids - batting_ids))
        response = Client().get(
            reverse("cricket_nepal:player_comparison_data"),
            [("player", batting_only), ("player", bowling_only)],
        )
        self.assertEqual(response.status_code, 200)
        players = {
            player["player_id"]: player for player in response.json()["players"]
        }
        self.assertIsNotNone(players[batting_only]["batting"])
        self.assertIsNone(players[batting_only]["bowling"])
        self.assertFalse(players[batting_only]["radar"]["bowling"]["available"])
        self.assertIsNone(players[bowling_only]["batting"])
        self.assertIsNotNone(players[bowling_only]["bowling"])
        self.assertFalse(players[bowling_only]["radar"]["batting"]["available"])

    def test_invalid_comparison_player_ids_are_rejected(self):
        client = Client()
        malformed = client.get(
            reverse("cricket_nepal:player_comparison_data"),
            {"player": "not-an-id"},
        )
        self.assertEqual(malformed.status_code, 400)
        unknown = client.get(
            reverse("cricket_nepal:player_comparison_data"),
            {"player": 999999999},
        )
        self.assertEqual(unknown.status_code, 404)

    def test_player_comparison_is_a_top_level_navigation_item(self):
        response = Client().get(reverse("cricket_nepal:player_comparison"))
        rendered = response.content.decode()
        self.assertIn(reverse("cricket_nepal:player_comparison"), rendered)
