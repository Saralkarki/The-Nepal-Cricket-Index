import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from scripts.add_nepal_abandoned_match import (
    MATCH_COLUMNS,
    MATCH_RECORD,
    add_match_record,
)


class AddNepalAbandonedMatchTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "cricket.sqlite3"
        with sqlite3.connect(self.database_path) as connection:
            columns = ", ".join(
                f'"{column}" {"INTEGER" if column == "tournament_id" else "TEXT"}'
                for column in MATCH_COLUMNS
            )
            connection.execute(f'CREATE TABLE "nepal_matches" ({columns})')
            connection.execute(
                'CREATE TABLE "matches" ("match_id" TEXT PRIMARY KEY, "team" TEXT)'
            )
            connection.execute(
                'INSERT INTO "matches" VALUES (?, ?)', ("npl-match", "NPL team")
            )
            connection.execute(
                'CREATE TABLE "nepal_innings_summary" ("match_id" TEXT)'
            )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_insert_is_match_only_and_safe_to_repeat(self):
        self.assertTrue(add_match_record(self.database_path))
        self.assertFalse(add_match_record(self.database_path))

        with sqlite3.connect(self.database_path) as connection:
            columns = ", ".join(f'"{column}"' for column in MATCH_COLUMNS)
            rows = connection.execute(
                f'SELECT {columns} FROM "nepal_matches" WHERE "match_id" = ?',
                (MATCH_RECORD[0],),
            ).fetchall()
            self.assertEqual(rows, [MATCH_RECORD])
            self.assertEqual(
                connection.execute('SELECT COUNT(*) FROM "nepal_matches"').fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute('SELECT COUNT(*) FROM "nepal_innings_summary"').fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute('SELECT COUNT(*) FROM "matches"').fetchone()[0],
                1,
            )

    def test_conflicting_existing_match_id_is_not_overwritten(self):
        with sqlite3.connect(self.database_path) as connection:
            columns = ", ".join(f'"{column}"' for column in MATCH_COLUMNS)
            placeholders = ", ".join("?" for _ in MATCH_COLUMNS)
            conflicting_record = list(MATCH_RECORD)
            conflicting_record[1] = "2024-09-25"
            connection.execute(
                f'INSERT INTO "nepal_matches" ({columns}) VALUES ({placeholders})',
                conflicting_record,
            )

        with self.assertRaisesRegex(ValueError, "conflicting data"):
            add_match_record(self.database_path)

        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute(
                    'SELECT COUNT(*) FROM "nepal_matches" WHERE "match_id" = ?',
                    (MATCH_RECORD[0],),
                ).fetchone()[0],
                1,
            )
