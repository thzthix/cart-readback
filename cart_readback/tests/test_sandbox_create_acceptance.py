import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

PATH = Path(
    __file__).resolve(
    ).parents[
    1] / "scripts/sandbox_create_acceptance.py"
SPEC = importlib.util.spec_from_file_location("acceptance", PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
MERCHANT = "ABCDEFGHJKLMN"


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        os.chmod(self.path, 0o700)
        self.directory = RUNNER.private_directory(self.path)

    def tearDown(self):
        os.close(self.directory)
        self.temp.cleanup()

    def plan(self):
        receipt = RUNNER.prepare(self.directory, MERCHANT, "synthetic-client")
        plan = RUNNER.parse(RUNNER.private_read(self.directory, "plan.json"))
        return receipt, plan

    def test_prepare_offline_no_overwrite(self):
        with mock.patch("socket.socket", side_effect=AssertionError("network")):
            receipt, plan = self.plan()
        self.assertEqual(receipt["status"], "NOT_EXECUTED")
        self.assertNotIn(MERCHANT, json.dumps(receipt))
        self.assertEqual(
            plan["body"]["purchase_units"][0]["amount"]["value"],
            "79.00")
        with self.assertRaises(FileExistsError):
            RUNNER.prepare(self.directory, MERCHANT, "synthetic-client")

    def test_plan_scope_expiry_and_tampering(self):
        _, plan = self.plan()
        for key, value in (("max_creates", 2), ("max_oauth", True),
                           ("max_usd_minor", 7901), ("base", "other"),
                           ("expires", plan["created"]), ("merchant", "bad")):
            modified = dict(plan, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                RUNNER.validate_plan(modified, int(time.time()))
        modified = json.loads(json.dumps(plan))
        modified["body"]["purchase_units"][0]["amount"]["value"] = "78.00"
        with self.assertRaises(ValueError):
            RUNNER.validate_plan(modified, int(time.time()))

    def test_private_files_symlink_mode_and_hardlink(self):
        self.plan()
        os.chmod(self.path / "plan.json", 0o644)
        with self.assertRaises(ValueError):
            RUNNER.private_read(self.directory, "plan.json")
        os.chmod(self.path / "plan.json", 0o600)
        os.link(self.path / "plan.json", self.path / "duplicate")
        with self.assertRaises(ValueError):
            RUNNER.private_read(self.directory, "plan.json")
        (self.path / "alias").symlink_to(self.path / "plan.json")
        with self.assertRaises(OSError):
            RUNNER.private_read(self.directory, "alias")

    def test_pipe_only_bounded_bound_identity(self):
        with tempfile.TemporaryFile() as file:
            with self.assertRaises(ValueError):
                RUNNER.validate_pipe(file.fileno())
        for data, valid in ((b'{"client_id":"synthetic-client","client_secret":"fake"}', True),
                            (b'x' * 1025, False),
                            (
                                b'{"client_id":"wrong","client_secret":"fake"}',
                                False)):
            reader, writer = os.pipe()
            os.write(writer, data)
            os.close(writer)
            try:
                if valid:
                    self.assertEqual(
                        RUNNER.borrow(reader,
                        "synthetic-client",
                        time.monotonic()+1),
                        ("synthetic-client",
                        "fake"))
                else:
                    with self.assertRaises(ValueError):
                        RUNNER.borrow(
                            reader,
                            "synthetic-client",
                            time.monotonic()+1)
            finally:
                os.close(reader)

    def test_consumed_before_child_and_no_retry(self):
        receipt, _ = self.plan()
        reader, writer = os.pipe()
        os.close(writer)
        try:
            with mock.patch.object(
                RUNNER.os,
                "fork",
                side_effect=RuntimeError("failure")):
                with self.assertRaises(RuntimeError):
                    RUNNER.run(
                        self.directory,
                        receipt["plan_sha256"],
                        reader,
                        self.path)
            marker = RUNNER.parse(
                RUNNER.private_read(self.directory,
                "consumed"))
            self.assertEqual(marker["status"], "UNKNOWN")
            with mock.patch.object(
                RUNNER.os,
                "fork",
                side_effect=AssertionError("retry")):
                with self.assertRaises(FileExistsError):
                    RUNNER.run(
                        self.directory,
                        receipt["plan_sha256"],
                        reader,
                        self.path)
        finally:
            os.close(reader)

    def test_fake_child_observation_and_redaction(self):
        receipt, _ = self.plan()
        reader, writer = os.pipe()
        os.close(writer)
        try:
            expected = dict(RUNNER.UNKNOWN)
            with mock.patch.object(
                RUNNER,
                "child_exchange",
                return_value=expected):
                result = RUNNER.run(
                    self.directory,
                    receipt["plan_sha256"],
                    reader,
                    self.path)
            self.assertEqual(result, expected)
            self.assertTrue((self.path / "consumed").exists())
        finally:
            os.close(reader)

    def test_projection_never_contains_raw_personal_data(self):
        core = types.SimpleNamespace(
            strict_provider_json=lambda body,
            **kw: json.loads(body))
        wire = {
            "id": "SANDBOX123",
            "status": "PAYER_ACTION_REQUIRED",
            "payer": {"email": "SECRET"},
            "links": [{"href": "SECRET"}],
            "purchase_units": [{"payee": {"merchant_id": "SECRET"}}]}
        response = types.SimpleNamespace(
            status_code=201,
            body=json.dumps(wire).encode())
        report = RUNNER.observation(response, core)
        self.assertEqual(report["status"], "PARTIAL_PROVIDER_OBSERVATION")
        self.assertFalse(report["provider_success"])
        self.assertNotIn("SECRET", json.dumps(report))
        self.assertEqual(report["provider_status"], "PAYER_ACTION_REQUIRED")

    def test_core_integrity_rejected_before_import(self):
        with self.assertRaises(FileNotFoundError):
            RUNNER.load_core(self.path)
        self.assertNotIn("cartreadback_app.paypal_https", sys.modules)

    def test_unexpected_child_output_is_unknown(self):
        receipt, _ = self.plan()
        reader, writer = os.pipe()
        os.close(writer)
        try:
            with mock.patch.object(RUNNER, "child_exchange", return_value={
                "status": "UNKNOWN", "provider_success": False,
                "raw": "SECRET",
            }):
                result = RUNNER.run(
                    self.directory, receipt["plan_sha256"], reader, self.path
                )
            self.assertEqual(result, RUNNER.UNKNOWN)
            self.assertNotIn("SECRET", (self.path / "receipt.json").read_text())
        finally:
            os.close(reader)

    def test_fake_core_exact_request_and_expiry_before_borrow(self):
        _, plan = self.plan()
        events = []
        outer = self
        class FakeTransport:
            def __init__(self, **kwargs):
                self.source = kwargs["credential_source"]
            def send(self, endpoint, request, headers, *, timeout_seconds):
                events.append((endpoint, request, headers, timeout_seconds))
                outer.assertEqual(self.source(), ("synthetic-client", "fake"))
                with outer.assertRaises(ValueError):
                    self.source()
                return types.SimpleNamespace(
                    status_code=201,
                    body=b'{"id":"ORDER123","status":"PAYER_ACTION_REQUIRED"}')
        core = types.SimpleNamespace(
            SandboxHttpsTransport=FakeTransport,
            DirectSandboxConnectionFactory=lambda: "fake-factory",
            SandboxClientCredentials=lambda *args: args,
            SANDBOX_ENDPOINT="https://api-m.sandbox.paypal.com",
            PaymentRequest=lambda *args: args,
            strict_provider_json=lambda body, **kw: json.loads(body),
            normalize_paypal_order=lambda raw: {},
        )
        reader, writer = os.pipe()
        os.write(
            writer,
            b'{"client_id":"synthetic-client","client_secret":"fake"}')
        os.close(writer)
        try:
            with mock.patch.object(RUNNER, "load_core", return_value=core):
                result = RUNNER.child_exchange(plan, reader, self.path)
            self.assertEqual(result["status"], "PARTIAL_PROVIDER_OBSERVATION")
            self.assertEqual(events[0][1][:2], ("POST", "/v2/checkout/orders"))
            self.assertEqual(
                events[0][2]["PayPal-Request-Id"],
                plan["operation"])
            self.assertLessEqual(events[0][3], 20)
            expired = dict(plan, expires=plan["created"])
            with mock.patch.object(
                RUNNER,
                "load_core",
                side_effect=AssertionError("import")):
                with self.assertRaises(ValueError):
                    RUNNER.child_exchange(expired, reader, self.path)
        finally:
            os.close(reader)

    def test_timeout_kills_only_owned_child_and_retains_consumed(self):
        receipt, _ = self.plan()
        reader, writer = os.pipe()
        os.close(writer)
        try:
            with (
                mock.patch.object(RUNNER.os, "fork", return_value=123456),
                mock.patch.object(
                    RUNNER.select,
                    "select",
                    return_value=([],
                    [],
                    [])),
                mock.patch.object(
                    RUNNER.os,
                    "waitpid",
                    side_effect=[(0,
                    0),
                    (123456,
                    0)]),
                mock.patch.object(RUNNER.os, "kill") as kill,
            ):
                result = RUNNER.run(
                    self.directory,
                    receipt["plan_sha256"],
                    reader,
                    self.path)
            kill.assert_called_once_with(123456, RUNNER.signal.SIGKILL)
            self.assertEqual(result, RUNNER.UNKNOWN)
            self.assertTrue((self.path / "consumed").exists())
        finally:
            os.close(reader)

    def test_wrong_hash_never_forks(self):
        self.plan()
        with mock.patch.object(
            RUNNER.os,
            "fork",
            side_effect=AssertionError("fork")):
            with self.assertRaises(ValueError):
                RUNNER.run(self.directory, "0" * 64, -1, self.path)
        self.assertFalse((self.path / "consumed").exists())

    def test_actual_fork_timeout_reaps_child(self):
        receipt, _ = self.plan()
        reader, writer = os.pipe()
        os.close(writer)
        original_fork = os.fork
        children = []
        def tracked_fork():
            pid = original_fork()
            if pid:
                children.append(pid)
            return pid
        try:
            with (
                mock.patch.object(RUNNER.os, "fork", side_effect=tracked_fork),
                mock.patch.object(
                    RUNNER,
                    "child_exchange",
                    side_effect=lambda *a: time.sleep(5)),
                mock.patch.object(
                    RUNNER.select,
                    "select",
                    return_value=([],
                    [],
                    [])),
            ):
                result = RUNNER.run(
                    self.directory,
                    receipt["plan_sha256"],
                    reader,
                    self.path)
            self.assertEqual(result, RUNNER.UNKNOWN)
            with self.assertRaises(ChildProcessError):
                os.waitpid(children[0], os.WNOHANG)
        finally:
            os.close(reader)

    def test_concurrent_runs_only_one_fake_side_effect(self):
        receipt, _ = self.plan()
        credentials, credentials_writer = os.pipe()
        os.close(credentials_writer)
        events, event_writer = os.pipe()
        children = []
        def fake_exchange(*args):
            os.write(event_writer, b"one")
            return dict(RUNNER.UNKNOWN)
        try:
            with mock.patch.object(
                RUNNER,
                "child_exchange",
                side_effect=fake_exchange):
                for _ in range(2):
                    pid = os.fork()
                    if pid == 0:
                        try:
                            RUNNER.run(
                                self.directory,
                                receipt["plan_sha256"],
                                credentials,
                                self.path)
                        except FileExistsError:
                            pass
                        finally:
                            os._exit(0)
                    children.append(pid)
                for pid in children:
                    os.waitpid(pid, 0)
            os.close(event_writer)
            event_writer = None
            self.assertEqual(os.read(events, 20), b"one")
        finally:
            for fd in (credentials, events, event_writer):
                if fd is not None:
                    os.close(fd)

    def test_real_core_fake_https_oauth_and_create(self):
        _, plan = self.plan()
        base = PATH.parents[1]
        core = RUNNER.load_core(base)
        exchanges = []
        class Socket:
            def settimeout(self, timeout):
                pass
        class Response:
            status = 200
            def __init__(self, body):
                self.body = body
                self.remaining = body
            def getheaders(self):
                return [("content-type", "application/json"),
                        ("content-length", str(len(self.body)))]
            def read(self, length):
                chunk, self.remaining = self.remaining[
                    :length], self.remaining[
                    length:]
                return chunk
            def isclosed(self):
                return not self.remaining
            def close(self):
                pass
        class Connection:
            def __init__(self, *args, **kwargs):
                self.sock = Socket()
            def set_debuglevel(self, level):
                pass
            def connect(self):
                pass
            def request(self, method, path, **kwargs):
                self.path = path
                exchanges.append((method, path, kwargs))
            def getresponse(self):
                if self.path == "/v1/oauth2/token":
                    return Response(
                        b'{"token_type":"Bearer","access_token":"fake-token",'
                        b'"expires_in":100,"scope":"fake"}')
                return Response(
                    b'{"id":"ORDER123","status":"PAYER_ACTION_REQUIRED"}')
            def close(self):
                pass
        reader, writer = os.pipe()
        os.write(
            writer,
            b'{"client_id":"synthetic-client","client_secret":"fake"}')
        os.close(writer)
        try:
            with (
                mock.patch.object(RUNNER, "load_core", return_value=core),
                mock.patch.object(core.os, "environ", {}),
                mock.patch.object(core, "getproxies", return_value={}),
                mock.patch.object(
                    core.http.client,
                    "HTTPSConnection",
                    Connection),
                mock.patch(
                    "socket.socket",
                    side_effect=AssertionError("network")),
            ):
                result = RUNNER.child_exchange(plan, reader, base)
            self.assertEqual(result["status"], "PARTIAL_PROVIDER_OBSERVATION")
            self.assertEqual([(m,p) for m,p,_ in exchanges], [
                ("POST", "/v1/oauth2/token"), ("POST", "/v2/checkout/orders")
            ])
            self.assertEqual(
                exchanges[1][2]["body"],
                RUNNER.encoded(plan["body"]))
            self.assertEqual(
                exchanges[1][2]["headers"]["PayPal-Request-Id"],
                plan["operation"])
            self.assertEqual(
                exchanges[1][2]["headers"]["Authorization"],
                "Bearer fake-token")
        finally:
            os.close(reader)
            for key in list(sys.modules):
                if (
                    key == "cartreadback_app"
                    or key.startswith("cartreadback_app.")
                ):
                    del sys.modules[key]

    def test_killed_coordinator_consumption_survives_restart(self):
        receipt, _ = self.plan()
        reader, writer = os.pipe()
        os.close(writer)
        pid = os.fork()
        if pid == 0:
            with mock.patch.object(
                RUNNER.os,
                "fork",
                side_effect=lambda: os.kill(os.getpid(),
                RUNNER.signal.SIGKILL)):
                RUNNER.run(
                    self.directory,
                    receipt["plan_sha256"],
                    reader,
                    self.path)
            os._exit(9)
        try:
            _, status = os.waitpid(pid, 0)
            self.assertTrue(os.WIFSIGNALED(status))
            self.assertTrue((self.path / "consumed").exists())
            with mock.patch.object(
                RUNNER.os,
                "fork",
                side_effect=AssertionError("replay")):
                with self.assertRaises(FileExistsError):
                    RUNNER.run(
                        self.directory,
                        receipt["plan_sha256"],
                        reader,
                        self.path)
        finally:
            os.close(reader)

    def test_empty_credential_pipe_no_http(self):
        _, plan = self.plan()
        core = RUNNER.load_core(PATH.parents[1])
        reader, writer = os.pipe()
        os.close(writer)
        try:
            with (
                mock.patch.object(RUNNER, "load_core", return_value=core),
                mock.patch.object(core.os, "environ", {}),
                mock.patch.object(core, "getproxies", return_value={}),
                mock.patch.object(
                    core.http.client,
                    "HTTPSConnection",
                    side_effect=AssertionError("HTTP")) as connection,
            ):
                with self.assertRaises(core.ProviderAmbiguity):
                    RUNNER.child_exchange(plan, reader, PATH.parents[1])
                connection.assert_not_called()
        finally:
            os.close(reader)
            for key in list(sys.modules):
                if (
                    key == "cartreadback_app"
                    or key.startswith("cartreadback_app.")
                ):
                    del sys.modules[key]

    def test_near_expiry_fails_before_transport_send(self):
        _, plan = self.plan()
        transport = mock.Mock()
        core = types.SimpleNamespace(
            SandboxHttpsTransport=mock.Mock(return_value=transport),
            DirectSandboxConnectionFactory=mock.Mock(),
        )
        with (
            mock.patch.object(RUNNER, "load_core", return_value=core),
            mock.patch.object(
                RUNNER.time,
                "time",
                return_value=plan["expires"] - 0.5),
        ):
            with self.assertRaisesRegex(ValueError, "Expired exchange window"):
                RUNNER.child_exchange(plan, 99, self.path)
        transport.send.assert_not_called()

    def test_borrow_crossing_expiry_never_returns_credentials(self):
        _, plan = self.plan()
        wall = [plan["created"]]
        source = []
        class Transport:
            def __init__(self, **kwargs):
                source.append(kwargs["credential_source"])
            def send(self, *args, **kwargs):
                return source[0]()
        credentials = mock.Mock()
        core = types.SimpleNamespace(
            SandboxHttpsTransport=Transport,
            DirectSandboxConnectionFactory=mock.Mock(),
            SandboxClientCredentials=credentials,
            SANDBOX_ENDPOINT="https://api-m.sandbox.paypal.com",
            PaymentRequest=mock.Mock(),
        )
        def delayed_borrow(*args):
            wall[0] = plan["expires"] + 1
            return "synthetic-client", "fake"
        with (
            mock.patch.object(RUNNER, "load_core", return_value=core),
            mock.patch.object(RUNNER, "borrow", side_effect=delayed_borrow),
            mock.patch.object(RUNNER.time, "time", side_effect=lambda: wall[0]),
        ):
            with self.assertRaises(ValueError):
                RUNNER.child_exchange(plan, 99, self.path)
        credentials.assert_not_called()

    def test_parent_wait_uses_remaining_plan_window(self):
        receipt, plan = self.plan()
        reader, writer = os.pipe()
        os.close(writer)
        try:
            with (
                mock.patch.object(
                    RUNNER.time,
                    "time",
                    return_value=plan["expires"] - 0.5),
                mock.patch.object(RUNNER.os, "fork", return_value=123456),
                mock.patch.object(
                    RUNNER.select,
                    "select",
                    return_value=([],
                    [],
                    [])) as wait,
                mock.patch.object(
                    RUNNER.os,
                    "waitpid",
                    side_effect=[(0,
                    0),
                    (123456,
                    0)]),
                mock.patch.object(RUNNER.os, "kill"),
            ):
                result = RUNNER.run(
                    self.directory,
                    receipt["plan_sha256"],
                    reader,
                    self.path)
            self.assertEqual(wait.call_args.args[3], 0.5)
            self.assertEqual(result, RUNNER.UNKNOWN)
        finally:
            os.close(reader)


if __name__ == "__main__":
    unittest.main()
