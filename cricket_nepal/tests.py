from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse


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
    overview_by_tournament = {
        1998: {
            "matches_played": 32,
            "teams_count": 8,
            "players_count": 139,
            "total_runs": 1000,
            "total_wickets": 200,
            "leading_run_scorer": {"player_name": "Latest Batter", "total_runs": 300},
            "leading_wicket_taker": {"player_name": "Latest Bowler", "wickets": 20},
        },
        1783: {
            "matches_played": 32,
            "teams_count": 8,
            "players_count": 126,
            "total_runs": 900,
            "total_wickets": 180,
            "leading_run_scorer": {"player_name": "Earlier Batter", "total_runs": 250},
            "leading_wicket_taker": {"player_name": "Earlier Bowler", "wickets": 18},
        },
    }

    def test_homepage_renders_both_database_tournaments(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch(
                "cricket_nepal.views.get_tournament_overview",
                return_value=self.overview_by_tournament[1998],
            ),
        ):
            response = self.client.get(reverse("cricket_nepal:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The story of Nepal cricket")
        self.assertContains(response, "Nepal Premier League (2024/25)")
        self.assertContains(response, "Nepal Premier League (2025/26)")

    def test_latest_tournament_is_selected_by_default(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch(
                "cricket_nepal.views.get_tournament_overview",
                return_value=self.overview_by_tournament[1998],
            ) as overview_query,
        ):
            response = self.client.get(reverse("cricket_nepal:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_tournament"]["season"], "2025/26")
        overview_query.assert_called_once_with(1998)

    def test_visitors_can_select_another_tournament(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch(
                "cricket_nepal.views.get_tournament_overview",
                return_value=self.overview_by_tournament[1783],
            ) as overview_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:home"), {"tournament_id": "1783"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_tournament"]["tournament_id"], 1783)
        self.assertEqual(response.context["selected_tournament"]["season"], "2024/25")
        overview_query.assert_called_once_with(1783)
        self.assertContains(response, "Earlier Batter")
        self.assertContains(response, "250 runs")

    def test_invalid_tournament_id_falls_back_to_latest(self):
        with (
            patch("cricket_nepal.views.get_tournaments", return_value=self.tournaments),
            patch(
                "cricket_nepal.views.get_tournament_overview",
                return_value=self.overview_by_tournament[1998],
            ) as overview_query,
        ):
            response = self.client.get(
                reverse("cricket_nepal:home"), {"tournament_id": "not-an-id"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_tournament"]["season"], "2025/26")
        overview_query.assert_called_once_with(1998)


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


class PlayerProfileTests(SimpleTestCase):
    profile = {
        "player_id": 25,
        "player_name": "A Player",
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
                    "matches_played": 4,
                    "dot_ball_percentage": 20.0,
                    "total_fours": 10,
                    "total_sixes": 2,
                },
                {
                    "player_id": 26,
                    "total_runs": 200,
                    "matches_played": 2,
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
                    "economy": 6.0,
                    "maidens": 1,
                    "dot_ball_percentage": 20.0,
                },
                {
                    "player_id": 26,
                    "wickets": 3,
                    "matches_bowled": 2,
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
            [0, 100, 0, 100, 100],
        )
        self.assertEqual(
            [axis["normalized"] for axis in bowling["axes"]],
            [100, 100, 100, 0, 100],
        )
        self.assertEqual(batting["axes"][0]["tooltip"], "Total runs: 100")
        self.assertEqual(batting["season_label"], "2024/25")
        self.assertContains(response, "batting-radar-data")
        self.assertContains(response, "bowling-radar-data")
        self.assertContains(response, "Total runs: 100")
        self.assertContains(response, "Economy: 6")

    def test_radar_charts_use_the_other_selected_season(self):
        cohort = self._radar_cohort()
        cohort["batting"][0]["total_runs"] = 300
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
        self.assertEqual(charts["bowling"]["season_label"], "2025/26")

    def test_combined_radar_cohort_and_missing_metrics_are_not_zero_filled(self):
        from cricket_nepal.views import _build_radar_chart

        cohort = {
            "batting": [
                {
                    "player_id": 25,
                    "total_runs": 0,
                    "matches_played": 1,
                    "dot_ball_percentage": None,
                    "total_fours": 0,
                    "total_sixes": 0,
                },
                {
                    "player_id": 26,
                    "total_runs": 0,
                    "matches_played": 2,
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
