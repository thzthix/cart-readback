"""One consumed sandbox create observation, never a checkout or payment pass.

POSIX host-only entry point. No defaults discover credentials or start networking.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import sys
import time
import types
from uuid import UUID, uuid4

BASE = "43150d6846b50a94a9350c3df33294b0b87feb47"
HASHES = {
    "payments.py": (
        "90ab034fdb92d2bb9de5fdb157e00fa7ea5adb7de8355404e0f331d09c16c3d6"
    ),
    "paypal_https.py": (
        "a2cbf0a2aac6a35fcac65bb61d2b5e4ecfd4197ed2841ace29a39863b002e331"
    ),
    "paypal_sandbox.py": (
        "9f12837b47df2dbcc331a0b25caace79c4213e6919bd598eee084e7d8f9fe5ce"
    ),
    "provider_json.py": (
        "0e46ff9f01bdb58d5191355d7f1e7a7fefc64b78939ca1432d318447e66bf64f"
    ),
    "validation.py": (
        "e343efd1b6806336f0588398fe9ee8ca5a0ea436303810ee05ba0480660bf6f2"
    ),
}
UNKNOWN = {"status": "UNKNOWN", "provider_success": False}


def encoded(value: object) -> bytes:
    """Encode deterministic private plan or sanitized receipt bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def pairs(items: list) -> dict:
    """Reject duplicate JSON fields."""
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Invalid record")
        result[key] = value
    return result


def parse(data: bytes) -> dict:
    """Parse bounded exact JSON without retaining parser diagnostics."""
    if not 0 < len(data) <= 8192:
        raise ValueError("Invalid record")
    value = json.loads(data, object_pairs_hook=pairs)
    if type(value) is not dict:
        raise ValueError("Invalid record")
    return value


def matches(value: object, pattern: str) -> bool:
    """Require exact string shape without returning user input."""
    return type(value) is str and re.fullmatch(pattern, value) is not None


def request_body(merchant: str, operation: str) -> dict:
    """Freeze one synthetic keyboard, USD79, no tax/shipping or callbacks."""
    return {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": operation,
            "custom_id": hashlib.sha256(operation.encode()).hexdigest(),
            "payee": {"merchant_id": merchant},
            "amount": {
                "currency_code": "USD", "value": "79.00",
                "breakdown": {"item_total": {
                    "currency_code": "USD", "value": "79.00"
                }},
            },
            "items": [{
                "sku": "KB-UK-C2C", "name": "Synthetic keyboard example",
                "quantity": "1",
                "unit_amount": {"currency_code": "USD", "value": "79.00"},
            }],
        }],
    }


def validate_plan(plan: dict, now: int) -> None:
    """Require the exact one-create scope and short unexpired window."""
    if set(plan) != {
        "schema", "base", "operation", "merchant", "client_id", "created",
        "expires", "body", "max_creates", "max_oauth", "max_usd_minor",
    }:
        raise ValueError("Invalid plan")
    operation = plan["operation"]
    if not matches(operation, r"[a-f0-9-]{36}"):
        raise ValueError("Invalid plan")
    identifier = UUID(operation)
    if str(identifier) != operation or identifier.version != 4:
        raise ValueError("Invalid plan")
    if (
        plan["schema"] != "sandbox-create-acceptance-v1"
        or plan["base"] != BASE
        or not matches(plan["merchant"], r"[2-9A-HJ-NP-Z]{13}")
        or not matches(plan["client_id"], r"[A-Za-z0-9._~-]{1,256}")
        or type(plan["created"]) is not int
        or type(plan["expires"]) is not int
        or not plan["created"] <= now < plan["expires"]
        or not 0 < plan["expires"] - plan["created"] <= 900
        or any(type(plan[k]) is not int for k in (
            "max_creates", "max_oauth", "max_usd_minor"
        ))
        or (plan["max_creates"], plan["max_oauth"], plan["max_usd_minor"])
        != (1, 1, 7900)
        or plan["body"] != request_body(plan["merchant"], operation)
    ):
        raise ValueError("Invalid plan")


def private_directory(path: Path) -> int:
    """Open an existing owner-only directory with no symlink components."""
    absolute = path.absolute()
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise ValueError("Unsafe directory")
    fd = os.open(absolute, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(fd)
        raise ValueError("Unsafe directory")
    return fd


def private_read(directory: int, name: str) -> bytes:
    """Read a bounded private regular file relative to the pinned directory."""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
            or info.st_size > 8192
        ):
            raise ValueError("Unsafe record")
        return os.read(fd, 8193)
    finally:
        os.close(fd)


def exclusive_write(directory: int, name: str, data: bytes) -> None:
    """Create once and fsync both file and directory before proceeding."""
    fd = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600, dir_fd=directory,
    )
    try:
        if os.write(fd, data) != len(data):
            raise ValueError("Record incomplete")
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(directory)


def prepare(directory: int, merchant: str, client_id: str) -> dict:
    """Create one immutable local plan; never overwrite an existing attempt."""
    # A consumed marker always blocks, even if a plan was manually removed.
    try:
        os.stat("consumed", dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise ValueError("Already consumed")
    now = int(time.time())
    operation = str(uuid4())
    plan = {
        "schema": "sandbox-create-acceptance-v1", "base": BASE,
        "operation": operation, "merchant": merchant, "client_id": client_id,
        "created": now, "expires": now + 900,
        "max_creates": 1, "max_oauth": 1, "max_usd_minor": 7900,
        "body": request_body(merchant, operation),
    }
    validate_plan(plan, now)
    data = encoded(plan)
    exclusive_write(directory, "plan.json", data)
    return {
        "status": "NOT_EXECUTED", "plan_sha256": hashlib.sha256(
            data).hexdigest(
            ),
        "expires": plan["expires"], "provider_success": False,
    }


def validate_pipe(fd: int) -> None:
    """Accept an inherited read-only FIFO descriptor, never a regular file."""
    if type(fd) is not int or fd < 3:
        raise ValueError("Invalid credential descriptor")
    info = os.fstat(fd)
    if (
        not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
        or fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
    ):
        raise ValueError("Invalid credential descriptor")


def borrow(fd: int, client_id: str, deadline: float) -> tuple[str, str]:
    """Read one bounded JSON credential pair in child memory only."""
    validate_pipe(fd)
    data = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise ValueError("Credential unavailable")
        chunk = os.read(fd, 1025 - len(data))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > 1024:
            raise ValueError("Credential unavailable")
    value = parse(bytes(data))
    if (
        set(value) != {"client_id", "client_secret"}
        or value["client_id"] != client_id
        or not matches(value["client_secret"], r"[A-Za-z0-9._~-]{1,256}")
    ):
        raise ValueError("Credential unavailable")
    return value["client_id"], value["client_secret"]


def load_core(root: Path):
    """Verify exact main module bytes before importing the shipped core."""
    sources = {}
    for name, expected in HASHES.items():
        source = (root / "cartreadback_app" / name).read_bytes()
        if hashlib.sha256(source).hexdigest() != expected:
            raise ValueError("Source integrity mismatch")
        sources[name] = source
    if any(
        k == "cartreadback_app" or k.startswith("cartreadback_app.")
        for k in sys.modules
    ):
        raise ValueError("Core already loaded")
    package = types.ModuleType("cartreadback_app")
    package.__path__ = []
    sys.modules["cartreadback_app"] = package
    for name in (
        "validation.py", "provider_json.py", "payments.py",
        "paypal_sandbox.py", "paypal_https.py",
    ):
        module_name = "cartreadback_app." + name[:-3]
        module = types.ModuleType(module_name)
        module.__package__ = "cartreadback_app"
        sys.modules[module_name] = module
        setattr(package, name[:-3], module)
        # Execute verified in-memory bytes; do not trust cached bytecode or
        # re-open paths after checking their hashes.
        exec(compile(sources[name], name, "exec"), module.__dict__)
    package.paypal_https.normalize_paypal_order = (
        package.paypal_sandbox.normalize_paypal_order
    )
    return package.paypal_https


def observation(response, core) -> dict:
    """Project only bounded nonpersonal response facts; never raw bodies."""
    if (
        type(response.status_code) is not int
        or response.status_code not in (200, 201)
    ):
        return dict(UNKNOWN)
    raw = core.strict_provider_json(
        response.body,
        max_bytes=65536,
        max_depth=16)
    identity, status = raw.get("id"), raw.get("status")
    if not matches(identity, r"[A-Z0-9]{1,36}") or status not in {
        "CREATED", "SAVED", "APPROVED", "VOIDED", "COMPLETED",
        "PAYER_ACTION_REQUIRED",
    }:
        return dict(UNKNOWN)
    # Validate returned field shape, but do not infer absent facts from request.
    try:
        normalized = core.normalize_paypal_order(raw)
    except Exception:
        normalized = {}

    return {
        "status": "PARTIAL_PROVIDER_OBSERVATION", "provider_success": False,
        "http_status": response.status_code, "provider_order_id": identity,
        "provider_status": status,
        "evidence_available": {key: key in normalized for key in (
            "reference_id", "custom_id", "merchant_id",
            "amount_minor", "currency", "items"
        )},
    }


def checked_receipt(value: dict) -> dict:
    """Reject unexpected child output before persistence or parent stdout."""
    if value == UNKNOWN and set(value) == set(UNKNOWN):
        return dict(UNKNOWN)
    if (
        set(value) != {"status", "provider_success", "http_status",
                       "provider_order_id", "provider_status",
                       "evidence_available"}
        or value["status"] != "PARTIAL_PROVIDER_OBSERVATION"
        or value["provider_success"] is not False
        or type(value["http_status"]) is not int
        or value["http_status"] not in (200, 201)
        or not matches(value["provider_order_id"], r"[A-Z0-9]{1,36}")
        or not matches(value["provider_status"],
                       r"CREATED|SAVED|APPROVED|VOIDED|COMPLETED|PAYER_ACTION_REQUIRED")
        or type(value["evidence_available"]) is not dict
        or set(value["evidence_available"]) != {
            "reference_id", "custom_id", "merchant_id",
            "amount_minor", "currency", "items"
        }
        or any(
            type(v) is not bool for v in value["evidence_available"].values())
    ):
        raise ValueError("Invalid child receipt")
    return value


def child_exchange(plan: dict, credential_fd: int, root: Path) -> dict:
    """Borrow lazily inside the consumed child and send only the create route."""
    validate_plan(plan, int(time.time()))
    core = load_core(root)
    deadline = time.monotonic() + min(20, plan["expires"] - time.time())
    borrowed = False

    def credential_source():
        nonlocal borrowed
        if borrowed:
            raise ValueError("Credential already borrowed")
        validate_plan(plan, int(time.time()))
        if time.monotonic() >= deadline:
            raise ValueError("Expired credential window")
        borrowed = True
        credentials = borrow(credential_fd, plan["client_id"], deadline)
        validate_plan(plan, int(time.time()))
        if time.monotonic() >= deadline:
            raise ValueError("Expired credential window")
        return core.SandboxClientCredentials(*credentials)

    transport = core.SandboxHttpsTransport(
        credential_source=credential_source,
        connection_factory=core.DirectSandboxConnectionFactory(),
        credential_reference="sandbox-create-acceptance-existing-app",
    )
    remaining = plan["expires"] - time.time()
    if remaining <= 1:
        raise ValueError("Expired exchange window")
    duration = min(20, remaining - 1)
    deadline = time.monotonic() + duration
    response = transport.send(
        core.SANDBOX_ENDPOINT,
        core.PaymentRequest(
            "POST",
            "/v2/checkout/orders",
            encoded(plan["body"]).decode()),
        {"Accept": "application/json", "Content-Type": "application/json",
         "Prefer": "return=representation", "PayPal-Request-Id": plan[
             "operation"]},
        timeout_seconds=duration,
    )
    return observation(response, core)


def run(directory: int, plan_hash: str, credential_fd: int, root: Path) -> dict:
    """Consume once before forking; kill local child on timeout, never retry."""
    data = private_read(directory, "plan.json")
    if (
        not matches(plan_hash, r"[a-f0-9]{64}")
        or hashlib.sha256(data).hexdigest() != plan_hash
    ):
        raise ValueError("Plan mismatch")
    plan = parse(data)
    validate_plan(plan, int(time.time()))
    validate_pipe(credential_fd)
    exclusive_write(directory, "consumed", encoded({
        "operation": plan["operation"], "plan_sha256": plan_hash,
        "status": "UNKNOWN",
    }))
    reader, writer = os.pipe()
    try:
        pid = os.fork()
    except BaseException:
        os.close(reader)
        os.close(writer)
        raise
    if pid == 0:
        os.close(reader)
        os.close(directory)
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        try:
            receipt = child_exchange(plan, credential_fd, root)
            os.write(writer, encoded(receipt))
        except BaseException:
            os.write(writer, encoded(UNKNOWN))
        finally:
            os._exit(0)
    os.close(writer)
    receipt = dict(UNKNOWN)
    try:
        remaining = min(25, plan["expires"] - time.time())
        if remaining > 0 and select.select([reader], [], [], remaining)[0]:
            receipt = checked_receipt(parse(os.read(reader, 2048)))
    except Exception:
        receipt = dict(UNKNOWN)
    finally:
        os.close(reader)
        # Kill only our unreaped child. This is not cancellation of remote work.
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == 0:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
    exclusive_write(directory, "receipt.json", encoded(receipt))
    return receipt


def main() -> int:
    """Dispatch explicit prepare/run commands without secret CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "run"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--merchant")
    parser.add_argument("--client-id")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--credential-fd", type=int)
    def invalid(_message):
        raise ValueError("Invalid arguments")
    parser.error = invalid
    directory = None
    try:
        args = parser.parse_args()
        directory = private_directory(args.directory)
        if args.phase == "prepare":
            if args.credential_fd is not None or args.plan_sha256 is not None:
                raise ValueError("Invalid phase")
            result = prepare(directory, args.merchant, args.client_id)
        else:
            if args.merchant is not None or args.client_id is not None:
                raise ValueError("Invalid phase")
            result = run(
                directory,
                args.plan_sha256,
                args.credential_fd,
                Path(__file__).resolve().parents[1])
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "NOT_EXECUTED" else 1
    except Exception:
        print(
            json.dumps({"status": "BLOCKED_OR_UNKNOWN",
            "provider_success": False}))
        return 2
    finally:
        if directory is not None:
            os.close(directory)


if __name__ == "__main__":
    raise SystemExit(main())
