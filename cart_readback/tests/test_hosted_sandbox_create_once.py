import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / "scripts/hosted_sandbox_create_once.py"
SPEC = importlib.util.spec_from_file_location("hosted_once", PATH)
SHIM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHIM)


def context():
    return {
        "GITHUB_REPOSITORY": "thzthix/cart-readback",
        "GITHUB_REPOSITORY_ID": "1443556432",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_NUMBER": "1", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": SHIM.WORKFLOW,
        "GITHUB_RUN_ID": "123456", "GITHUB_SHA": "a" * 40,
    }


class HostedOnceTest(unittest.TestCase):
    def test_gate_rejects_all_context_mutations(self):
        SHIM.require_first_run(context())
        for key in context():
            for value in (None, "", "2", "01", "wrong"):
                if key == "GITHUB_RUN_ID" and value == "2":
                    continue
                with self.subTest(key=key, value=value):
                    changed = dict(context(), **{key: value})
                    with self.assertRaises(ValueError):
                        SHIM.require_first_run(changed)

    def test_run_gate_precedes_source_and_proxy_discovery(self):
        with (
            mock.patch.object(SHIM, "verified_launcher") as source,
            mock.patch.object(SHIM, "getproxies") as proxies,
        ):
            with self.assertRaises(ValueError):
                SHIM.preflight(Path("unused"), {})
        source.assert_not_called()
        proxies.assert_not_called()

    def test_proxy_and_trust_refused_without_mutation(self):
        for name in ("HTTPS_PROXY", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR"):
            env = dict(context(), **{name: "SECRET_PROXY"})
            before = dict(env)
            with self.assertRaisesRegex(ValueError, "^Host incompatible$"):
                SHIM.require_direct_host(env)
            self.assertEqual(env, before)
        for proxies in ({"https": "SECRET"}, None, {"http": 1}, {1: "x"}):
            with mock.patch.object(SHIM, "getproxies", return_value=proxies):
                with self.assertRaises(ValueError):
                    SHIM.require_direct_host(context())
        with mock.patch.object(SHIM, "getproxies", side_effect=RuntimeError("secret")):
            with self.assertRaises(RuntimeError):
                SHIM.require_direct_host(context())

    def test_secrets_removed_even_when_incomplete(self):
        env = {SHIM.SECRET_NAMES[0]: "fake-client"}
        with self.assertRaises(ValueError):
            SHIM.take_credentials(env)
        self.assertEqual(env, {})

    def test_source_mismatch_never_executes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            (root / "scripts/sandbox_create_acceptance.py").write_text(
                "raise AssertionError('must not execute')"
            )
            with self.assertRaisesRegex(ValueError, "Source mismatch"):
                SHIM.verified_launcher(root)

    def test_only_pipe_gets_secret_and_only_safe_file_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state, output = root / "private", root / "public"
            env = dict(context(), **dict(zip(SHIM.SECRET_NAMES, (
                "fake-client", "fake-secret", "fake-merchant"
            ))))
            receipt = {"status": "UNKNOWN", "provider_success": False}
            def checked(value):
                self.assertEqual(value, receipt)
                return value
            runner = types.SimpleNamespace(
                UNKNOWN=receipt,
                matches=lambda *args: True,
                private_directory=lambda path: os.open(path, os.O_RDONLY),
                prepare=lambda *args: {"plan_sha256": "a" * 64},
                encoded=lambda value: json.dumps(value).encode(),
                parse=json.loads,
                private_read=lambda fd, name: (state / name).read_bytes(),
                checked_receipt=checked,
            )
            outer = self
            class Child:
                pid = 123456
                def __init__(self, command, **kwargs):
                    outer.assertNotIn("fake-secret", str(command))
                    outer.assertFalse(set(SHIM.SECRET_NAMES) & set(kwargs["env"]))
                    credential = json.loads(os.read(kwargs["pass_fds"][0], 1024))
                    outer.assertEqual(credential["client_secret"], "fake-secret")
                    (state / "receipt.json").write_text(json.dumps(receipt))
                    (state / "consumed").write_text(json.dumps({
                        "operation": "private-operation", "plan_sha256": "a" * 64,
                        "status": "UNKNOWN",
                    }))
                def wait(self, **kwargs):
                    return 1
            printed = io.StringIO()
            with (
                contextlib.redirect_stdout(printed),
                mock.patch.object(SHIM, "preflight", return_value=runner),
                mock.patch.object(SHIM.subprocess, "Popen", Child),
                mock.patch("socket.socket", side_effect=AssertionError("network")),
            ):
                SHIM.execute_once(root, state, output, env)
            report = (output / "evidence.json").read_text()
            self.assertEqual(json.loads(printed.getvalue()), json.loads(report))
            self.assertNotIn("fake-", report)
            self.assertNotIn("private-operation", report)
            self.assertNotIn("plan_sha256", report)
            self.assertTrue(json.loads(report)["local_consumed_marker_present"])
            self.assertEqual([p.name for p in output.iterdir()], ["evidence.json"])
            self.assertFalse(set(SHIM.SECRET_NAMES) & set(env))

    def test_later_run_refuses_before_launcher_or_subprocess(self):
        env = dict(context(), GITHUB_RUN_NUMBER="2")
        env.update(dict(zip(SHIM.SECRET_NAMES, ("fake", "fake", "fake"))))
        with (
            mock.patch.object(SHIM, "verified_launcher") as source,
            mock.patch.object(SHIM.subprocess, "Popen") as process,
            mock.patch.object(SHIM, "take_credentials") as credentials,
        ):
            with self.assertRaises(ValueError):
                SHIM.execute_once(Path("unused"), Path("unused"), Path("unused"), env)
        source.assert_not_called()
        process.assert_not_called()
        credentials.assert_not_called()

    def test_main_error_does_not_echo_exception(self):
        import contextlib
        import io
        output = io.StringIO()
        with (
            mock.patch.object(SHIM.sys, "argv", ["shim", "preflight"]),
            mock.patch.object(SHIM.os, "environ", {"GITHUB_WORKSPACE": "unused"}),
            mock.patch.object(SHIM, "preflight", side_effect=RuntimeError("SECRET")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(SHIM.main(), 1)
        self.assertNotIn("SECRET", output.getvalue())

    def test_old_python_rejected_before_source(self):
        with (
            mock.patch.object(SHIM.sys, "version_info", (3, 10)),
            mock.patch.object(SHIM, "verified_launcher") as source,
        ):
            with self.assertRaises(ValueError):
                SHIM.preflight(Path("unused"), context())
        source.assert_not_called()

    def test_static_workflow_guards_and_secret_step(self):
        path = PATH.parents[2] / ".github/workflows/paypal-sandbox-create-once.yml"
        source = path.read_text()
        self.assertIn("on:\n  workflow_dispatch:\n", source)
        for trigger in ("pull_request:", "push:", "schedule:", "workflow_call:"):
            self.assertNotIn(trigger, source)
        self.assertIn("permissions:\n  contents: read", source)
        self.assertIn("cancel-in-progress: false", source)
        self.assertIn("ref: " + SHIM.CORE_SHA, source)
        self.assertNotIn("upload-artifact", source)
        self.assertNotIn("retention-days", source)
        before, secret_step = source.split(
            "      - name: Provision private pipe", 1
        )
        self.assertNotIn("secrets.", before)
        for segment in (before, secret_step):
            for gate in (
                "github.repository == 'thzthix/cart-readback'",
                "github.repository_id == '1443556432'",
                "github.event_name == 'workflow_dispatch'",
                "github.ref == 'refs/heads/main'",
                "github.workflow_ref == '" + SHIM.WORKFLOW + "'",
                "github.run_number == 1", "github.run_attempt == 1",
            ):
                self.assertIn(gate, segment)
        for name in SHIM.SECRET_NAMES:
            self.assertEqual(source.count("secrets." + name + " }}"), 1)
        self.assertEqual(source.count("secrets."), 3)

    def test_pinned_launcher_prepare_pipe_with_stub_subprocess(self):
        # Real frozen launcher prepare/private directory/receipt parser. The
        # subprocess is a local standard-library stub, never the network runner.
        import subprocess
        workspace = Path(os.environ.get("GITHUB_WORKSPACE", PATH.parents[2]))
        root = workspace / "core/cart_readback"
        if not root.exists():
            root = PATH.parents[1]
        env = context()
        env.update(dict(zip(SHIM.SECRET_NAMES, (
            "fake-client", "fake-secret", "ABCDEFGHJKLMN"
        ))))
        real_popen = subprocess.Popen
        stub = (
            "import os,json,sys,pathlib; "
            "value=json.loads(os.read(int(sys.argv[1]),1024)); "
            "assert value['client_secret']=='fake-secret'; "
            "assert not any(k.startswith('PAYPAL_SANDBOX_') for k in os.environ); "
            "p=pathlib.Path(sys.argv[2]); "
            "plan=json.loads((p/'plan.json').read_text()); "
            "import hashlib; h=hashlib.sha256((p/'plan.json').read_bytes()).hexdigest(); "
            "records={'consumed':{'operation':plan['operation'],'plan_sha256':h,'status':'UNKNOWN'},"
            "'receipt.json':{'status':'UNKNOWN','provider_success':False}}; "
            "[(lambda fd,b:(os.write(fd,b),os.fsync(fd),os.close(fd)))"
            "(os.open(str(p/n),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),json.dumps(v).encode())"
            " for n,v in records.items()]"
        )
        def launch_stub(command, **kwargs):
            state = command[command.index("--directory") + 1]
            fd = command[command.index("--credential-fd") + 1]
            return real_popen([SHIM.sys.executable, "-I", "-S", "-c", stub, fd, state], **kwargs)
        printed = io.StringIO()
        with (
            contextlib.redirect_stdout(printed),
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(SHIM, "getproxies", return_value={}),
            mock.patch.object(SHIM.subprocess, "Popen", side_effect=launch_stub),
        ):
            state, output = Path(folder) / "private", Path(folder) / "public"
            SHIM.execute_once(root, state, output, env)
            result = json.loads((output / "evidence.json").read_text())
            self.assertEqual(json.loads(printed.getvalue()), result)
            self.assertTrue(result["local_consumed_marker_present"])
            self.assertEqual(result["receipt"]["status"], "UNKNOWN")
            self.assertEqual(result["github_run_id"], "123456")
            self.assertEqual(result["workflow_revision"], "a" * 40)

    def test_extra_or_invalid_public_evidence_rejected(self):
        runner = types.SimpleNamespace(checked_receipt=lambda value: value)
        evidence = {
            "schema": "hosted-sandbox-create-evidence-v1",
            "workflow_slot_consumed": True,
            "local_consumed_marker_present": False,
            "source_revision": SHIM.CORE_SHA,
            "receipt": {"status": "UNKNOWN", "provider_success": False},
            "github_run_id": "123", "workflow_revision": "a" * 40,
        }
        SHIM.checked_evidence(evidence, runner)
        for change in ({"private": "SECRET"}, {"github_run_id": "SECRET"},
                       {"local_consumed_marker_present": 1},
                       {"workflow_revision": "SECRET"}):
            with self.assertRaises(ValueError):
                SHIM.checked_evidence(dict(evidence, **change), runner)


if __name__ == "__main__":
    unittest.main()
