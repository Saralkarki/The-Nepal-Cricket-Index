import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from django.test import Client
from django.urls import reverse

from scripts.add_npl_abandoned_match import (
    MATCH_COLUMNS,
    MATCH_RECORD,
    add_match_record,
)


class AddNplAbandonedMatchTests(TestCase):
    def test_insert_is_safe_to_repeat_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "cricket.sqlite3"
            with sqlite3.connect(database_path) as connection:
                columns = ", ".join(f'"{column}" {"INTEGER" if column in ("stage_order", "tournament_id") else "TEXT"}'
                    for column in MATCH_COLUMNS)
                connection.execute(f'CREATE TABLE "matches" ({columns})')

            self.assertTrue(add_match_record(database_path))
            self.assertFalse(add_match_record(database_path))

            with sqlite3.connect(database_path) as connection:
                self.assertEqual(
                    connection.execute('SELECT COUNT(*) FROM "matches"').fetchone()[0],
                    1,
                )
                connection.execute('UPDATE "matches" SET "venue_name" = \'Other\'')
            with self.assertRaises(ValueError):
                add_match_record(database_path)


class NplAbandonedMatchPageTests(TestCase):
    def test_match_page_and_list_say_abandoned(self):
        response = Client().get(
            reverse("cricket_nepal:match_detail", args=[MATCH_RECORD[0]])
        )
        self.assertIn("Match abandoned without a ball bowled", response.content.decode())

        listing = Client().get(
            reverse("cricket_nepal:npl_matches"),
            {"tournament_id": MATCH_RECORD[-1]},
        )
        self.assertIn("Abandoned without a ball bowled", listing.content.decode())
