"""Bounded offline count work; no provider client, credentials or live mode."""

import math
import queue
import threading
import time
from typing import Callable

from cartreadback_app.inference_budget import OfflineInputCount, request_hash
from cartreadback_app.validation import AppError

PREFLIGHT_VERSION = "offline-count-cas-v1"
PREFLIGHT_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_preflights (
    preflight_id TEXT PRIMARY KEY, sid TEXT NOT NULL,
    input_document TEXT NOT NULL, input_hash TEXT NOT NULL,
    status TEXT NOT NULL, claim_token TEXT NOT NULL DEFAULT '',
    count_document TEXT NOT NULL DEFAULT '',
    analysis_operation_id TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS single_count_preflight
ON analysis_preflights((1)) WHERE status IN ('PREPARED', 'COUNTING');
"""


def run_offline_count(
    counter: Callable[[bytes], OfflineInputCount],
    request: bytes,
    timeout: float,
) -> OfflineInputCount:
    """Bound the caller wait for one injected attempt, without retry or I/O.

    Trusted callback code is not sandboxed or forcibly cancelled. The caller must
    durably keep any timeout/error UNKNOWN; a late worker has no write callback.
    """
    if (
        not callable(counter)
        or type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 20
    ):
        raise AppError(
            "MODEL_BUDGET_EXCEEDED", "Invalid offline count settings.", 503
        )
    request_hash(request)
    deadline = time.monotonic() + timeout
    completed = queue.Queue(maxsize=1)

    def run():
        try:
            result = counter(request)
        except Exception:
            completed.put((False, None))
        else:
            completed.put((True, result))

    threading.Thread(target=run, daemon=True).start()
    try:
        success, result = completed.get(
            timeout=max(0, deadline - time.monotonic())
        )
    except queue.Empty:
        raise AppError(
            "MODEL_TIMEOUT", "Offline count deadline exceeded.", 503
        ) from None
    if time.monotonic() >= deadline:
        raise AppError("MODEL_TIMEOUT", "Offline count deadline exceeded.", 503)
    if not success or type(result) is not OfflineInputCount:
        raise AppError(
            "MODEL_BUDGET_EXCEEDED", "Offline count unavailable.", 503
        )
    return result
