"""Prepare offline disclosure or run one explicitly approved Gemini analysis.

This trusted-host entry point does not discover credentials or verify external
approval. A selected reviewed local record and inherited secret-store pipe are
required for run. The ordinary fixture CLI/HTTP interface is unchanged.
"""

import argparse
import os
import re
import select
import sqlite3
import stat
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cartreadback_app.gemini_capacity import (  # noqa: E402
    GeminiCapacityPolicy,
    HostGeminiAuthorization,
    gemini_database_identity,
    initialize_gemini_database,
)
from cartreadback_app.gemini_client import (  # noqa: E402
    GeminiClient,
    GeminiConfig,
)
from cartreadback_app.gemini_runtime import (  # noqa: E402
    ApprovedDataScope,
    CredentialBinding,
    GeminiAnalysisRuntime,
    InstalledGeminiContext,
    ProviderTransportBinding,
    execution_identity,
    host_provenance,
)
from cartreadback_app.payments import FixturePaymentAdapter  # noqa: E402
from cartreadback_app.provider_json import strict_provider_json  # noqa: E402
from cartreadback_app.responses_adapter import Deadline  # noqa: E402
from cartreadback_app.service import Service  # noqa: E402
from cartreadback_app.storage import Store, product_for  # noqa: E402
from cartreadback_app.validation import (  # noqa: E402
    AppError,
    canonical,
    conditions,
    digest,
    object_fields,
    text_hash,
    token,
)

REQUEST_SCHEMA = "gemini-host-approval-request-v2"
APPROVAL_SCHEMA = "gemini-approved-host-record-v2"
PLAN_FIELDS = {
    "binding",
    "config",
    "policy",
    "binding_record_sha256",
    "pricing_adoption_record_sha256",
    "installation_revision",
    "timeout_seconds",
    "limits",
}
REQUEST_FIELDS = {
    "schema",
    "plan",
    "database_id",
    "owner_sha256",
    "catalog",
    "conditions",
    "expected_revision",
    "runtime_sha256",
    "generation_request_sha256",
    "database_file_sha256",
}


def _blocked():
    return AppError("GEMINI_RUN_BLOCKED", "Gemini host run unavailable.", 503)


def _read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(131_073)
    return strict_provider_json(raw, max_bytes=131_072, max_depth=16)


def _write_private(path, value):
    # Never overwrite an owner credential, request, or approval by accident.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _owner(path):
    with Path(path).open("r", encoding="ascii") as stream:
        value = stream.read(101)
    return token(value)


class InheritedPipeCredential:
    """Single-use, bounded lazy reader for an explicitly inherited host pipe.

    Only anonymous/named FIFO descriptors are accepted, not files, sockets or
    terminals. The trusted host must supply a private pipe and close its writer.
    No descriptor read or mode change occurs until the committed-claim borrower
    is invoked. Python cannot promise erasure of every immutable string copy.
    """

    def __init__(self, descriptor: int, binding: CredentialBinding):
        """Retain nonsecret descriptor number and exact approved binding."""
        if type(descriptor) is not int or descriptor < 3:
            raise _blocked()
        if type(binding) is not CredentialBinding:
            raise _blocked()
        self._descriptor = descriptor
        self._binding = binding
        self._used = False
        self._lock = threading.Lock()

    @property
    def binding(self):
        """Return the immutable nonsecret scope without accessing the pipe."""
        return self._binding

    def borrow(self, *, expected_binding, deadline):
        """Read at most 256 ASCII key bytes after durable dispatch authorization."""
        if expected_binding != self._binding or type(deadline) is not Deadline:
            raise _blocked()
        deadline.remaining()
        with self._lock:
            if self._used:
                raise _blocked()
            self._used = True
        raw = bytearray()
        try:
            if not stat.S_ISFIFO(os.fstat(self._descriptor).st_mode):
                raise _blocked()
            os.set_blocking(self._descriptor, False)
            while True:
                remaining = deadline.remaining()
                readable, _, _ = select.select(
                    [self._descriptor], [], [], remaining
                )
                deadline.remaining()
                if not readable:
                    raise _blocked()
                try:
                    part = os.read(self._descriptor, 257 - len(raw))
                except BlockingIOError:
                    continue
                if not part:
                    break
                raw.extend(part)
                if len(raw) > 256:
                    raise _blocked()
            value = raw.decode("ascii")
            if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value) is None:
                raise _blocked()
            deadline.remaining()
            return value
        except Exception:
            raise _blocked() from None
        finally:
            raw[:] = b"\x00" * len(raw)


class _UnusableCredential:
    def __init__(self, binding):
        self.binding = binding

    def borrow(self, **_kwargs):
        raise _blocked()


def _plan(value):
    object_fields(value, PLAN_FIELDS)
    object_fields(
        value["binding"], {item.name for item in fields(CredentialBinding)}
    )
    object_fields(
        value["config"],
        {"model", "expected_model_version", "response_language"},
    )
    object_fields(
        value["policy"], {item.name for item in fields(GeminiCapacityPolicy)}
    )
    binding = CredentialBinding(**value["binding"])
    config = GeminiConfig(**value["config"])
    policy = GeminiCapacityPolicy(**value["policy"])
    transport = ProviderTransportBinding(value["installation_revision"])
    object_fields(
        value["limits"],
        {
            "valid_from",
            "expires_at",
            "max_calls",
            "max_total_input_tokens",
            "max_total_output_tokens",
            "max_micro_usd",
            "admission_mode",
        },
    )
    return binding, config, policy, transport


def _installation(request, handle=None):
    object_fields(request, REQUEST_FIELDS)
    if request["schema"] != REQUEST_SCHEMA:
        raise _blocked()
    plan = request["plan"]
    binding, config, policy, transport = _plan(plan)
    scope = ApprovedDataScope(
        (digest(request["catalog"]),),
        (digest(request["conditions"]),),
        (request["owner_sha256"],),
    )
    identity = execution_identity(
        binding,
        config,
        plan["timeout_seconds"],
        transport=transport,
        policy=policy,
    )
    if identity != request["runtime_sha256"]:
        raise _blocked()
    prepared = GeminiClient(config).prepare(
        request["catalog"]["source"], request["conditions"]
    )
    if prepared.request_sha256 != request["generation_request_sha256"]:
        raise _blocked()
    authorization = HostGeminiAuthorization(
        database_id=request["database_id"],
        provenance_sha256=host_provenance(
            plan["binding_record_sha256"],
            plan["pricing_adoption_record_sha256"],
            "provider",
            policy=policy,
        ),
        data_scope_sha256=digest(asdict(scope)),
        runtime_sha256=identity,
        policy_sha256=text_hash(policy.identity),
        **plan["limits"],
    )
    return InstalledGeminiContext(
        binding=binding,
        scope=scope,
        policy=policy,
        authorization=authorization,
        binding_record_sha256=plan["binding_record_sha256"],
        pricing_adoption_record_sha256=plan["pricing_adoption_record_sha256"],
        credential_handle=handle or _UnusableCredential(binding),
        transport=transport,
        config=config,
        evidence_kind="provider",
        timeout_seconds=plan["timeout_seconds"],
    )


def _database_file_identity(path):
    path = Path(path).resolve(strict=True)
    info = path.stat()
    return digest(
        {"path": str(path), "device": info.st_dev, "inode": info.st_ino}
    )


def prepare(db, owner_file, host_plan, sku, choices):
    """Prepare exact nonsecret disclosure; never grant approval or read a key."""
    binding, config, policy, transport = _plan(host_plan)
    selected = conditions(choices)
    ordered = [
        {"condition_id": f"c{index}", **choice}
        for index, choice in enumerate(selected, 1)
    ]
    store = Store(db)
    lease = store.acquire_service()
    try:
        if Path(owner_file).exists():
            sid = _owner(owner_file)
            with store.transaction() as connection:
                if not connection.execute(
                    "SELECT 1 FROM sessions WHERE sid = ?", (sid,)
                ).fetchone():
                    raise _blocked()
        else:
            session, _ = store.session(None)
            sid = session["sid"]
            _write_private(owner_file, sid)
        with store.transaction() as connection:
            database_id = initialize_gemini_database(connection)
            product = product_for(connection, sku)
            revision = connection.execute(
                "SELECT revision FROM sessions WHERE sid = ?", (sid,)
            ).fetchone()[0]
        request = {
            "schema": REQUEST_SCHEMA,
            "plan": host_plan,
            "database_id": database_id,
            "owner_sha256": text_hash(sid),
            "database_file_sha256": _database_file_identity(store.path),
            "catalog": product,
            "conditions": ordered,
            "expected_revision": revision,
            "runtime_sha256": execution_identity(
                binding,
                config,
                host_plan["timeout_seconds"],
                transport=transport,
                policy=policy,
            ),
            "generation_request_sha256": GeminiClient(config)
            .prepare(product["source"], ordered)
            .request_sha256,
        }
        _installation(request)
        return request
    finally:
        lease.close()


def approved_request(record):
    """Validate a trusted local reviewed record, not external consent proof."""
    object_fields(
        record,
        {
            "schema",
            "approval_reference",
            "request_sha256",
            "request",
        },
    )
    if (
        record["schema"] != APPROVAL_SCHEMA
        or type(record["approval_reference"]) is not str
        or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", record["approval_reference"])
        is None
        or record["request_sha256"] != digest(record["request"])
    ):
        raise _blocked()
    _installation(record["request"])
    return record["request"]


class _ExistingStore(Store):
    """Use only an existing prepared schema; never create a run-phase database."""

    def __init__(self, path, file_identity):
        """Retain the approved file without invoking Store's creating initializer."""
        self.path = Path(path).resolve(strict=True)
        self._file_identity = file_identity

    def connect(self):
        """Use SQLite mode=rw so deletion races cannot create a fresh database."""
        if _database_file_identity(self.path) != self._file_identity:
            raise _blocked()
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=rw",
            uri=True,
            timeout=5,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection


def _existing_store(db, sid, request):
    # URI mode=ro cannot recreate a missing store. Check before Store's creator.
    path = Path(db).resolve(strict=True)
    if (
        not path.is_file()
        or _database_file_identity(path) != request["database_file_sha256"]
    ):
        raise _blocked()
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT revision FROM sessions WHERE sid = ?", (sid,)
        ).fetchone()
        if (
            gemini_database_identity(connection) != request["database_id"]
            or text_hash(sid) != request["owner_sha256"]
            or row is None
            or row[0] != request["expected_revision"]
            or digest(product_for(connection, request["catalog"]["sku_id"]))
            != digest(request["catalog"])
        ):
            raise _blocked()
    finally:
        connection.close()
    store = _ExistingStore(path, request["database_file_sha256"])
    if _database_file_identity(path) != request["database_file_sha256"]:
        raise _blocked()
    return store


@contextmanager
def _approved_service(db, owner_file, record, credential_fd):
    """Keep exact validation, construction and synchronous cleanup shared."""
    request = approved_request(record)
    sid = _owner(owner_file)
    store = _existing_store(db, sid, request)
    binding = CredentialBinding(**request["plan"]["binding"])
    handle = InheritedPipeCredential(credential_fd, binding)
    installed = _installation(request, handle)
    service = Service(
        store,
        payments=FixturePaymentAdapter(),
        gemini_analysis=GeminiAnalysisRuntime(installed),
    )
    try:
        yield service, sid, request
    finally:
        # A watchdog result is not cancellation. Keep this process/lease alive
        # until the synchronous exchange and observation worker really exit.
        while True:
            try:
                service.close()
                break
            except AppError as error:
                if error.code != "INVALID_STATE":
                    raise
                time.sleep(0.05)


def _analyze(service, sid, request):
    return service.mutate(
        sid,
        "analyze",
        {
            "expected_revision": request["expected_revision"],
            "sku_id": request["catalog"]["sku_id"],
            "conditions": [
                {"kind": item["kind"], "value": item["value"]}
                for item in request["conditions"]
            ],
        },
    )


def run(db, owner_file, record, credential_fd):
    """Execute exactly one reviewed Service analysis, never confirm or pay."""
    with _approved_service(db, owner_file, record, credential_fd) as opened:
        service, sid, request = opened
        return _analyze(service, sid, request)


def view(
    db: str | Path,
    owner_file: str | Path,
    record: dict,
    credential_fd: int,
    opener: Callable[[str], object],
    *,
    port: int = 0,
) -> None:
    """Analyze once, then hand a private launch URL to a trusted local opener.

    The caller must separately authorize the provider action and local browser
    opening. The opener must not log or persist its argument. No URL containing
    the launch capability is returned or printed. This is not a credential or
    browser installation API. The exact Service remains owned through shutdown.
    """
    from cartreadback_app.gemini_viewer import GeminiResultViewer

    if not callable(opener) or type(port) is not int or not 0 <= port <= 65535:
        raise _blocked()
    with _approved_service(db, owner_file, record, credential_fd) as opened:
        service, sid, request = opened
        _analyze(service, sid, request)
        server = GeminiResultViewer(
            ("127.0.0.1", port),
            service,
            sid,
            request["catalog"],
            request["conditions"],
            Path(__file__).resolve().parents[1] / "ui",
        )
        failures = []

        def serve():
            try:
                server.serve_forever()
            except BaseException:
                # Never retain/log exception text from a private host lifetime.
                failures.append(True)

        serving = None
        try:
            serving = threading.Thread(target=serve)
            serving.start()
            server.launch(opener)
            while serving.is_alive():
                serving.join(0.1)
            if failures:
                raise _blocked()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                # A failed Thread constructor/start owns no joinable worker.
                if serving is not None and serving.ident is not None:
                    server.shutdown()
                    serving.join()
            finally:
                server.server_close()


def main(argv=None):
    """Run explicit prepare/run subcommands with sanitized bounded failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    offline = commands.add_parser("prepare")
    live = commands.add_parser("run")
    for command in (offline, live):
        command.add_argument("--db", required=True)
        command.add_argument("--owner-file", required=True)
    offline.add_argument("--host-plan", required=True)
    offline.add_argument("--sku", required=True)
    offline.add_argument(
        "--conditions",
        required=True,
        help="Path to an object with a conditions array",
    )
    offline.add_argument("--output", required=True)
    live.add_argument("--approved-record", required=True)
    live.add_argument("--credential-fd", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            choices = _read_json(args.conditions)
            object_fields(choices, {"conditions"})
            request = prepare(
                args.db,
                args.owner_file,
                _read_json(args.host_plan),
                args.sku,
                choices["conditions"],
            )
            _write_private(args.output, canonical(request) + "\n")
            print(
                canonical(
                    {
                        "request_sha256": digest(request),
                        "approval_created": False,
                        "network_used": False,
                    }
                )
            )
        else:
            print(
                canonical(
                    run(
                        args.db,
                        args.owner_file,
                        _read_json(args.approved_record),
                        args.credential_fd,
                    )
                )
            )
        return 0
    except Exception:
        # Never echo file contents, provider payload, host identifiers or keys.
        print(
            "Gemini host operation blocked; no automatic retry.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
