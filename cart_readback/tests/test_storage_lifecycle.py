"""Track SQLite initialization cleanup without relying on garbage collection."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from cartreadback_app import storage


class TrackedConnection(sqlite3.Connection):
    """Retain real SQLite transaction behavior and record context/close order."""

    def __enter__(self):
        self.lifecycle.append(("enter", self.in_transaction))
        return super().__enter__()

    def __exit__(self, kind, value, traceback):
        self.lifecycle.append(("exit-before", kind, self.in_transaction))
        result = super().__exit__(kind, value, traceback)
        self.lifecycle.append(("exit-after", self.in_transaction))
        return result

    def close(self):
        self.lifecycle.append(("close", self.in_transaction))
        super().close()


class StoreLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.sqlite3"
        self.connections = []
        self.real_connect = sqlite3.connect
        patcher = mock.patch.object(
            storage.sqlite3, "connect", side_effect=self.tracked_connect
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.close_connections)

    def tracked_connect(self, *args, **kwargs):
        connection = self.real_connect(
            *args, **kwargs, factory=TrackedConnection
        )
        connection.lifecycle = []
        self.connections.append(connection)
        return connection

    def close_connections(self):
        for connection in self.connections:
            sqlite3.Connection.close(connection)

    def assert_closed(self, connection, error=None, pending=False):
        self.assertEqual(
            connection.lifecycle,
            [
                ("enter", False),
                ("exit-before", error, pending),
                ("exit-after", False),
                ("close", False),
            ],
        )
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_initialization_commits_seed_and_closes_connection(self):
        storage.Store(self.path)
        self.assertEqual(len(self.connections), 1)
        self.assert_closed(self.connections[0])
        with closing(self.real_connect(self.path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT sku, document FROM catalog ORDER BY sku"
                ).fetchall(),
                sorted(
                    (product["sku_id"], storage.canonical(product))
                    for product in storage.fixtures()
                ),
            )

    def test_reinitialization_preserves_existing_catalog_and_closes(self):
        storage.Store(self.path)
        with closing(self.real_connect(self.path)) as connection:
            connection.execute("UPDATE catalog SET document = 'preserved'")
            connection.commit()
        storage.Store(self.path)
        self.assertEqual(len(self.connections), 2)
        for connection in self.connections:
            self.assert_closed(connection)
        with closing(self.real_connect(self.path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT DISTINCT document FROM catalog"
                ).fetchall(),
                [("preserved",)],
            )

    def test_schema_failure_preserves_transaction_semantics_and_closes(self):
        for pending in (True, False):
            with self.subTest(pending_transaction=pending):
                schema = (
                    "BEGIN IMMEDIATE;" if pending else ""
                ) + "CREATE TABLE partial_schema (value TEXT); INVALID SQL;"
                with mock.patch.object(storage, "SCHEMA", schema):
                    with self.assertRaises(sqlite3.OperationalError):
                        storage.Store(self.path)
                self.assert_closed(
                    self.connections[-1], sqlite3.OperationalError, pending
                )
                with closing(self.real_connect(self.path)) as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT name FROM sqlite_master WHERE name = ?",
                            ("partial_schema",),
                        ).fetchall(),
                        [] if pending else [("partial_schema",)],
                    )

    def test_seed_failure_rolls_back_partial_insert_before_close(self):
        for error_type in (RuntimeError, KeyboardInterrupt):
            with self.subTest(error_type=error_type):
                error = error_type("Synthetic second-product failure")
                with mock.patch.object(
                    storage, "validate_product", side_effect=[None, error]
                ) as validate:
                    with self.assertRaises(error_type) as observed:
                        storage.Store(self.path)
                self.assertIs(observed.exception, error)
                self.assertEqual(validate.call_count, 2)
                self.assert_closed(
                    self.connections[-1], error_type, pending=True
                )
                with closing(self.real_connect(self.path)) as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM catalog"
                        ).fetchone()[0],
                        0,
                    )


if __name__ == "__main__":
    unittest.main()
