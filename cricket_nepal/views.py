from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.text import slugify

from cricket_nepal.data_access import (
    get_team_directory,
    get_npl_team_directory,
    get_team_profile,
    get_player_directory,
    get_player_names,
    get_player_statistics,
    get_player_match_performance,
    get_player_profile,
    get_player_radar_comparison,
    search_players,
    get_matches,
    get_match_scorecard,
    get_teams,
    get_npl_tournament_overview,
    get_tournaments,
)
from cricket_nepal.nepal_data_access import (
    LEAGUE_2_CYCLES,
    get_nepal_match_scorecard,
    get_nepal_player_directory,
    get_nepal_player_profile,
    get_nepal_tournament_overview,
    get_nepal_tournaments,
)
from cricket_nepal.tournament_data_access import get_tournament_match_formats


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

FIELDING_SORT_OPTIONS = (
    ("dismissals", "Most dismissals"),
    ("catches", "Most catches"),
    ("stumpings", "Most stumpings"),
    ("run_outs", "Most run-outs"),
    ("dismissals_per_match", "Highest dismissals per match"),
)

COMPARISON_BATTING_RADAR_AXES = (
    ("Runs", "runs", True, ""),
    ("Batting Average", "average", True, ""),
    ("Strike Rate", "strike_rate", True, ""),
    ("Fours", "fours", True, ""),
    ("Sixes", "sixes", True, ""),
    ("Dot-ball %", "dot_ball_percentage", False, "%"),
)

COMPARISON_BOWLING_RADAR_AXES = (
    ("Wickets", "wickets", True, ""),
    ("Bowling Average", "average", False, ""),
    ("Economy", "economy", False, ""),
    ("Bowling Strike Rate", "strike_rate", False, ""),
    ("Maidens", "maidens", True, ""),
    ("Dot-ball %", "dot_ball_percentage", True, "%"),
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
    return render(request, "cricket_nepal/home.html")


def about(request):
    return render(request, "cricket_nepal/about.html")


def _tournament_directory(include_nepal=False, include_npl=True):
    tournaments_by_name = {}
    tournament_sources = []
    if include_npl:
        tournament_sources.append((get_tournaments(), "NPL", "male", True))
    if include_nepal:
        tournament_sources.append(
            (get_nepal_tournaments(), "Nepal national team", None, False)
        )

    formats_by_tournament = {}
    if include_nepal:
        for match_format in get_tournament_match_formats():
            key = (
                match_format["source"],
                match_format["tournament_name"],
                match_format["season"],
                (
                    "male"
                    if match_format["source"] == "NPL"
                    else (match_format["gender"] or "").casefold()
                ),
            )
            formats_by_tournament.setdefault(key, set()).add(
                match_format["match_format"]
            )

    for (
        source_tournaments,
        source_name,
        default_gender,
        has_overview,
    ) in tournament_sources:
        for tournament in source_tournaments:
            tournament_name = tournament["tournament_name"]
            entry = tournaments_by_name.setdefault(
                tournament_name,
                {
                    "tournament_name": tournament_name,
                    "tournament_slug": slugify(tournament_name),
                    "seasons": [],
                    "sources": [],
                    "has_overview": False,
                    "records": [],
                },
            )
            season = tournament.get("season")
            if season and season not in entry["seasons"]:
                entry["seasons"].append(season)
            entry["records"].append(
                {
                    "gender": (
                        tournament.get("gender") or default_gender or ""
                    ).casefold(),
                    "season": season,
                    "tournament_id": tournament.get("tournament_id"),
                    "source": source_name,
                    "has_overview": has_overview,
                    "match_formats": formats_by_tournament.get(
                        (
                            source_name,
                            tournament_name,
                            season,
                            (
                                "male"
                                if source_name == "NPL"
                                else (
                                    tournament.get("gender") or ""
                                ).casefold()
                            ),
                        ),
                        set(),
                    ),
                }
            )
    return list(tournaments_by_name.values())


def tournaments(request):
    all_tournaments = _tournament_directory(include_nepal=True, include_npl=False)
    all_formats = {
        match_format.strip().upper()
        for tournament in all_tournaments
        for record in tournament["records"]
        for match_format in record["match_formats"]
        if match_format and match_format.strip()
    }
    known_match_types = ("ODI", "T20", "T20I")
    available_match_types = [
        match_type for match_type in known_match_types if match_type in all_formats
    ]
    if any(match_format not in known_match_types for match_format in all_formats):
        available_match_types.append("Others")

    season_options = sorted(
        {
            record["season"]
            for tournament in all_tournaments
            for record in tournament["records"]
            if record["season"]
        },
        reverse=True,
    )
    selected_gender = request.GET.get("gender", "all")
    if selected_gender not in {"all", "men", "women"}:
        selected_gender = "all"
    selected_season = request.GET.get("season", "all")
    if selected_season not in season_options and selected_season != "all":
        selected_season = "all"
    selected_match_type = request.GET.get("match_type", "all")
    match_type_values = {
        "odi": "ODI",
        "t20": "T20",
        "t20i": "T20I",
        "others": "Others",
    }
    if (
        selected_match_type != "all"
        and match_type_values.get(selected_match_type) not in available_match_types
    ):
        selected_match_type = "all"

    gender_values = {"men": "male", "women": "female"}
    tournament_list = []
    for tournament in all_tournaments:
        matching_records = [
            record
            for record in tournament["records"]
            if record["match_formats"]
            and (
                selected_gender == "all"
                or record["gender"] == gender_values[selected_gender]
            )
            and (
                selected_season == "all"
                or record["season"] == selected_season
            )
            and (
                selected_match_type == "all"
                or (
                    any(
                        match_format.strip().upper() not in known_match_types
                        for match_format in record["match_formats"]
                        if match_format
                    )
                    if selected_match_type == "others"
                    else match_type_values[selected_match_type]
                    in {
                        match_format.strip().upper()
                        for match_format in record["match_formats"]
                        if match_format
                    }
                )
            )
        ]
        if not matching_records:
            continue
        nepal_instances = []
        seen_nepal_ids = set()
        for record in matching_records:
            tournament_id = record["tournament_id"]
            if (
                record["source"] == "Nepal national team"
                and tournament_id is not None
                and tournament_id not in seen_nepal_ids
            ):
                seen_nepal_ids.add(tournament_id)
                nepal_instances.append(
                    {"tournament_id": tournament_id, "season": record["season"]}
                )
        tournament_list.append(
            {
                **tournament,
                "seasons": list(
                    dict.fromkeys(
                        record["season"]
                        for record in matching_records
                        if record["season"]
                    )
                ),
                "sources": list(
                    dict.fromkeys(record["source"] for record in matching_records)
                ),
                "has_overview": any(
                    record["has_overview"] for record in matching_records
                ),
                "match_formats": sorted(
                    {
                        match_format
                        for record in matching_records
                        for match_format in record["match_formats"]
                    }
                ),
                "nepal_instances": nepal_instances,
            }
        )

    return render(
        request,
        "cricket_nepal/tournaments.html",
        {
            "tournaments": tournament_list,
            "season_options": season_options,
            "selected_gender": selected_gender,
            "selected_season": selected_season,
            "match_type_options": available_match_types,
            "selected_match_type": selected_match_type,
        },
    )


def nepal_tournament_overview(request, tournament_id: int):
    cycle_for_tournament = next(
        (
            cycle
            for cycle, ids in LEAGUE_2_CYCLES.items()
            if tournament_id in ids
        ),
        None,
    )
    selected_cycle = cycle_for_tournament
    cycle_tournament_ids = (
        LEAGUE_2_CYCLES[cycle_for_tournament]
        if cycle_for_tournament
        else (tournament_id,)
    )

    requested_cycle = request.GET.get("cycle")
    if cycle_for_tournament and requested_cycle in LEAGUE_2_CYCLES:
        selected_cycle = requested_cycle
        cycle_tournament_ids = LEAGUE_2_CYCLES[requested_cycle]

    overview = get_nepal_tournament_overview(cycle_tournament_ids)
    if overview is None:
        raise Http404("Tournament not found")

    cycle_options = [
        {"value": cycle, "label": cycle.replace("-", "–")}
        for cycle in LEAGUE_2_CYCLES
    ]
    selected_cycle_label = (
        selected_cycle.replace("-", "–") if selected_cycle else None
    )
    return render(
        request,
        "cricket_nepal/nepal_tournament_overview.html",
        {
            "overview": overview,
            "tournament_id": tournament_id,
            "is_league_2": cycle_for_tournament is not None,
            "cycle_options": cycle_options,
            "selected_cycle": selected_cycle,
            "selected_cycle_label": selected_cycle_label,
        },
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


def npl_home(request):
    return tournament_overview(request, slugify("Nepal Premier League"))


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


def national_team_players(request):
    search_term = request.GET.get("q", "").strip()[:100]
    selected_gender = request.GET.get("gender", "all")
    if selected_gender not in {"all", "male", "female"}:
        selected_gender = "all"
    players = get_nepal_player_directory(
        search_term,
        gender=None if selected_gender == "all" else selected_gender,
    )
    return render(
        request,
        "cricket_nepal/national_team_players.html",
        {
            "players": players,
            "search_term": search_term,
            "selected_gender": selected_gender,
            "player_count": len(players),
        },
    )


def national_team_player_profile(request, nepal_player_id: int):
    profile = get_nepal_player_profile(nepal_player_id)
    if profile is None:
        raise Http404("National-team player not found")
    return render(
        request,
        "cricket_nepal/nepal_player_profile.html",
        {"profile": profile},
    )


def player_statistics(request, statistics_view="batting"):
    try:
        minimum_matches = int(request.GET.get("minimum_matches", "1"))
    except ValueError:
        minimum_matches = 1

    statistics = get_player_statistics(
        tournament_name=request.GET.get("tournament", "").strip()[:100],
        season=request.GET.get("season", "").strip()[:30],
        team_name=request.GET.get("team", "").strip()[:100],
        search_term=request.GET.get("q", "").strip()[:100],
        minimum_matches=min(max(minimum_matches, 0), 20),
        batting_sort=request.GET.get("batting_sort", "runs"),
        bowling_sort=request.GET.get("bowling_sort", "wickets"),
    )
    return render(
        request,
        "cricket_nepal/player_statistics.html",
        {
            "statistics": statistics,
            "statistics_view": statistics_view,
            "statistics_page_url": {
                "batting": "cricket_nepal:player_statistics_batting",
                "bowling": "cricket_nepal:player_statistics_bowling",
                "compare": "cricket_nepal:player_statistics_compare",
            }[statistics_view],
        },
    )


def player_fielding_statistics(request):
    try:
        minimum_matches = int(request.GET.get("minimum_matches", "1"))
    except ValueError:
        minimum_matches = 1
    minimum_matches = min(max(minimum_matches, 0), 20)

    fielding_sort = request.GET.get("fielding_sort", "dismissals")
    valid_sort_values = {value for value, _ in FIELDING_SORT_OPTIONS}
    if fielding_sort not in valid_sort_values:
        fielding_sort = "dismissals"

    statistics = get_player_statistics(
        tournament_name=request.GET.get("tournament", "").strip()[:100],
        season=request.GET.get("season", "").strip()[:30],
        team_name=request.GET.get("team", "").strip()[:100],
        search_term=request.GET.get("q", "").strip()[:100],
        minimum_matches=minimum_matches,
        player_ids=(),
        include_best_performances=False,
    )
    return render(
        request,
        "cricket_nepal/fielding_statistics.html",
        {
            "statistics": statistics,
            "statistics_view": "fielding",
            "fielding_sort": fielding_sort,
            "fielding_sort_options": [
                {"value": value, "label": label}
                for value, label in FIELDING_SORT_OPTIONS
            ],
        },
    )


def player_statistics_compare(request):
    return redirect("cricket_nepal:player_comparison")


def player_comparison(request):
    statistics = get_player_statistics(
        minimum_matches=0,
        player_ids=(),
        include_best_performances=False,
    )
    return render(
        request,
        "cricket_nepal/player_comparison.html",
        {
            "statistics": statistics,
            "comparison_data_url": reverse("cricket_nepal:player_comparison_data"),
            "player_search_url": reverse("cricket_nepal:player_comparison_search"),
        },
    )


def player_comparison_search(request):
    players = search_players(request.GET.get("q", "")[:100])
    return JsonResponse(
        {
            "players": [
                {
                    **player,
                    "profile_url": reverse(
                        "cricket_nepal:player_profile",
                        args=[player["player_id"]],
                    ),
                }
                for player in players
            ]
        }
    )


def player_comparison_data(request):
    raw_player_ids = request.GET.getlist("player")
    try:
        player_ids = tuple(dict.fromkeys(int(value) for value in raw_player_ids))
    except ValueError:
        return JsonResponse({"error": "Player IDs must be integers."}, status=400)
    if any(player_id <= 0 for player_id in player_ids):
        return JsonResponse({"error": "Player IDs must be positive."}, status=400)

    player_names = get_player_names(player_ids)
    if len(player_names) != len(player_ids):
        return JsonResponse({"error": "One or more players were not found."}, status=404)

    statistics = get_player_statistics(
        tournament_name=request.GET.get("tournament", "").strip()[:100],
        season=request.GET.get("season", "").strip()[:30],
        team_name=request.GET.get("team", "").strip()[:100],
        minimum_matches=0,
        player_ids=None if player_ids else (),
        include_best_performances=False,
    )
    batting_rows = {row["player_id"]: row for row in statistics["batting"]}
    bowling_rows = {row["player_id"]: row for row in statistics["bowling"]}
    players = []
    for player_id in player_ids:
        batting = batting_rows.get(player_id)
        bowling = bowling_rows.get(player_id)
        batting_radar = _build_radar_chart(
            statistics["batting"],
            player_id,
            COMPARISON_BATTING_RADAR_AXES,
            "Selected comparison",
        )
        bowling_radar = _build_radar_chart(
            statistics["bowling"],
            player_id,
            COMPARISON_BOWLING_RADAR_AXES,
            "Selected comparison",
        )
        players.append(
            {
                "player_id": player_id,
                "player_name": player_names[player_id],
                "profile_url": reverse(
                    "cricket_nepal:player_profile",
                    args=[player_id],
                ),
                "batting": batting,
                "bowling": bowling,
                "radar": {
                    "batting": batting_radar,
                    "bowling": bowling_radar,
                },
            }
        )

    return JsonResponse(
        {
            "players": players,
            "filters": {
                "tournament_options": statistics["tournament_options"],
                "season_options": statistics["season_options"],
                "team_options": statistics["team_options"],
                "selected_tournament": statistics["selected_tournament"],
                "selected_season": statistics["selected_season"],
                "selected_team": statistics["selected_team"],
            },
        }
    )


def teams(request):
    seasons = [
        season
        for season in get_tournaments()
        if season["tournament_name"] == "Nepal Premier League"
    ]
    selected_season = next(
        (
            season
            for season in seasons
            if str(season["tournament_id"]) == request.GET.get("season_id")
        ),
        None,
    )
    directory = get_npl_team_directory(
        selected_season["tournament_id"] if selected_season else None
    )
    return render(
        request,
        "cricket_nepal/teams.html",
        {
            "teams": directory["teams"],
            "seasons": directory["seasons"],
            "selected_season": directory["selected_season"],
        },
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


def nepal_match_detail(request, match_id: str):
    match = get_nepal_match_scorecard(match_id)
    if match is None:
        raise Http404("Match not found")
    return render(request, "cricket_nepal/nepal_match_detail.html", {"match": match})
