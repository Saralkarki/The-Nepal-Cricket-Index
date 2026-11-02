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
    path("players/<int:player_id>/", views.player_profile, name="player_profile"),
]
