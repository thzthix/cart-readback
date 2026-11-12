"""Trusted GitHub provisioning shim for one separately approved sandbox create."""

import hashlib
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import types
from urllib.request import getproxies

CORE_SHA = "75d5b7e3bafdecc1cfb322cfd6c19d49a0abd30a"
LAUNCHER_HASH = "85e6fb6693827bc6a8003f98410fb3baced2176f369b662901aa02e615cf655f"
WORKFLOW = "thzthix/cart-readback/.github/workflows/paypal-sandbox-create-once.yml@refs/heads/main"
SECRET_NAMES = (
    "PAYPAL_SANDBOX_CLIENT_ID", "PAYPAL_SANDBOX_CLIENT_SECRET",
    "PAYPAL_SANDBOX_MERCHANT_ID",
)


def require_first_run(environment: dict) -> None:
    """Reject every later run/rerun and every other repository/ref/workflow."""
    if sys.version_info < (3, 11):
        raise ValueError("Unsupported Python")
    expected = {
        "GITHUB_REPOSITORY": "thzthix/cart-readback",
        "GITHUB_REPOSITORY_ID": "1443556432",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_NUMBER": "1", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": WORKFLOW,
    }
    if any(environment.get(k) != v for k, v in expected.items()):
        raise ValueError("Run not eligible")
    if (
        type(environment.get("GITHUB_RUN_ID")) is not str
        or type(environment.get("GITHUB_SHA")) is not str
        or re.fullmatch(r"[1-9][0-9]{0,19}", environment.get("GITHUB_RUN_ID", ""))
        is None
        or re.fullmatch(r"[a-f0-9]{40}", environment.get("GITHUB_SHA", ""))
        is None
    ):
        raise ValueError("Invalid run identity")


def require_direct_host(environment: dict) -> None:
    """Refuse proxies/trust overrides; never remove or bypass them."""
    if any(
        value for key, value in environment.items()
        if key.lower().endswith("_proxy")
        or key.upper() in {"SSL_CERT_FILE", "SSL_CERT_DIR"}
    ):
        raise ValueError("Host incompatible")
    proxies = getproxies()
    if (
        type(proxies) is not dict
        or any(type(k) is not str or type(v) is not str
               for k, v in proxies.items())
        or any(proxies.values())
    ):
        raise ValueError("Host incompatible")


def verified_launcher(root: Path):
    """Load exact launcher bytes after nonsecret host gates, not provider code."""
    source = (root / "scripts/sandbox_create_acceptance.py").read_bytes()
    if hashlib.sha256(source).hexdigest() != LAUNCHER_HASH:
        raise ValueError("Source mismatch")
    module = types.ModuleType("sandbox_create_acceptance")
    exec(compile(source, "sandbox_create_acceptance.py", "exec"), module.__dict__)
    for name, digest in module.HASHES.items():
        data = (root / "cartreadback_app" / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Source mismatch")
    reader, writer = os.pipe()
    try:
        module.validate_pipe(reader)
    finally:
        os.close(reader)
        os.close(writer)
    return module


def preflight(root: Path, environment: dict):
    """Check immutable workflow context, host policy and source before secrets."""
    require_first_run(environment)
    require_direct_host(environment)
    return verified_launcher(root)


def take_credentials(environment: dict) -> tuple[str, str, str]:
    """Pop only the three explicitly provisioned secrets before child creation."""
    values = tuple(environment.pop(name, "") for name in SECRET_NAMES)
    if not all(type(value) is str and value for value in values):
        raise ValueError("Credential provisioning incomplete")
    return values


def checked_evidence(value: dict, runner) -> dict:
    """Allow only fixed nonsecret evidence fields into the hosted job log."""
    if (
        set(value) != {"schema", "workflow_slot_consumed",
                       "local_consumed_marker_present", "source_revision",
                       "receipt", "github_run_id", "workflow_revision"}
        or value["schema"] != "hosted-sandbox-create-evidence-v1"
        or value["workflow_slot_consumed"] is not True
        or type(value["local_consumed_marker_present"]) is not bool
        or value["source_revision"] != CORE_SHA
        or type(value["github_run_id"]) is not str
        or re.fullmatch(r"[1-9][0-9]{0,19}", value["github_run_id"]) is None
        or type(value["workflow_revision"]) is not str
        or re.fullmatch(r"[a-f0-9]{40}", value["workflow_revision"]) is None
    ):
        raise ValueError("Invalid evidence")
    return {**value, "receipt": runner.checked_receipt(value["receipt"])}


def execute_once(root: Path, state: Path, output: Path, environment: dict) -> None:
    """Provision one private pipe and export only revalidated safe evidence."""
    runner = preflight(root, environment)
    client_id, secret, merchant = take_credentials(environment)
    if not runner.matches(secret, r"[A-Za-z0-9._~-]{1,256}"):
        raise ValueError("Invalid credential")
    # These are explicitly per-run private files, not cross-run consumption.
    state.mkdir(mode=0o700, exist_ok=False)
    directory = runner.private_directory(state)
    reader = writer = None
    receipt = dict(runner.UNKNOWN)
    try:
        plan = runner.prepare(directory, merchant, client_id)
        reader, writer = os.pipe()
        data = runner.encoded({"client_id": client_id, "client_secret": secret})
        if len(data) > 1024 or os.write(writer, data) != len(data):
            raise ValueError("Credential pipe incomplete")
        os.close(writer)
        writer = None
        # No provisioned secrets in argv or child environment. Core host checks
        # still run inside the child; original proxy settings were not removed.
        command = [
            sys.executable, "-I", "-S",
            str(root / "scripts/sandbox_create_acceptance.py"), "run",
            "--directory", str(state), "--plan-sha256", plan["plan_sha256"],
            "--credential-fd", str(reader),
        ]
        child = subprocess.Popen(
            command, pass_fds=(reader,), env=dict(environment),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            child.wait(timeout=35)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        try:
            receipt = runner.checked_receipt(
                runner.parse(runner.private_read(directory, "receipt.json"))
            )
        except (OSError, ValueError, TypeError, KeyError):
            receipt = dict(runner.UNKNOWN)
        try:
            consumed = runner.parse(runner.private_read(directory, "consumed"))
            consumed_present = (
                set(consumed) == {"operation", "plan_sha256", "status"}
                and consumed["plan_sha256"] == plan["plan_sha256"]
                and consumed["status"] == "UNKNOWN"
            )
        except (OSError, ValueError, TypeError):
            consumed_present = False
        public = {
            "schema": "hosted-sandbox-create-evidence-v1",
            "workflow_slot_consumed": True,
            "local_consumed_marker_present": consumed_present,
            "source_revision": CORE_SHA, "receipt": receipt,
            "github_run_id": environment["GITHUB_RUN_ID"],
            "workflow_revision": environment["GITHUB_SHA"],
        }
        public = checked_evidence(public, runner)
        output.mkdir(mode=0o700, exist_ok=False)
        (output / "evidence.json").write_bytes(runner.encoded(public))
        print(json.dumps(public, sort_keys=True))
    finally:
        for fd in (reader, writer, directory):
            if fd is not None:
                os.close(fd)


def main() -> int:
    """Use fixed workflow directories; emit no exception or secret diagnostics."""
    try:
        workspace = Path(os.environ["GITHUB_WORKSPACE"])
        root = workspace / "core/cart_readback"
        if sys.argv[1:] == ["preflight"]:
            preflight(root, os.environ)
            print("Nonsecret preflight passed; provider not executed")
        elif sys.argv[1:] == ["run"]:
            execute_once(
                root, workspace / "private-attempt", workspace / "safe-evidence",
                os.environ,
            )
        else:
            raise ValueError("Unsupported phase")
        return 0
    except Exception:
        print("BLOCKED_OR_UNKNOWN; one-use workflow slot remains spent")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
