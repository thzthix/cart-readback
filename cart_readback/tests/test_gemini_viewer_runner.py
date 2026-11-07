"""Shared approved runner lifetime uses synthetic mocks, never a browser/key."""

import contextlib
import io
import threading
import unittest
from unittest.mock import patch

import test_gemini_runner as fixtures
from cartreadback_app.validation import AppError

runner = fixtures.runner


class ViewerRunnerTests(unittest.TestCase):
    def setUp(self):
        self.helper = fixtures.RunnerTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.record = self.helper.record()

    def test_same_service_scope_single_analyze_and_synchronous_cleanup(self):
        with (
            patch.object(runner, "Service", autospec=True) as service_type,
            patch(
                "cartreadback_app.gemini_viewer.GeminiResultViewer",
                autospec=True,
            ) as viewer_type,
            patch.object(runner.time, "sleep") as sleep,
        ):
            service = service_type.return_value
            service.close.side_effect = [
                AppError("INVALID_STATE", "Still active", 409),
                None,
            ]
            viewer = viewer_type.return_value
            stopped = threading.Event()
            viewer.serve_forever.side_effect = stopped.wait
            viewer.shutdown.side_effect = stopped.set
            viewer.launch.side_effect = KeyboardInterrupt()  # host interrupt

            def opener(_):
                return True

            output = io.StringIO()
            with (
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(output),
            ):
                runner.view(
                    self.helper.db, self.helper.owner, self.record, 3, opener
                )
            self.assertEqual(service.mutate.call_count, 1)
            self.assertEqual(service.mutate.call_args.args[1], "analyze")
            args = viewer_type.call_args.args
            self.assertIs(args[1], service)
            self.assertEqual(args[2], self.helper.owner.read_text())
            self.assertEqual(
                args[3:5],
                (
                    self.record["request"]["catalog"],
                    self.record["request"]["conditions"],
                ),
            )
            viewer.launch.assert_called_once_with(opener)
            viewer.server_close.assert_called_once()
            self.assertEqual(service.close.call_count, 2)
            sleep.assert_called_once_with(0.05)
            self.assertEqual(output.getvalue(), "")

    def test_opener_failure_closes_server_then_original_service(self):
        events = []
        with (
            patch.object(runner, "Service", autospec=True) as service_type,
            patch(
                "cartreadback_app.gemini_viewer.GeminiResultViewer",
                autospec=True,
            ) as viewer_type,
        ):
            service = service_type.return_value
            service.close.side_effect = lambda: events.append("service-close")
            viewer = viewer_type.return_value
            stopped = threading.Event()
            viewer.serve_forever.side_effect = stopped.wait
            viewer.shutdown.side_effect = stopped.set
            viewer.launch.side_effect = AppError(
                "VIEWER_REJECTED", "Blocked", 403
            )
            viewer.server_close.side_effect = lambda: events.append(
                "server-close"
            )
            with self.assertRaises(AppError):
                runner.view(
                    self.helper.db,
                    self.helper.owner,
                    self.record,
                    3,
                    lambda _: False,
                )
            self.assertEqual(events, ["server-close", "service-close"])
            viewer.serve_forever.assert_called_once()
            self.assertEqual(service.mutate.call_count, 1)

    def test_constructor_or_analyze_failure_keeps_cleanup_and_no_browser(self):
        for fails in ("analyze", "construct"):
            with (
                self.subTest(fails=fails),
                patch.object(runner, "Service", autospec=True) as service_type,
                patch(
                    "cartreadback_app.gemini_viewer.GeminiResultViewer",
                    autospec=True,
                ) as viewer_type,
            ):
                if fails == "analyze":
                    service_type.return_value.mutate.side_effect = AppError(
                        "GEMINI_RUN_BLOCKED", "Blocked", 503
                    )
                else:
                    viewer_type.side_effect = ValueError(
                        "Synthetic construction failure"
                    )
                with self.assertRaises((AppError, ValueError)):
                    runner.view(
                        self.helper.db,
                        self.helper.owner,
                        self.record,
                        3,
                        lambda _: self.fail("No browser"),
                    )
                service_type.return_value.close.assert_called_once()

    def test_invalid_opener_or_port_does_not_construct_service(self):
        for opener, port in (
            (None, 0),
            (lambda _: True, True),
            (lambda _: True, -1),
            (lambda _: True, 65536),
        ):
            with patch.object(
                runner, "Service", side_effect=AssertionError("No runtime")
            ):
                with self.assertRaises(AppError):
                    runner.view(
                        self.helper.db,
                        self.helper.owner,
                        self.record,
                        3,
                        opener,
                        port=port,
                    )
