"""Host runner uses only synthetic approvals and keys; provider never contacted."""

import copy
import importlib.util
import os
import shutil
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cartreadback_app.gemini_client import CURRENT_MODEL
from cartreadback_app.gemini_runtime import CredentialBinding
from cartreadback_app.responses_adapter import Deadline
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, digest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_gemini_analysis.py"
spec = importlib.util.spec_from_file_location("gemini_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def plan():
    now = int(time.time())
    return {
        "binding": {
            "project": "synthetic_project",
            "credential_version": "v1",
            "host_revision": "test_host",
        },
        "config": {
            "expected_model_version": CURRENT_MODEL,
            "model": CURRENT_MODEL,
            "response_language": "en",
        },
        "policy": {
            "valid_from": now - 10,
            "expires_at": now + 600,
            "model": CURRENT_MODEL,
            "expected_model_version": CURRENT_MODEL,
            "max_input_tokens": 1048576,
            "input_rate_micro_usd_per_million": 1000000,
            "output_rate_micro_usd_per_million": 1000000,
            "project": "synthetic_project",
            "tier": "paid",
            "eligibility_record_sha256": "a" * 64,
            "pricing_record_sha256": "b" * 64,
            "admission_mode": "paid",
            "host_decision_record_sha256": "d" * 64,
        },
        "binding_record_sha256": "c" * 64,
        "pricing_adoption_record_sha256": "b" * 64,
        "installation_revision": "synthetic_install",
        "timeout_seconds": 1.0,
        "limits": {
            "valid_from": now - 10,
            "expires_at": now + 600,
            "max_calls": 1,
            "max_total_input_tokens": 1048576,
            "max_total_output_tokens": 2048,
            "max_micro_usd": 1050624,
            "admission_mode": "paid",
        },
    }


class RunnerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.db = self.root / "test.sqlite3"
        self.owner = self.root / "owner"
        self.no_socket = patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("No network"),
        )
        self.no_socket.start()
        self.addCleanup(self.no_socket.stop)

    def prepare(self):
        return runner.prepare(
            self.db,
            self.owner,
            plan(),
            "KB-UK-C2C",
            [
                {"kind": "layout", "value": "UK_QWERTY"},
            ],
        )

    def record(self):
        request = self.prepare()
        return {
            "schema": runner.APPROVAL_SCHEMA,
            "approval_reference": "fabricated_only",
            "request_sha256": digest(request),
            "request": request,
        }

    def test_prepare_has_exact_nonsecret_scope_no_approval_or_borrow(self):
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "ambient_synthetic"}),
            patch.object(
                os, "read", side_effect=AssertionError("No credential reads")
            ),
        ):
            request = self.prepare()
        self.assertEqual(request["schema"], runner.REQUEST_SCHEMA)
        self.assertEqual(request["conditions"][0]["condition_id"], "c1")
        self.assertNotIn(self.owner.read_text(), str(request))
        self.assertEqual(self.owner.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("ambient_synthetic", str(request))
        self.assertEqual(
            runner._existing_store(
                self.db, self.owner.read_text(), request
            ).path,
            self.db,
        )

    def test_explicit_model_and_config_fields_are_mandatory(self):
        for field in ("model", "expected_model_version", "response_language"):
            with self.subTest(field=field):
                host_plan = plan()
                del host_plan["config"][field]
                with self.assertRaises(AppError):
                    runner.prepare(
                        self.db,
                        self.owner,
                        host_plan,
                        "KB-UK-C2C",
                        [
                            {"kind": "layout", "value": "UK_QWERTY"},
                        ],
                    )
                self.assertFalse(self.db.exists())

    def test_prepare_is_not_approved_record(self):
        request = self.prepare()
        with self.assertRaises(AppError):
            runner.approved_request(request)
        record = {
            "schema": runner.APPROVAL_SCHEMA,
            "request": request,
            "request_sha256": digest(request),
            "approved": True,
        }
        with self.assertRaises(AppError):
            runner.approved_request(record)

    def test_altered_approval_request_rejected(self):
        record = self.record()
        record["request"]["conditions"][0]["value"] = "DE_QWERTZ"
        with self.assertRaises(AppError):
            runner.approved_request(record)

    def test_missing_store_never_recreated(self):
        record = self.record()
        self.db.unlink()
        with self.assertRaises(FileNotFoundError):
            runner.run(self.db, self.owner, record, 3)
        self.assertFalse(self.db.exists())

    def test_different_and_copied_database_rejected(self):
        record = self.record()
        other = self.root / "other.sqlite3"
        Store(other)
        with self.assertRaises(AppError):
            runner.run(other, self.owner, record, 3)
        other.unlink()
        shutil.copy2(self.db, other)
        with self.assertRaises(AppError):
            runner.run(other, self.owner, record, 3)

    def test_replaced_store_same_location_rejected(self):
        record = self.record()
        other = self.root / "copy.sqlite3"
        shutil.copy2(self.db, other)
        other.replace(self.db)
        with self.assertRaises(AppError):
            runner.run(self.db, self.owner, record, 3)

    def test_foreign_owner_and_stale_catalog_rejected_before_handle(self):
        record = self.record()
        with patch.object(
            runner,
            "InheritedPipeCredential",
            side_effect=AssertionError("No handle"),
        ):
            sid = self.owner.read_text()
            self.owner.write_text("foreign_synthetic_owner")
            with self.assertRaises(AppError):
                runner.run(self.db, self.owner, record, 3)
            self.owner.write_text(sid)
            store = Store(self.db)
            product = copy.deepcopy(record["request"]["catalog"])
            product["price_minor"] += 1
            store.replace_product(product)
            with self.assertRaises(AppError):
                runner.run(self.db, self.owner, record, 3)

    def test_deleted_after_precheck_cannot_create_database(self):
        record = self.record()
        existing = runner._existing_store(
            self.db, self.owner.read_text(), record["request"]
        )
        self.db.unlink()
        with self.assertRaises(FileNotFoundError):
            existing.connect()
        self.assertFalse(self.db.exists())

    def test_run_composes_only_analysis_and_exact_fixture_payment(self):
        # This observes runner wiring only. It is not provider wire evidence.
        record = self.record()
        from cartreadback_app.gemini_runtime import (
            GeminiAnalysisRuntime,
            ProviderTransportBinding,
        )
        from cartreadback_app.payments import FixturePaymentAdapter

        with patch.object(runner, "Service", autospec=True) as service_type:
            service = service_type.return_value
            service.mutate.return_value = {"test_seam": "not_dispatched"}
            with patch.object(
                os, "read", side_effect=AssertionError("No key read")
            ):
                result = runner.run(self.db, self.owner, record, 3)
            args = service_type.call_args.kwargs
            self.assertIs(type(args["payments"]), FixturePaymentAdapter)
            runtime = args["gemini_analysis"]
            self.assertIs(type(runtime), GeminiAnalysisRuntime)
            self.assertIs(
                type(runtime.installed.transport), ProviderTransportBinding
            )
            self.assertEqual(service.mutate.call_count, 1)
            self.assertEqual(service.mutate.call_args.args[1], "analyze")
            self.assertEqual(result, {"test_seam": "not_dispatched"})
            service.close.assert_called_once()

    def test_changed_runtime_identity_rejected_before_fd(self):
        record = self.record()
        record["request"]["plan"]["binding"]["credential_version"] = "v2"
        record["request_sha256"] = digest(record["request"])
        with self.assertRaises(AppError):
            runner.run(self.db, self.owner, record, 3)


class PipeTests(unittest.TestCase):
    def setUp(self):
        self.binding = CredentialBinding("synthetic_project", "v1", "host")
        self.read, self.write = os.pipe()
        self.addCleanup(os.close, self.read)

    def handle(self):
        return runner.InheritedPipeCredential(self.read, self.binding)

    def borrow(self, handle, seconds=1):
        return handle.borrow(
            expected_binding=self.binding,
            deadline=Deadline(time.monotonic() + seconds, 1, 1),
        )

    def test_lazy_then_single_use(self):
        handle = self.handle()
        os.write(self.write, b"synthetic_key_not_real")
        os.close(self.write)
        self.assertEqual(self.borrow(handle), "synthetic_key_not_real")
        with self.assertRaises(AppError):
            self.borrow(handle)

    def test_open_writer_without_eof_is_deadline_bounded(self):
        self.addCleanup(os.close, self.write)
        os.write(self.write, b"synthetic_key")
        started = time.monotonic()
        with self.assertRaises(AppError):
            self.borrow(self.handle(), seconds=0.02)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_overlong_key_rejected(self):
        os.write(self.write, b"x" * 4097)
        os.close(self.write)
        with self.assertRaises(AppError):
            self.borrow(self.handle())

    def test_opaque_key_preserved_at_local_limit(self):
        value = b"fake.authorization+token/with=" + b"x" * 4066
        self.assertEqual(len(value), 4096)
        os.write(self.write, value)
        os.close(self.write)
        handle = self.handle()
        self.assertEqual(self.borrow(handle), value.decode("ascii"))
        with self.assertRaises(AppError):
            self.borrow(handle)

    def test_invalid_graphic_ascii_rejected_and_consumed(self):
        os.close(self.write)
        for value in (
            b"",
            b" ",
            b"fake key",
            b"fake\t",
            b"fake\r",
            b"fake\n",
            b"fake\x00",
            b"fake\x7f",
            b"fake\xff",
            "é".encode("utf-8"),
            b"x" * 4097,
        ):
            with self.subTest(value=value[:10]):
                read, write = os.pipe()
                try:
                    os.write(write, value)
                finally:
                    os.close(write)
                try:
                    handle = runner.InheritedPipeCredential(read, self.binding)
                    with self.assertRaises(AppError):
                        self.borrow(handle)
                    with self.assertRaises(AppError):
                        self.borrow(handle)
                finally:
                    os.close(read)

    def test_newline_key_rejected(self):
        os.write(self.write, b"synthetic_key\n")
        os.close(self.write)
        with self.assertRaises(AppError):
            self.borrow(self.handle())

    def test_binding_mismatch_does_not_consume_pipe(self):
        os.write(self.write, b"synthetic_key")
        os.close(self.write)
        handle = self.handle()
        with self.assertRaises(AppError):
            handle.borrow(
                expected_binding=CredentialBinding("other", "v1", "host"),
                deadline=Deadline(time.monotonic() + 1, 1, 1),
            )
        self.assertEqual(self.borrow(handle), "synthetic_key")

    def test_regular_file_rejected(self):
        os.close(self.write)
        with tempfile.TemporaryFile() as stream:
            stream.write(b"synthetic_key")
            stream.seek(0)
            handle = runner.InheritedPipeCredential(
                stream.fileno(), self.binding
            )
            with self.assertRaises(AppError):
                self.borrow(handle)
            self.assertEqual(stream.tell(), 0)


if __name__ == "__main__":
    unittest.main()
