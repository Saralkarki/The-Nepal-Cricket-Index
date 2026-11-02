from django.http import Http404
from django.shortcuts import render
from django.utils.text import slugify

from cricket_nepal.data_access import (
    get_team_directory,
    get_team_profile,
    get_player_directory,
    get_player_match_performance,
    get_player_profile,
    get_player_radar_comparison,
    get_matches,
    get_match_scorecard,
    get_teams,
    get_npl_tournament_overview,
    get_tournaments,
)


BATTER_RADAR_AXES = (
    ("Total runs", "total_runs", True, ""),
    ("Strike Rate", "strike_rate", True, ""),
    ("Dot-ball %", "dot_ball_percentage", False, "%"),
    ("Fours", "total_fours", True, ""),
    ("Sixes", "total_sixes", True, ""),
)

BOWLER_RADAR_AXES = (
    ("Wickets", "wickets", True, ""),
    ("Bowling Strike Rate", "strike_rate", False, ""),
    ("Economy", "economy", False, ""),
    ("Maidens", "maidens", True, ""),
    ("Dot-ball %", "dot_ball_percentage", False, "%"),
)


def _build_radar_chart(
    cohort: list[dict], player_id: int, axis_definitions: tuple, season_label: str
) -> dict:
    player_data = next(
        (row for row in cohort if row["player_id"] == player_id),
        None,
    )
    axes = []
    for label, key, higher_is_better, unit in axis_definitions:
        cohort_values = [
            row[key] for row in cohort if row[key] is not None
        ]
        value = player_data[key] if player_data is not None else None
        normalized = None
        if value is not None and cohort_values:
            low, high = min(cohort_values), max(cohort_values)
            if high == low:
                normalized = 100
            else:
                normalized = (value - low) * 100 / (high - low)
                if not higher_is_better:
                    normalized = 100 - normalized
        actual = (
            f"{value:g}{unit}" if value is not None else "Not available"
        )
        axes.append(
            {
                "label": label,
                "value": value,
                "normalized": normalized,
                "actual": actual,
                "tooltip": f"{label}: {actual}",
            }
        )

    return {
        "available": player_data is not None
        and any(axis["value"] is not None for axis in axes),
        "season_label": season_label,
        "axes": axes,
    }


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
    return render(
        request,
        "cricket_nepal/home.html",
        {"tournaments": _tournament_directory()},
    )


def _tournament_directory():
    tournaments_by_name = {}
    for tournament in get_tournaments():
        entry = tournaments_by_name.setdefault(
            tournament["tournament_name"],
            {
                "tournament_name": tournament["tournament_name"],
                "tournament_slug": slugify(tournament["tournament_name"]),
                "seasons": [],
            },
        )
        entry["seasons"].append(tournament["season"])
    return list(tournaments_by_name.values())


def tournaments(request):
    return render(
        request,
        "cricket_nepal/tournaments.html",
        {"tournaments": _tournament_directory()},
    )


def tournament_overview(request, tournament_slug: str):
    npl_slug = slugify("Nepal Premier League")
    if tournament_slug != npl_slug:
        raise Http404("Tournament not found")

    npl_seasons = [
        tournament
        for tournament in get_tournaments()
        if tournament["tournament_name"] == "Nepal Premier League"
    ]
    season_id = request.GET.get("season_id")
    selected_season = next(
        (
            season
            for season in npl_seasons
            if str(season["tournament_id"]) == season_id
        ),
        None,
    )
    overview = get_npl_tournament_overview(
        selected_season["tournament_id"] if selected_season else None
    )
    return render(
        request,
        "cricket_nepal/tournament_overview.html",
        {
            "overview": overview,
            "selected_season": selected_season,
            "tournament_slug": npl_slug,
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


def teams(request):
    return render(
        request,
        "cricket_nepal/teams.html",
        {"teams": get_team_directory()},
    )


def team_profile(request, team_slug: str):
    team = next(
        (
            team
            for team in get_team_directory()
            if team["team_slug"] == team_slug
        ),
        None,
    )
    if team is None:
        raise Http404("Team not found")

    season_id = request.GET.get("season_id")
    selected_season = next(
        (
            season
            for season in team["participations"]
            if str(season["tournament_id"]) == season_id
        ),
        None,
    )
    selected_tournament_id = (
        selected_season["tournament_id"] if selected_season else None
    )
    profile = get_team_profile(team["team_name"], selected_tournament_id)
    if profile is None:
        raise Http404("Team not found")

    return render(
        request,
        "cricket_nepal/team_profile.html",
        {
            "team": profile,
            "selected_season": selected_season,
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
    radar_comparison = get_player_radar_comparison(selected_tournament_id)
    season_label = selected_season["season"] if selected_season else "All seasons"
    radar_charts = {
        "batting": _build_radar_chart(
            radar_comparison["batting"],
            player_id,
            BATTER_RADAR_AXES,
            season_label,
        ),
        "bowling": _build_radar_chart(
            radar_comparison["bowling"],
            player_id,
            BOWLER_RADAR_AXES,
            season_label,
        ),
    }
    return render(
        request,
        "cricket_nepal/player_profile.html",
        {
            "profile": profile,
            "performance": performance,
            "selected_season": selected_season,
            "radar_charts": radar_charts,
        },
    )


def match_detail(request, match_id: str):
    match = get_match_scorecard(match_id)
    if match is None:
        raise Http404("Match not found")
    return render(request, "cricket_nepal/match_detail.html", {"match": match})
