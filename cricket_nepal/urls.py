from django.urls import path

from . import views

app_name = "cricket_nepal"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("tournaments/", views.tournaments, name="tournaments"),
    path(
        "tournaments/<slug:tournament_slug>/",
        views.tournament_overview,
        name="tournament_overview",
    ),
    path(
        "nepal-tournaments/<int:tournament_id>/",
        views.nepal_tournament_overview,
        name="nepal_tournament_overview",
    ),
    path("npl-matches/", views.matches, name="npl_matches"),
    path("matches/<str:match_id>/", views.match_detail, name="match_detail"),
    path(
        "nepal-matches/<str:match_id>/",
        views.nepal_match_detail,
        name="nepal_match_detail",
    ),
    path("teams/", views.teams, name="teams"),
    path("teams/<slug:team_slug>/", views.team_profile, name="team_profile"),
    path("npl-players/", views.players, name="players"),
    path(
        "nepal-national-team/",
        views.national_team_players,
        name="national_team_players",
    ),
    path(
        "nepal-national-team/players/<int:nepal_player_id>/",
        views.national_team_player_profile,
        name="national_team_player_profile",
    ),
    path("player-statistics/", views.player_statistics, name="player_statistics"),
    path(
        "player-statistics/batting/",
        views.player_statistics,
        {"statistics_view": "batting"},
        name="player_statistics_batting",
    ),
    path(
        "player-statistics/bowling/",
        views.player_statistics,
        {"statistics_view": "bowling"},
        name="player_statistics_bowling",
    ),
    path(
        "player-statistics/fielding/",
        views.player_fielding_statistics,
        name="player_statistics_fielding",
    ),
    path(
        "player-statistics/compare/",
        views.player_statistics_compare,
        name="player_statistics_compare",
    ),
    path("player-comparison/", views.player_comparison, name="player_comparison"),
    path(
        "player-comparison/data/",
        views.player_comparison_data,
        name="player_comparison_data",
    ),
    path(
        "player-comparison/search/",
        views.player_comparison_search,
        name="player_comparison_search",
    ),
    path("players/<int:player_id>/", views.player_profile, name="player_profile"),
]
