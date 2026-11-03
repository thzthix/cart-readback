"""SQLite persistence with serialized local transitions and durable audit data."""

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from cartreadback_app.catalog import fixtures, validate_product
from cartreadback_app.inference_budget import BUDGET_SCHEMA
from cartreadback_app.validation import AppError, canonical, text_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog (sku TEXT PRIMARY KEY, document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    sid TEXT PRIMARY KEY, csrf TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
    checkout TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY, sid TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
    document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS confirmations (
    confirmation_id TEXT PRIMARY KEY, sid TEXT NOT NULL, review_id TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL, document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, sid TEXT NOT NULL, review_id TEXT UNIQUE NOT NULL,
    snapshot_hash TEXT NOT NULL, provider_order_id TEXT,
    status TEXT NOT NULL, expected TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY, sid TEXT NOT NULL, kind TEXT NOT NULL,
    idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
    order_id TEXT NOT NULL, status TEXT NOT NULL,
    upstream_payload TEXT NOT NULL DEFAULT '',
    upstream_hash TEXT NOT NULL DEFAULT '',
    UNIQUE(sid, kind, idempotency_key), UNIQUE(order_id, kind)
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_provider_order
ON orders(provider_order_id) WHERE provider_order_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS fixture_provider_orders (
    provider_order_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
    document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_operations (
    operation_id TEXT PRIMARY KEY, sid TEXT NOT NULL, review_id TEXT NOT NULL,
    input_document TEXT NOT NULL, input_hash TEXT NOT NULL,
    checkout_hash TEXT NOT NULL,
    reserved_revision INTEGER NOT NULL, is_fixture INTEGER NOT NULL,
    status TEXT NOT NULL, dispatch_token TEXT NOT NULL DEFAULT '',
    reserved_at TEXT NOT NULL, dispatched_at TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL DEFAULT '', observation TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS single_accounted_analysis
ON analysis_operations(is_fixture)
WHERE is_fixture = 0 AND status IN ('RESERVED', 'DISPATCHED');
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY, sid TEXT NOT NULL, event TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


class Store:
    """Own connections; BEGIN IMMEDIATE makes concurrent transitions exclusive."""

    def __init__(self, path: str | Path):
        """Create a local fixture database and seed only on first initialization."""
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA + BUDGET_SCHEMA)
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(operations)")
            }
            additions = {
                name: "TEXT NOT NULL DEFAULT ''"
                for name in (
                    "upstream_payload",
                    "upstream_hash",
                    "method",
                    "path",
                    "expected_hash",
                    "provider_mode",
                    "merchant_id",
                    "adapter_version",
                    "dispatch_token",
                    "reserved_at",
                    "dispatched_at",
                    "observed_at",
                    "last_observation",
                    "error_code",
                )
            }
            additions["reserved_revision"] = "INTEGER NOT NULL DEFAULT -1"
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE operations ADD COLUMN {name} {definition}"
                    )
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute(
                "SELECT 1 FROM catalog LIMIT 1"
            ).fetchone():
                products = fixtures()
                if len({item["sku_id"] for item in products}) != len(products):
                    raise AppError("INVALID_CATALOG", "Duplicate server SKU.")
                for product in products:
                    validate_product(product)
                    connection.execute(
                        "INSERT INTO catalog VALUES (?, ?)",
                        (product["sku_id"], canonical(product)),
                    )
            connection.commit()

    def acquire_service(self) -> BinaryIO:
        """Reject another service for this DB before startup recovery.

        The OS releases the advisory lock after process death. The lock file is
        never removed: unlinking a held lock would permit a second lock inode.
        All supported service instances must use this guard and one DB path.
        """
        handle = self.path.with_suffix(self.path.suffix + ".service-lock").open(
            "a+b"
        )
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError) as error:
            handle.close()
            raise AppError(
                "SERVICE_ALREADY_RUNNING",
                "Use one service instance for this database.",
                409,
            ) from error
        return handle

    def connect(self) -> sqlite3.Connection:
        """Return a fresh connection with an explicit bounded lock wait."""
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit a complete local transition or roll back every local write."""
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def session(self, candidate: str | None) -> tuple[dict, bool]:
        """Resolve an existing random owner cookie or create a new session."""
        with self.transaction() as connection:
            if candidate:
                row = connection.execute(
                    "SELECT * FROM sessions WHERE sid = ?",
                    (candidate,),
                ).fetchone()
                if row:
                    session = dict(row)
                    expected_csrf_hash = text_hash(csrf_for(candidate))
                    if session["csrf"] != expected_csrf_hash:
                        connection.execute(
                            "UPDATE sessions SET csrf = ? WHERE sid = ?",
                            (expected_csrf_hash, candidate),
                        )
                        session["csrf"] = expected_csrf_hash
                    return session, False
            sid = secrets.token_urlsafe(32)
            csrf = text_hash(csrf_for(sid))
            connection.execute(
                "INSERT INTO sessions(sid, csrf) VALUES (?, ?)",
                (sid, csrf),
            )
            return {
                "sid": sid,
                "csrf": csrf,
                "revision": 0,
                "checkout": None,
            }, True

    def replace_product(self, product: dict) -> None:
        """Test/admin seam only; there is no HTTP catalog-mutation endpoint."""
        validate_product(product)
        with self.transaction() as connection:
            if not connection.execute(
                "SELECT 1 FROM catalog WHERE sku = ?",
                (product["sku_id"],),
            ).fetchone():
                raise AppError("UNKNOWN_SKU", "Unknown catalog SKU.")
            connection.execute(
                "UPDATE catalog SET document = ? WHERE sku = ?",
                (canonical(product), product["sku_id"]),
            )


def product_for(connection: sqlite3.Connection, sku: str) -> dict:
    """Read and validate authoritative catalog fields on every use."""
    row = connection.execute(
        "SELECT document FROM catalog WHERE sku = ?",
        (sku,),
    ).fetchone()
    if not row:
        raise AppError("UNKNOWN_SKU", "Unknown catalog SKU.", 404)
    product = json.loads(row[0])
    validate_product(product)
    return product


def event(
    connection: sqlite3.Connection, sid: str, name: str, details: dict
) -> None:
    """Append a bounded domain event, without headers, cookies or credentials."""
    connection.execute(
        "INSERT INTO events(sid, event, details) VALUES (?, ?, ?)",
        (sid, name, canonical(details)),
    )


def csrf_for(sid: str) -> str:
    """Derive a CSRF token from the unpredictable HttpOnly owner credential.

    Only its hash is persisted. The browser obtains it from same-origin
    bootstrap, never from a URL or a readable cookie.
    """
    return text_hash("cartreadback-local-csrf-v1:" + sid)
