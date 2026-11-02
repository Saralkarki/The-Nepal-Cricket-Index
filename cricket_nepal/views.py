from django.shortcuts import render

# Create your views here.
from django.shortcuts import render


SEASONS = (
    {"year": "2024", "name": "NPL Season 1", "label": "Season 1 · 2024"},
    {"year": "2025", "name": "NPL Season 2", "label": "Season 2 · 2025"},
)


def home(request):
    selected_year = request.GET.get("season", "2025")
    if selected_year not in {season["year"] for season in SEASONS}:
        selected_year = "2025"

    selected_season = next(
        season for season in SEASONS if season["year"] == selected_year
    )
    return render(
        request,
        "cricket_nepal/home.html",
        {
            "seasons": SEASONS,
            "selected_year": selected_year,
            "selected_season": selected_season,
        },
    )
