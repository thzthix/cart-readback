"""Manually enter one ephemeral credential for an existing free-only approval."""

import argparse
import getpass
import os
import re
import signal
import stat
import sys
import tempfile
import time
import warnings
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_gemini_analysis as runner  # noqa: E402
from cartreadback_app.gemini_capacity import (  # noqa: E402
    FREE_MODE,
    MAX_INPUT_TOKENS,
    OUTPUT_TOKENS,
)
from cartreadback_app.gemini_client import CURRENT_MODEL  # noqa: E402


def _preflight(db, owner_file, record):
    request = runner.approved_request(record)
    installed = runner._installation(request)
    installed.validate(time.time())
    limits = installed.authorization
    if (
        installed.policy.admission_mode != FREE_MODE
        or limits.admission_mode != FREE_MODE
        or limits.max_calls != 1
        or limits.max_micro_usd != 0
        or installed.config.model != CURRENT_MODEL
        or installed.config.expected_model_version != CURRENT_MODEL
        or limits.max_total_input_tokens != MAX_INPUT_TOKENS
        or limits.max_total_output_tokens != OUTPUT_TOKENS
    ):
        raise runner._blocked()
    runner._existing_store(db, runner._owner(owner_file), request)


def _prompt_key() -> str:
    # Require a controlling terminal, not merely an injected stdin.isatty().
    # GetPassWarning becomes an exception BEFORE getpass's echoed fallback read.
    descriptor = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    with os.fdopen(descriptor, "w", encoding="ascii") as terminal:
        if not os.isatty(terminal.fileno()):
            raise runner._blocked()
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass("Gemini API key (hidden): ", stream=terminal)


@contextmanager
def _private_fifo(key):
    read_fd = write_fd = None
    raw = bytearray()
    try:
        if (
            type(key) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key) is None
        ):
            raise runner._blocked()
        raw.extend(key.encode("ascii"))
        with tempfile.TemporaryDirectory(prefix="gemini-manual-") as directory:
            if stat.S_IMODE(os.stat(directory).st_mode) != 0o700:
                raise runner._blocked()
            fifo = Path(directory) / "credential"
            os.mkfifo(fifo, 0o600)
            read_fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
            write_fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            for descriptor in (read_fd, write_fd):
                info = os.fstat(descriptor)
                if (
                    descriptor < 3
                    or not stat.S_ISFIFO(info.st_mode)
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_uid != os.geteuid()
                ):
                    raise runner._blocked()
                os.set_inheritable(descriptor, False)
            os.unlink(fifo)
            if os.write(write_fd, raw) != len(raw):
                raise runner._blocked()
            os.close(write_fd)
            write_fd = None
            raw[:] = b"\x00" * len(raw)
            yield read_fd
    finally:
        raw[:] = b"\x00" * len(raw)
        for descriptor in (write_fd, read_fd):
            if descriptor is not None:
                os.close(descriptor)


@contextmanager
def _interrupt_cleanup():
    previous = {}

    def interrupt(_signum, _frame):
        # A second signal must not interrupt the runner's synchronous cleanup.
        for number in previous:
            signal.signal(number, signal.SIG_IGN)
        raise KeyboardInterrupt

    try:
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[number] = signal.signal(number, interrupt)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def launch(db: str, owner_file: str, approved_record: str) -> dict:
    """Validate before prompting, then invoke the unchanged runner exactly once.

    This does not verify the external truth of the reviewed approval or free-tier
    eligibility. No credential is read from the environment, arguments or files.
    """
    key = None
    with _interrupt_cleanup():
        try:
            record = runner._read_json(approved_record)
            _preflight(db, owner_file, record)
            key = _prompt_key()
            # Recheck expiry, ownership and file identity after manual entry.
            _preflight(db, owner_file, record)
            with _private_fifo(key) as descriptor:
                key = None
                return runner.run(db, owner_file, record, descriptor)
        finally:
            # Dropping references is not guaranteed Python memory erasure.
            key = None


def main(argv: list[str] | None = None) -> int:
    """Run the manual launcher without printing exception details."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--owner-file", required=True)
    parser.add_argument("--approved-record", required=True)
    args = parser.parse_args(argv)
    try:
        result = launch(args.db, args.owner_file, args.approved_record)
        print(runner.canonical(result))
    except (Exception, KeyboardInterrupt):
        print("Gemini launch stopped; no automatic retry.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
