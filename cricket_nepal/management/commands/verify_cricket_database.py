import json

from django.core.management.base import BaseCommand, CommandError

from cricket_nepal.data_access import (
    count_matches,
    get_match_with_innings,
    get_top_batting_stats,
    get_top_bowling_stats,
    get_tournaments,
    list_tables,
)


class Command(BaseCommand):
    help = "Verify read access to the imported cricket SQLite database."

    def add_arguments(self, parser):
        parser.add_argument("--tournament-id", type=int, default=1783)
        parser.add_argument("--match-id", default="1462596")

    def handle(self, *args, **options):
        tournament_id = options["tournament_id"]
        match_id = options["match_id"]
        tournaments = get_tournaments()
        if not any(row["tournament_id"] == tournament_id for row in tournaments):
            raise CommandError(f"Unknown tournament ID: {tournament_id}")

        match = get_match_with_innings(match_id)
        if match is None:
            raise CommandError(f"Unknown match ID: {match_id}")

        report = {
            "tables": list_tables(),
            "tournaments": tournaments,
            "match_count": count_matches(),
            "top_10_batting": get_top_batting_stats(tournament_id),
            "top_10_bowling": get_top_bowling_stats(tournament_id),
            "match_with_innings": match,
        }
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
