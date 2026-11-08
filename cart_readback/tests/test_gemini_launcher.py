"""Synthetic-only manual launcher tests; sockets and HTTPS are forbidden."""

import copy
import getpass
import http.client
import importlib.util
import io
import os
import signal
import socket
import stat
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cartreadback_app.gemini_capacity import FREE_MODE
from cartreadback_app.gemini_runtime import CredentialBinding
from cartreadback_app.responses_adapter import Deadline
from cartreadback_app.validation import canonical, digest
from test_gemini_runner import plan

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts/launch_gemini_analysis.py"
)
spec = importlib.util.spec_from_file_location("gemini_launcher", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
runner = launcher.runner


class LauncherTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.db = self.root / "existing.sqlite3"
        self.owner = self.root / "owner"
        self.approval = self.root / "approval.json"
        for target in ("socket", "create_connection"):
            guard = patch.object(
                socket, target, side_effect=AssertionError("network")
            )
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(
            http.client, "HTTPSConnection", side_effect=AssertionError("HTTPS")
        )
        guard.start()
        self.addCleanup(guard.stop)
        self.host_plan = plan()
        self.host_plan["policy"].update(
            admission_mode=FREE_MODE,
            tier="free",
            input_rate_micro_usd_per_million=0,
            output_rate_micro_usd_per_million=0,
        )
        self.host_plan["limits"].update(
            admission_mode=FREE_MODE, max_micro_usd=0
        )
        self.make_record()

    def make_record(self):
        request = runner.prepare(
            self.db,
            self.owner,
            self.host_plan,
            "KB-UK-C2C",
            [{"kind": "layout", "value": "UK_QWERTY"}],
        )
        self.record = dict(
            schema=runner.APPROVAL_SCHEMA,
            approval_reference="synthetic_only",
            request_sha256=digest(request),
            request=request,
        )
        self.save()

    def save(self):
        self.approval.write_text(canonical(self.record))

    def launch(self):
        launcher.launch(str(self.db), str(self.owner), str(self.approval))

    def test_invalid_approval_and_runtime_fail_before_prompt(self):
        original = copy.deepcopy(self.record)
        for mutate in (
            lambda r: r.update(request_sha256="0" * 64),
            lambda r: r["request"].update(runtime_sha256="0" * 64),
            lambda r: r.update(schema="not-approved"),
        ):
            self.record = copy.deepcopy(original)
            mutate(self.record)
            self.save()
            with patch.object(launcher, "_prompt_key") as prompt:
                with self.assertRaises(Exception):
                    self.launch()
                prompt.assert_not_called()

    def test_limits_rejected_before_prompt(self):
        original = copy.deepcopy(self.host_plan)
        for change in (
            {"max_calls": 2},
            {"max_total_input_tokens": 1048577},
            {"max_total_input_tokens": 1},
            {"max_total_output_tokens": 1},
            {"max_total_output_tokens": 2049},
            {"valid_from": 1, "expires_at": 2},
        ):
            self.host_plan = copy.deepcopy(original)
            self.host_plan["limits"].update(change)
            if "expires_at" in change:
                self.host_plan["policy"].update(change)
            self.make_record()
            with patch.object(launcher, "_prompt_key") as prompt:
                with self.assertRaises(Exception):
                    self.launch()
                prompt.assert_not_called()
        self.host_plan = plan()
        self.make_record()
        with patch.object(launcher, "_prompt_key") as prompt:
            with self.assertRaises(Exception):
                self.launch()
            prompt.assert_not_called()

    def test_owner_missing_and_replaced_db_fail_before_prompt(self):
        with patch.object(launcher, "_prompt_key") as prompt:
            owner = self.owner.read_text()
            self.owner.write_text("wrong_owner")
            with self.assertRaises(Exception):
                self.launch()
            self.owner.write_text(owner)
            replacement = self.root / "replacement"
            replacement.write_bytes(self.db.read_bytes())
            replacement.replace(self.db)
            with self.assertRaises(Exception):
                self.launch()
            self.db.unlink()
            with self.assertRaises(Exception):
                self.launch()
            self.assertFalse(self.db.exists())
            prompt.assert_not_called()

    def test_exact_single_run_private_fifo_and_no_ambient_key(self):
        descriptors = []

        def consume(db, owner, record, descriptor):
            descriptors.append(descriptor)
            info = os.fstat(descriptor)
            self.assertTrue(stat.S_ISFIFO(info.st_mode))
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            self.assertEqual(info.st_nlink, 0)
            self.assertFalse(os.get_inheritable(descriptor))
            binding = CredentialBinding(**record["request"]["plan"]["binding"])
            handle = runner.InheritedPipeCredential(descriptor, binding)
            import time

            self.assertEqual(
                handle.borrow(
                    expected_binding=binding,
                    deadline=Deadline(time.monotonic() + 1, 1, 1),
                ),
                "synthetic_key",
            )

        with (
            patch.object(launcher, "_prompt_key", return_value="synthetic_key"),
            patch.object(runner, "run", side_effect=consume) as run,
            patch.dict(os.environ, {"GEMINI_API_KEY": "wrong_ambient"}),
        ):
            self.launch()
            run.assert_called_once()
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_invalid_keys_eof_interrupt_and_failure_are_sanitized(self):
        args = [
            "--db",
            str(self.db),
            "--owner-file",
            str(self.owner),
            "--approved-record",
            str(self.approval),
        ]
        for value in (
            "",
            "x" * 257,
            "synthetic\n",
            "한",
            EOFError("secret"),
            KeyboardInterrupt("secret"),
            getpass.GetPassWarning("secret"),
        ):
            kwargs = (
                {"side_effect": value}
                if isinstance(value, BaseException)
                else {"return_value": value}
            )
            output = io.StringIO()
            with (
                patch.object(launcher, "_prompt_key", **kwargs),
                patch.object(runner, "run") as run,
                redirect_stderr(output),
                redirect_stdout(output),
            ):
                self.assertEqual(launcher.main(args), 1)
                run.assert_not_called()
            self.assertNotIn("secret", output.getvalue())

    def test_run_exception_and_signal_close_fifo_no_retry(self):
        for failure in (RuntimeError("secret"), KeyboardInterrupt()):
            descriptors = []

            def fail(*args):
                descriptors.append(args[-1])
                raise failure

            previous = signal.getsignal(signal.SIGTERM)
            with (
                patch.object(
                    launcher, "_prompt_key", return_value="synthetic_key"
                ),
                patch.object(runner, "run", side_effect=fail) as run,
            ):
                with self.assertRaises(type(failure)):
                    self.launch()
                run.assert_called_once()
            self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
            with self.assertRaises(OSError):
                os.fstat(descriptors[0])

    def test_actual_sigterm_cleanup(self):
        with launcher._interrupt_cleanup():
            with self.assertRaises(KeyboardInterrupt):
                os.kill(os.getpid(), signal.SIGTERM)

    def test_no_terminal_and_warning_never_fallback(self):
        with (
            patch.object(os, "open", side_effect=OSError("no tty")),
            patch.object(getpass, "getpass") as prompt,
        ):
            with self.assertRaises(OSError):
                launcher._prompt_key()
            prompt.assert_not_called()
        # A real temporary fd is used only to exercise warning handling offline.
        with tempfile.TemporaryFile(mode="w+") as terminal:

            def warning(*args, **kwargs):
                warnings.warn("secret", getpass.GetPassWarning)
                self.fail("fallback was reached")

            with (
                patch.object(
                    os, "open", return_value=os.dup(terminal.fileno())
                ),
                patch.object(os, "isatty", return_value=True),
                patch.object(getpass, "getpass", side_effect=warning),
            ):
                with self.assertRaises(getpass.GetPassWarning):
                    launcher._prompt_key()

    def test_fifo_directory_mode_and_failed_write_cleanup(self):
        directories = []
        descriptors = []
        original_mkfifo = os.mkfifo
        original_open = os.open

        def make_fifo(path, mode):
            directories.append(Path(path).parent)
            self.assertEqual(
                stat.S_IMODE(Path(path).parent.stat().st_mode), 0o700
            )
            return original_mkfifo(path, mode)

        def open_fifo(path, flags, *args, **kwargs):
            descriptor = original_open(path, flags, *args, **kwargs)
            if str(path).endswith("credential"):
                descriptors.append(descriptor)
            return descriptor

        with (
            patch.object(os, "mkfifo", side_effect=make_fifo),
            patch.object(os, "open", side_effect=open_fifo),
            patch.object(os, "write", side_effect=OSError("synthetic_secret")),
        ):
            with self.assertRaises(OSError):
                with launcher._private_fifo("synthetic_key"):
                    self.fail("must not yield")
        self.assertTrue(directories)
        self.assertFalse(directories[0].exists())
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_cli_outputs_only_runner_public_envelope(self):
        args = [
            "--db",
            str(self.db),
            "--owner-file",
            str(self.owner),
            "--approved-record",
            str(self.approval),
        ]
        output = io.StringIO()
        with (
            patch.object(launcher, "_prompt_key", return_value="synthetic_key"),
            patch.object(runner, "run", return_value={"mode": "fixture"}),
            redirect_stdout(output),
        ):
            self.assertEqual(launcher.main(args), 0)
        self.assertEqual(output.getvalue(), '{"mode":"fixture"}\n')
        self.assertNotIn("synthetic_key", output.getvalue())

    def test_expiry_during_prompt_prevents_run(self):
        expires = self.host_plan["limits"]["expires_at"]
        with (
            patch.object(launcher, "_prompt_key", return_value="synthetic_key"),
            patch.object(
                launcher.time, "time", side_effect=[expires - 1, expires]
            ),
            patch.object(runner, "run") as run,
        ):
            with self.assertRaises(Exception):
                self.launch()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
