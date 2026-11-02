from django.urls import path

from . import views

app_name = "cricket_nepal"

urlpatterns = [
    path("", views.home, name="home"),
    path("matches/", views.matches, name="matches"),
    path("matches/<str:match_id>/", views.match_detail, name="match_detail"),
    path("players/", views.players, name="players"),
    path("players/<int:player_id>/", views.player_profile, name="player_profile"),
]
