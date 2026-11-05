"""Verify analysis test helpers close their own SQLite connections."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import test_analysis_budget as budget_tests
import test_analysis_dispatch as dispatch_tests
from cartreadback_app.storage import Store


class TrackedConnection(sqlite3.Connection):
    """Record transaction exit before explicit closure on a real connection."""

    def __enter__(self):
        self.events.append("enter")
        return super().__enter__()

    def __exit__(self, kind, value, traceback):
        result = super().__exit__(kind, value, traceback)
        self.events.append(("exit", kind, self.in_transaction))
        return result

    def execute(self, sql, *args, **kwargs):
        if self.failure is not None and sql.startswith("SELECT"):
            raise self.failure
        return super().execute(sql, *args, **kwargs)

    def close(self):
        self.events.append(("close", self.in_transaction))
        super().close()


class AnalysisConnectionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name) / "helpers.sqlite3")

    def check_helpers(self, fail):
        helpers = {
            "authored_transport": dispatch_tests.AuthoredTransport,
            "operations": lambda store: (
                dispatch_tests.AnalysisDispatchTests.operations(
                    SimpleNamespace(store=store)
                )
            ),
            "budget_rows": lambda store: (
                budget_tests.IntegratedBudgetTests.rows(
                    SimpleNamespace(store=store), "budget_operations"
                )
            ),
        }
        for name, helper in helpers.items():
            with self.subTest(helper=name, failure=fail):
                connection = sqlite3.connect(
                    self.store.path, factory=TrackedConnection
                )
                connection.events = []
                connection.failure = None
                connection.row_factory = sqlite3.Row
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS lifecycle_probe (value TEXT)"
                )
                connection.execute(
                    "INSERT INTO lifecycle_probe VALUES (?)", (name,)
                )
                error = sqlite3.OperationalError("injected query failure")
                connection.failure = error if fail else None
                try:
                    with mock.patch.object(
                        self.store, "connect", return_value=connection
                    ):
                        if fail:
                            with self.assertRaises(
                                sqlite3.OperationalError
                            ) as caught:
                                helper(self.store)
                            self.assertIs(caught.exception, error)
                        else:
                            helper(self.store)
                    self.assertEqual(
                        connection.events,
                        [
                            "enter",
                            (
                                "exit",
                                sqlite3.OperationalError if fail else None,
                                False,
                            ),
                            ("close", False),
                        ],
                    )
                    connection.failure = None
                    with self.assertRaises(sqlite3.ProgrammingError):
                        connection.execute("SELECT 1")
                finally:
                    # Also release baseline failures without relying on GC.
                    sqlite3.Connection.close(connection)
                with self.store.transaction() as check:
                    self.assertEqual(
                        check.execute(
                            "SELECT count(*) FROM lifecycle_probe WHERE value = ?",
                            (name,),
                        ).fetchone()[0],
                        0 if fail else 1,
                    )

    def test_helpers_commit_then_close_on_success(self):
        self.check_helpers(False)

    def test_helpers_rollback_then_close_on_query_failure(self):
        self.check_helpers(True)
