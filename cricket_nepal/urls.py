from django.urls import path

from . import views

app_name = "cricket_nepal"

urlpatterns = [
    path("", views.home, name="home"),
    path("tournaments/", views.tournaments, name="tournaments"),
    path(
        "tournaments/<slug:tournament_slug>/",
        views.tournament_overview,
        name="tournament_overview",
    ),
    path("matches/", views.matches, name="matches"),
    path("matches/<str:match_id>/", views.match_detail, name="match_detail"),
    path("teams/", views.teams, name="teams"),
    path("teams/<slug:team_slug>/", views.team_profile, name="team_profile"),
    path("players/", views.players, name="players"),
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
        "player-statistics/compare/",
        views.player_statistics,
        {"statistics_view": "compare"},
        name="player_statistics_compare",
    ),
    path("players/<int:player_id>/", views.player_profile, name="player_profile"),
]
