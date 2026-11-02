from django.http import Http404
from django.shortcuts import render

from cricket_nepal.data_access import (
    get_player_directory,
    get_player_match_performance,
    get_player_profile,
    get_matches,
    get_match_scorecard,
    get_teams,
    get_tournament_overview,
    get_tournaments,
)


def _get_tournament_selection(request):
    tournaments = get_tournaments()
    if not tournaments:
        raise RuntimeError("No tournaments are available in the cricket database")

    tournament_by_id = {
        str(tournament["tournament_id"]): tournament for tournament in tournaments
    }
    selected_tournament = tournament_by_id.get(request.GET.get("tournament_id"))
    if selected_tournament is None:
        selected_tournament = tournaments[0]
    return tournaments, selected_tournament


def home(request):
    tournaments, selected_tournament = _get_tournament_selection(request)
    overview = get_tournament_overview(selected_tournament["tournament_id"])

    return render(
        request,
        "cricket_nepal/home.html",
        {
            "tournaments": tournaments,
            "selected_tournament": selected_tournament,
            "overview": overview,
        },
    )


def matches(request):
    tournaments, selected_tournament = _get_tournament_selection(request)
    teams = get_teams(selected_tournament["tournament_id"])
    selected_team = request.GET.get("team", "")
    if selected_team not in teams:
        selected_team = ""
    match_list = get_matches(selected_tournament["tournament_id"], selected_team or None)

    return render(
        request,
        "cricket_nepal/matches.html",
        {
            "tournaments": tournaments,
            "selected_tournament": selected_tournament,
            "teams": teams,
            "selected_team": selected_team,
            "matches": match_list,
        },
    )


def players(request):
    search_term = request.GET.get("q", "").strip()[:100]
    return render(
        request,
        "cricket_nepal/players.html",
        {
            "players": get_player_directory(search_term),
            "search_term": search_term,
        },
    )


def player_profile(request, player_id: int):
    profile = get_player_profile(player_id)
    if profile is None:
        raise Http404("Player not found")

    season_id = request.GET.get("season_id")
    selected_season = next(
        (
            season
            for season in profile["participations"]
            if str(season["tournament_id"]) == season_id
        ),
        None,
    )
    selected_tournament_id = (
        selected_season["tournament_id"] if selected_season else None
    )
    profile["display_season_stats"] = [
        season
        for season in profile["season_stats"]
        if selected_tournament_id is None
        or season["tournament_id"] == selected_tournament_id
    ]
    performance = get_player_match_performance(
        player_id, tournament_id=selected_tournament_id
    )
    return render(
        request,
        "cricket_nepal/player_profile.html",
        {
            "profile": profile,
            "performance": performance,
            "selected_season": selected_season,
        },
    )


def match_detail(request, match_id: str):
    match = get_match_scorecard(match_id)
    if match is None:
        raise Http404("Match not found")
    return render(request, "cricket_nepal/match_detail.html", {"match": match})
