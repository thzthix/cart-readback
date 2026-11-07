"""Synthetic interruption regressions for the shared host-capacity worker."""

import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical
from test_context_service import fabricate as context_fabricate
from test_domain import Workflow
from test_gemini_service import NOW
from test_gemini_service import fabricate as gemini_fabricate
from test_responses_http import FakeConnection, FakeResponse


class CapacityWorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        for name in ("socket.create_connection", "http.client.HTTPSConnection"):
            guard = patch(name, side_effect=AssertionError("no real network"))
            guard.start()
            self.addCleanup(guard.stop)

    @contextmanager
    def case(self, strategy, timeout=2.0):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "app.sqlite3")
            sid = store.session(None)[0]["sid"]
            fabricate = (
                gemini_fabricate if strategy == "gemini" else context_fabricate
            )
            runtime, state, _ = fabricate(store, (sid,), timeout=timeout)
            service = Service(
                store,
                **{f"{strategy}_analysis": runtime},
                clock=lambda: datetime.fromtimestamp(NOW, timezone.utc),
            )
            try:
                yield store, service, state, Workflow(service, sid)
            finally:
                service.close()

    def assert_unknown(self, store, strategy, service, state, flow, errors):
        with store.connect() as connection:
            row = connection.execute(
                f"SELECT a.status, c.status FROM analysis_operations a "
                f"JOIN {strategy}_capacity_operations c USING(operation_id)"
            ).fetchone()
            self.assertEqual(tuple(row), ("UNKNOWN", "UNKNOWN"))
        checkout = service.bootstrap(flow.sid)["checkout"]
        self.assertEqual(checkout["state"], "ANALYSIS_BLOCKED")
        self.assertIn(
            checkout["analysis_error"],
            ("MODEL_OUTCOME_UNKNOWN", "MODEL_TIMEOUT"),
        )
        self.assertIsNone(checkout["snapshot_hash"])
        self.assertIsNone(checkout["confirmation_id"])
        self.assertNotIn("SYNTHETIC_PRIVATE_INTERRUPTION", canonical(checkout))
        self.assertEqual(errors, [])
        self.assertEqual(service._active, 0)
        self.assertEqual(state["calls"], 1)
        with self.assertRaises(AppError):
            Workflow(service, flow.sid).analyze()
        self.assertEqual(state["calls"], 1)

    def test_cleanup_baseexceptions_are_fenced_without_thread_exception_leaks(
        self,
    ):
        for strategy in ("gemini", "context"):
            for exception in (KeyboardInterrupt, SystemExit, BaseException):
                with (
                    self.subTest(strategy=strategy, exception=exception),
                    self.case(strategy) as case,
                ):
                    store, service, state, flow = case
                    errors, closed = [], []
                    original_close = FakeConnection.close

                    def interrupted(_response):
                        raise exception("SYNTHETIC_PRIVATE_INTERRUPTION")

                    def connection_close(connection):
                        original_close(connection)
                        closed.append(connection)

                    with (
                        patch.object(FakeResponse, "close", interrupted),
                        patch.object(FakeConnection, "close", connection_close),
                        patch(
                            "threading.excepthook",
                            lambda args: errors.append(args),
                        ),
                    ):
                        result = flow.analyze()
                    self.assertEqual(len(closed), 1)
                    self.assertEqual(closed[0].closed, 1)
                    self.assertNotIn(
                        "SYNTHETIC_PRIVATE_INTERRUPTION", canonical(result)
                    )
                    self.assert_unknown(
                        store, strategy, service, state, flow, errors
                    )

    def test_preobservation_baseexception_fences_original(self):
        for strategy in ("gemini", "context"):
            with self.subTest(strategy=strategy), self.case(strategy) as case:
                store, service, state, flow = case
                errors = []

                def interrupted(name, _operation):
                    if name == "analysis_before_observation_commit":
                        raise KeyboardInterrupt(
                            "SYNTHETIC_PRIVATE_INTERRUPTION"
                        )

                service._checkpoint = interrupted
                with patch(
                    "threading.excepthook", lambda args: errors.append(args)
                ):
                    flow.analyze()
                self.assert_unknown(
                    store, strategy, service, state, flow, errors
                )

    def test_observation_baseexception_rolls_back_before_unknown(self):
        for strategy in ("gemini", "context"):
            with self.subTest(strategy=strategy), self.case(strategy) as case:
                store, service, state, flow = case
                errors = []
                finish = service._finish_context

                def interrupted(*args, **kwargs):
                    finish(*args, **kwargs)
                    raise KeyboardInterrupt("SYNTHETIC_PRIVATE_INTERRUPTION")

                service._finish_context = interrupted
                with patch(
                    "threading.excepthook", lambda args: errors.append(args)
                ):
                    flow.analyze()
                self.assert_unknown(
                    store, strategy, service, state, flow, errors
                )
                with store.connect() as connection:
                    self.assertEqual(
                        connection.execute(
                            f"SELECT observation FROM {strategy}_capacity_operations"
                        ).fetchone()[0],
                        "",
                    )

    def test_blocked_interrupted_cleanup_keeps_lease_until_actual_exit(self):
        for strategy in ("gemini", "context"):
            with (
                self.subTest(strategy=strategy),
                self.case(strategy, timeout=0.2) as case,
            ):
                store, service, state, flow = case
                entered, release = threading.Event(), threading.Event()
                errors = []

                def interrupted(_response):
                    entered.set()
                    release.wait(3)
                    raise KeyboardInterrupt("SYNTHETIC_PRIVATE_INTERRUPTION")

                with (
                    patch.object(FakeResponse, "close", interrupted),
                    patch(
                        "threading.excepthook", lambda args: errors.append(args)
                    ),
                ):
                    try:
                        flow.analyze()
                        self.assertTrue(entered.is_set())
                        with self.assertRaises(AppError):
                            service.close()
                        with self.assertRaises(AppError):
                            Service(Store(store.path))
                    finally:
                        release.set()
                        for _ in range(300):
                            if service._active == 0:
                                break
                            time.sleep(0.01)
                self.assert_unknown(
                    store, strategy, service, state, flow, errors
                )


if __name__ == "__main__":
    unittest.main()
