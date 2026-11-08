"""Prepare, explicitly run, or credential-free re-export a finite corpus.

No default model execution. Run needs a distinct reviewed corpus record and
one private inherited FIFO per still-eligible request. External authorization
and account-specific Free/no-paid-billing evidence are not supplied by files.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cartreadback_app.gemini_corpus import (  # noqa: E402
    MAX_CORPUS_BYTES,
    REQUEST_SCHEMA,
    CorpusGeminiAdapter,
    CorpusRuntime,
    approved_request,
    blocked,
    corpus_execution_identity,
    owned_json,
    parse_corpus,
    plan_parts,
)
from cartreadback_app.gemini_corpus_credentials import (  # noqa: E402
    CorpusPipes,
    OwnedDescriptors,
)
from cartreadback_app.gemini_corpus_ledger import (  # noqa: E402
    ExistingCorpusStore,
    activate,
    attach_result,
    commit_observation,
    completion_state,
    database_file_identity,
    expire_incomplete,
    freeze,
    history_snapshot,
    invalidated,
    ledger_for,
    paired_rows,
    prepare_database,
    prior_totals,
    read_frozen,
    recover,
    seal_completion,
    stage_observation,
)
from cartreadback_app.genuine_responses import GenuineExchange  # noqa: E402
from cartreadback_app.validation import (  # noqa: E402
    canonical,
    digest,
    text_hash,
    token,
)


def _read(path, maximum):
    with Path(path).open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise blocked()
    return raw


def publish(raw: bytes, destination) -> None:
    """Fsync complete private bytes, then atomically publish without clobbering.

    A failed link/fsync never grants execution. Existing files, including partial
    old artifacts, are preserved. Re-export can use a fresh destination.
    """
    target = Path(destination)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".corpus-export-", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def prepare(db, owner, raw, plan, *, transport=None):
    """Prepare concrete disclosure offline in the same existing DB and owner."""
    token(owner)
    plan = owned_json(canonical(plan).encode())
    _, config, _, selected = plan_parts(plan, transport)
    corpus = parse_corpus(raw, config)
    store = ExistingCorpusStore(db)
    lease = store.acquire_service()
    try:
        with store.transaction() as connection:
            database_id = prepare_database(connection, owner)
            request = {
                "schema": REQUEST_SCHEMA,
                "plan": plan,
                "corpus_sha256": corpus.sha256,
                "corpus": json.loads(corpus.document_json),
                "mapping": corpus.mapping,
                "mapping_sha256": digest(corpus.mapping),
                "runtime_sha256": corpus_execution_identity(plan, selected),
                "database_id": database_id,
                "database_file_sha256": database_file_identity(db),
                "owner_sha256": text_hash(owner),
                "baseline_sha256": history_snapshot(connection),
                "prior_totals": list(prior_totals(connection)),
                "evidence_kind": selected.metadata["kind"],
            }
            # Scalar checks do not activate the grant or manufacture approval.
            CorpusRuntime(canonical(request), "0" * 64, selected).authorization
            return request
    finally:
        lease.close()


def _runtime(record, raw, owner, transport):
    request = approved_request(record)
    _, config, _, selected = plan_parts(request["plan"], transport)
    corpus = parse_corpus(raw, config)
    if (
        text_hash(owner) != request["owner_sha256"]
        or corpus.sha256 != request["corpus_sha256"]
        or corpus.document_json != canonical(request["corpus"])
        or corpus.mapping_json != canonical(request["mapping"])
        or digest(corpus.mapping) != request["mapping_sha256"]
    ):
        raise blocked()
    return CorpusRuntime(canonical(request), digest(record), selected)


def _claim_guard(
    store, runtime, ordinal, claim, endpoint, body, deadline, clock
):
    runtime.exact_case(ordinal, body=body)
    expected = CorpusGeminiAdapter(runtime, clock)
    case, _ = runtime.exact_case(ordinal)
    prepared = expected.prepare(case["source"], case["conditions"])
    if (
        endpoint
        != f"https://generativelanguage.googleapis.com/v1beta/models/{runtime.config.model}:generateContent"
        or body != prepared.request
    ):
        raise blocked()
    deadline.remaining()
    with store.transaction() as connection:
        ledger = ledger_for(connection, runtime, clock())
        rows = paired_rows(connection, runtime)
        if rows[ordinal][
            "operation_id"
        ] != claim.reservation.operation_id or not ledger.validate_claim(
            claim, body, runtime.fence(ordinal), now=clock()
        ):
            raise blocked()


def _execute(store, runtime, ordinal, pipes, clock):
    handle = pipes.handle(ordinal, runtime.record_sha256)
    selected = replace(runtime, credential_handle=handle, ordinal=ordinal)
    adapter = CorpusGeminiAdapter(selected, clock)
    case, _ = selected.exact_case(ordinal)
    prepared = adapter.prepare(case["source"], case["conditions"])
    # Reserve and map in one transaction. No pipe read or network before claim.
    with store.transaction() as connection:
        ledger = ledger_for(connection, selected, clock())
        rows = paired_rows(connection, selected)
        if rows[ordinal]["operation_id"] is not None or any(
            row["status"] != "KNOWN" for row in rows[:ordinal]
        ):
            raise blocked()
        pipes.validate(ordinal, runtime.record_sha256)
        reservation = ledger.reserve(
            prepared.request, selected.fence(ordinal), now=clock()
        )
        connection.execute(
            "UPDATE gemini_corpus_requests SET operation_id=? WHERE ordinal=? AND operation_id IS NULL",
            (reservation.operation_id, ordinal),
        )
    try:
        with store.transaction() as connection:
            ledger = ledger_for(connection, selected, clock())
            paired_rows(connection, selected)
            claim = ledger.claim(
                reservation,
                prepared.request,
                selected.fence(ordinal),
                now=clock(),
            )
        if claim is None:
            raise blocked()
        deadline = adapter.deadline(claim)

        def guard(*, endpoint, body, deadline):
            return _claim_guard(
                store, selected, ordinal, claim, endpoint, body, deadline, clock
            )

        exchange = adapter.exchange(
            prepared, claim, deadline, claim_guard=guard
        )
        if (
            type(exchange) is not GenuineExchange
            or exchange.operation_id != reservation.operation_id
            or exchange.claim_token != claim.claim_token
            or exchange.request_sha256 != prepared.request_sha256
            or exchange.runtime_sha256 != prepared.runtime_sha256
            or exchange.evidence_kind != selected.evidence_kind
        ):
            raise blocked()
        fault, code, results = adapter.classify(
            exchange, selected.policy, prepared
        )
        deadline.remaining()

        def observe(connection):
            # BEGIN IMMEDIATE may have waited. The 20-second capacity claim
            # does not replace this request's shorter monotonic deadline.
            deadline.remaining()
            ledger = ledger_for(connection, selected, clock())
            paired_rows(connection, selected)
            current_fence = selected.fence(ordinal)
            deadline.remaining()
            state = ledger.observe(
                claim,
                exchange.envelope,
                request_sha256=exchange.request_sha256,
                runtime_sha256=exchange.runtime_sha256,
                request_id=exchange.request_id,
                current_fence=current_fence,
                now=clock(),
            )
            deadline.remaining()
            if fault and state == "KNOWN":
                raise blocked()
            attach_result(
                connection,
                selected,
                ordinal,
                reservation.operation_id,
                state,
                "MODEL_OUTCOME_UNKNOWN" if state == "UNKNOWN" else code,
                results if state == "KNOWN" and not code else None,
            )
            stage_observation(connection, selected, ordinal)
            # Late local validation/attachment rolls this transaction back;
            # the original reservation is then durably marked UNKNOWN.
            deadline.remaining()
            return state

        state, disposition = commit_observation(store, deadline, observe)
    except Exception:
        # No retry. Read durable state after an ambiguous commit; never rewrite
        # KNOWN accounting or immutable candidate bytes as UNKNOWN.
        with store.transaction() as connection:
            rows = paired_rows(connection, selected)
            row = rows[ordinal]
            receipts, _, missing = completion_state(
                connection, selected.record_sha256, selected.request
            )
            if ordinal in missing:
                seal_completion(connection, selected, ordinal, "UNCONFIRMED")
                return "INVALIDATED"
            if ordinal in receipts:
                raise blocked()
            ledger = ledger_for(connection, selected, clock(), fresh=False)
            ledger.mark_unknown(reservation)
            if not row["result"]:
                attach_result(
                    connection,
                    selected,
                    ordinal,
                    reservation.operation_id,
                    "UNKNOWN",
                    "MODEL_OUTCOME_UNKNOWN",
                )
        return "UNKNOWN"
    # A durable receipt records the already measured COMMIT return. Its own
    # persistence may finish later, but no next provider request starts first.
    # Crashing here leaves a provisional marker, recovered as UNCONFIRMED.
    with store.transaction() as connection:
        seal_completion(connection, selected, ordinal, disposition)
    return state if disposition == "TIMELY" else "INVALIDATED"


def run(
    db, owner, raw, record, descriptors, *, transport=None, clock=time.time
):
    """Execute a sequential known prefix once; freeze before exporting/scoring."""
    owned = OwnedDescriptors(descriptors)
    pipes = lease = None
    try:
        record = owned_json(canonical(record).encode())
        runtime = _runtime(record, raw, owner, transport)
        store = ExistingCorpusStore(db, runtime.request["database_file_sha256"])
        lease = store.acquire_service()
        # Recovery commits independently of fresh admission. Expiry/code drift
        # cannot roll a crashed claim back into a sendable request.
        with store.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='gemini_corpus_identity'"
            ).fetchone():
                existing = connection.execute(
                    "SELECT document,frozen FROM gemini_corpus_identity WHERE singleton=1"
                ).fetchone()
                if existing is not None:
                    if (
                        text_hash(existing["document"]) != runtime.record_sha256
                        or existing["frozen"]
                    ):
                        raise blocked()
                    recover(connection, runtime)
                    expire_incomplete(connection, runtime, clock())
                    rows = paired_rows(connection, runtime)
                    if (
                        invalidated(connection, runtime)
                        or any(row["status"] == "UNKNOWN" for row in rows)
                        or all(row["status"] == "KNOWN" for row in rows)
                    ):
                        return freeze(connection, runtime)
        with store.transaction() as connection:
            activate(connection, record, runtime, clock())
            # Frozen runs are never executable, even after an export failure.
            if connection.execute(
                "SELECT frozen FROM gemini_corpus_identity WHERE singleton=1"
            ).fetchone()[0]:
                raise blocked()
            recover(connection, runtime)
            rows = paired_rows(connection, runtime)
            if invalidated(connection, runtime) or any(
                row["status"] == "UNKNOWN" for row in rows
            ):
                return freeze(connection, runtime)
            eligible = [
                row["ordinal"] for row in rows if row["operation_id"] is None
            ]
        pipes = CorpusPipes(
            owned, eligible, runtime.binding, runtime.record_sha256
        )
        for ordinal in eligible:
            try:
                state = _execute(store, runtime, ordinal, pipes, clock)
            except Exception:
                # Expiry after a durable timely prefix is terminal, not a new
                # admission. The same lease/identity remains held throughout.
                with store.transaction() as connection:
                    if expire_incomplete(connection, runtime, clock()):
                        return freeze(connection, runtime)
                raise
            if state != "KNOWN":
                break
        with store.transaction() as connection:
            return freeze(connection, runtime)
    finally:
        try:
            if pipes is not None:
                pipes.close()
        finally:
            try:
                # Constructor failure may already have consumed this owner.
                # Never close the original integer list a second time.
                owned.close()
            finally:
                if lease is not None:
                    lease.close()


def main(argv=None):
    """Keep prepare/run/export distinct; no mode infers permission from a key."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    offline = commands.add_parser("prepare")
    live = commands.add_parser("run")
    export = commands.add_parser("export")
    audit = commands.add_parser("export-audit")
    for command in (offline, live, export, audit):
        command.add_argument("--db", required=True)
        command.add_argument("--output", required=True)
    for command in (offline, live):
        command.add_argument("--owner-file", required=True)
        command.add_argument("--corpus", required=True)
    offline.add_argument("--host-plan", required=True)
    live.add_argument("--approved-record", required=True)
    live.add_argument(
        "--credential-fd", action="append", default=[], metavar="ORDINAL:FD"
    )
    args = parser.parse_args(argv)
    try:
        if args.command in ("export", "export-audit"):
            result = read_frozen(
                args.db, audit_only=args.command == "export-audit"
            )
        else:
            owner = token(_read(args.owner_file, 100).decode("ascii"))
            raw = _read(args.corpus, MAX_CORPUS_BYTES)
            if args.command == "prepare":
                result = (
                    canonical(
                        prepare(
                            args.db,
                            owner,
                            raw,
                            owned_json(_read(args.host_plan, 131072)),
                        )
                    )
                    + "\n"
                ).encode()
            else:
                pairs = [item.split(":") for item in args.credential_fd]
                descriptors = {int(ordinal): int(fd) for ordinal, fd in pairs}
                if len(descriptors) != len(pairs):
                    raise blocked()
                result = run(
                    args.db,
                    owner,
                    raw,
                    owned_json(_read(args.approved_record, MAX_CORPUS_BYTES)),
                    descriptors,
                )
        if args.command == "run":
            # Invalidated runs are persisted but require explicit audit export.
            result = read_frozen(args.db)
        publish(result, args.output)
        print(
            canonical(
                {
                    "artifact_sha256": text_hash(result.decode()),
                    "approval_created": False,
                }
            )
        )
        return 0
    except Exception:
        print(
            "Finite corpus operation blocked; no automatic retry.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
