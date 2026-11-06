import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from scripts.import_nepal_parquet_to_sqlite import (
    SOURCE_FILES,
    import_nepal_data,
)
from scripts.import_parquet_to_sqlite import (
    TABLE_ORDER as NPL_TABLES,
    read_source_data as read_npl_source_data,
    rebuild_database,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NEPAL_ROW_COUNTS = {
    "nepal_matches": 381,
    "nepal_innings_summary": 764,
    "nepal_batting_scorecards": 6379,
    "nepal_batting_stats_by_tournament": 3595,
    "nepal_batting_stats_overall": 1304,
    "nepal_bowling_scorecards": 4589,
    "nepal_bowling_stats_by_tournament": 2460,
    "nepal_bowling_stats_overall": 934,
    "nepal_players": 123,
    "nepal_tournament_players": 1284,
}


def snapshot_tables(connection, tables):
    snapshot = {}
    for table in tables:
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        columns = connection.execute(
            f'PRAGMA table_info("{table}")'
        ).fetchall()
        foreign_keys = connection.execute(
            f'PRAGMA foreign_key_list("{table}")'
        ).fetchall()
        indexes = connection.execute(
            f'PRAGMA index_list("{table}")'
        ).fetchall()
        index_details = tuple(
            (
                index,
                connection.execute(
                    f'PRAGMA index_info("{index[1]}")'
                ).fetchall(),
                connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                    (index[1],),
                ).fetchone(),
            )
            for index in indexes
        )
        rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
        snapshot[table] = (
            schema,
            columns,
            foreign_keys,
            index_details,
            tuple(sorted(rows, key=repr)),
        )
    return snapshot


class NepalParquetImportTests(TestCase):
    def test_import_is_repeatable_and_preserves_npl_tables(self):
        npl_data = read_npl_source_data(ROOT / "data" / "npl")
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "cricket.sqlite3"
            rebuild_database(database_path, npl_data)

            with sqlite3.connect(database_path) as connection:
                npl_before = snapshot_tables(connection, NPL_TABLES)

            first_counts = import_nepal_data(database_path, ROOT / "data" / "nepal")
            self.assertEqual(first_counts, EXPECTED_NEPAL_ROW_COUNTS)

            with sqlite3.connect(database_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertTrue(set(NPL_TABLES).issubset(tables))
                self.assertTrue(set(SOURCE_FILES).issubset(tables))
                self.assertEqual(snapshot_tables(connection, NPL_TABLES), npl_before)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM nepal_players"
                    ).fetchone()[0],
                    123,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM players"
                    ).fetchone()[0],
                    226,
                )

            second_counts = import_nepal_data(database_path, ROOT / "data" / "nepal")
            self.assertEqual(second_counts, EXPECTED_NEPAL_ROW_COUNTS)

            with sqlite3.connect(database_path) as connection:
                self.assertEqual(snapshot_tables(connection, NPL_TABLES), npl_before)
                for table, expected_count in EXPECTED_NEPAL_ROW_COUNTS.items():
                    self.assertEqual(
                        connection.execute(
                            f'SELECT COUNT(*) FROM "{table}"'
                        ).fetchone()[0],
                        expected_count,
                    )

                nepal_tables = tuple(SOURCE_FILES)
                nepal_before_failure = snapshot_tables(connection, nepal_tables[:-1])
                connection.execute('DROP TABLE "nepal_tournament_players"')
                connection.execute(
                    "CREATE VIEW nepal_tournament_players AS SELECT 1 AS marker"
                )
                connection.commit()

                with self.assertRaises(sqlite3.OperationalError):
                    import_nepal_data(database_path, ROOT / "data" / "nepal")

                self.assertEqual(
                    snapshot_tables(connection, nepal_tables[:-1]),
                    nepal_before_failure,
                )
                self.assertEqual(snapshot_tables(connection, NPL_TABLES), npl_before)
