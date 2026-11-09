"""Unselected, authenticated GitHub reads, not admission or host attestation.

Only a separately trusted host may supply enrollment and an ephemeral credential
handle. No selector, credential loader, durable retirement or consent is shipped.
Private transport/clock names are test seams, not supported caller parameters.
"""

import http.client
import ipaddress
import json
import math
import queue
import re
import socket
import ssl
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

_HOST = "api.github.com"
_REPOSITORY = "thzthix/cart-readback"
_BASE = "/repos/" + _REPOSITORY + "/actions"
_MAX_BODY = 262_144
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_TOKEN = re.compile(r"[A-Za-z0-9_]{1,4096}")
_DNS_SLOT = threading.BoundedSemaphore(1)
_wall_clock = time.time
_monotonic = time.monotonic


class MetadataUnavailable(Exception):
    """A constant sanitized failure, never a raw transport/API error."""

    def __init__(self) -> None:
        """Retain no remote, credential or callback details."""
        super().__init__("GitHub run metadata unavailable; no retry.")


def _require(condition: bool) -> None:
    if not condition:
        raise MetadataUnavailable()


def _positive_id(value: object) -> bool:
    return type(value) is int and 0 < value <= 2**63 - 1


def _direct_cancellation(error):
    return isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit))


@dataclass(frozen=True)
class RunEnrollment:
    """Externally enrolled identity/window; constructing it grants no authority."""

    repository_id: int
    workflow_id: int
    actor_id: int
    workflow_path: str
    reviewed_sha: str
    not_before: int
    expires_at: int
    ref: str = "refs/heads/main"

    def __post_init__(self) -> None:
        """Reject unsupported identities and relative/renewable windows."""
        _require(
            all(
                _positive_id(value)
                for value in (
                    self.repository_id,
                    self.workflow_id,
                    self.actor_id,
                    self.not_before,
                    self.expires_at,
                )
            )
            and 0 < self.expires_at - self.not_before <= 86_400
            and type(self.ref) is str
            and self.ref == "refs/heads/main"
            and type(self.workflow_path) is str
            and re.fullmatch(
                r"\.github/workflows/[a-zA-Z0-9_-]{1,100}\.ya?ml",
                self.workflow_path,
            )
            is not None
            and type(self.reviewed_sha) is str
            and re.fullmatch(r"[0-9a-f]{40}", self.reviewed_sha) is not None
        )


@dataclass(frozen=True)
class GitHubRunMetadata:
    """A narrow queried-run observation, not fabricated evidence or a grant."""

    repository_id: int
    workflow_id: int
    actor_id: int
    workflow_path: str
    ref: str
    head_sha: str
    run_id: int
    created_at: int
    started_at: int
    updated_at: int


class _Deadline:
    def __init__(self, enrollment):
        self.enrollment = enrollment
        self.start_wall = _wall_clock()
        self.start_mono = _monotonic()
        self.last_wall = self.start_wall
        self.last_mono = self.start_mono
        self.end = self.start_mono + 20
        self.check()

    def check(self):
        wall, mono = _wall_clock(), _monotonic()
        _require(
            type(wall) in (int, float)
            and type(mono) in (int, float)
            and math.isfinite(wall)
            and math.isfinite(mono)
            and wall >= self.last_wall
            and mono >= self.last_mono
            and self.enrollment.not_before <= wall < self.enrollment.expires_at
            and mono < self.end
        )
        self.last_wall, self.last_mono = wall, mono
        return min(self.end - mono, self.enrollment.expires_at - wall)

    def timeout(self, maximum=5):
        return min(maximum, self.check())


def _resolve(deadline):
    # Platform DNS cannot be force-cancelled in Python. At most one resolver-only
    # daemon can outlive a caller; it never receives a credential/socket/context.
    # While it remains stuck, future production DNS attempts fail closed.
    _require(_DNS_SLOT.acquire(blocking=False))
    completed = queue.Queue(maxsize=1)

    def resolve():
        try:
            result = socket.getaddrinfo(
                _HOST, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
            )
            completed.put((True, result))
        except BaseException:
            completed.put((False, None))
        finally:
            _DNS_SLOT.release()

    try:
        worker = threading.Thread(target=resolve, daemon=True)
        worker.start()
    except BaseException:
        _DNS_SLOT.release()
        raise
    success, records = completed.get(timeout=deadline.timeout(3))
    deadline.check()
    _require(success and type(records) is list and 1 <= len(records) <= 16)
    family, kind, protocol, _, address = records[0]
    _require(
        family in (socket.AF_INET, socket.AF_INET6)
        and kind == socket.SOCK_STREAM
        and protocol == socket.IPPROTO_TCP
        and type(address) is tuple
        and len(address) == (2 if family == socket.AF_INET else 4)
        and address[1] == 443
        and ipaddress.ip_address(address[0]).version
        == (4 if family == socket.AF_INET else 6)
    )
    return family, kind, protocol, address


class _GitHubConnection(http.client.HTTPSConnection):
    def __init__(self, deadline, context):
        super().__init__(
            _HOST, 443, timeout=deadline.timeout(3), context=context
        )
        self._deadline = deadline

    def connect(self):
        # One DNS lookup, one selected address, one connect; no fallback/retry.
        family, kind, protocol, address = _resolve(self._deadline)
        raw = socket.socket(family, kind, protocol)
        try:
            raw.settimeout(self._deadline.timeout(3))
            raw.connect(address)
            raw.settimeout(self._deadline.timeout(3))
            self.sock = self._context.wrap_socket(raw, server_hostname=_HOST)
            self._deadline.check()
        except BaseException as primary:
            try:
                raw.close()
            except BaseException as cleanup:
                if _direct_cancellation(cleanup) and not _direct_cancellation(
                    primary
                ):
                    raise
            raise


def _connection(deadline, context):
    return _GitHubConnection(deadline, context)


class _Reader:
    def __init__(self, reader, guard):
        self.reader, self.guard = reader, guard
        self.pending = bytearray()
        self.phase, self.header_count, self.header_size = 0, 0, 0

    def __getattr__(self, name):
        return getattr(self.reader, name)

    def read1(self, amount):
        self.guard()
        if self.pending:
            chunk = bytes(self.pending[:amount])
            del self.pending[:amount]
            return chunk
        return self.reader.read1(min(amount, 8192))

    def read(self, amount):
        _require(type(amount) is int and 0 <= amount <= _MAX_BODY)
        raw = bytearray()
        while len(raw) < amount:
            chunk = self.read1(amount - len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        return bytes(raw)

    def readline(self, limit=-1):
        _require(type(limit) is int and 0 < limit <= 65_537)
        limit = min(limit, 4356)
        raw = bytearray()
        while len(raw) < limit:
            chunk = self.read1(limit - len(raw))
            if not chunk:
                break
            newline = chunk.find(b"\n")
            if newline >= 0:
                raw.extend(chunk[: newline + 1])
                self.pending[:0] = chunk[newline + 1 :]
                break
            raw.extend(chunk)
        line = bytes(raw)
        if self.phase == 0:
            self.phase = 1
        elif self.phase == 1:
            self.header_size += len(line)
            _require(self.header_size <= 16_384 and line.endswith(b"\r\n"))
            if line == b"\r\n":
                self.phase = 2
            else:
                self.header_count += 1
                _require(self.header_count <= 64 and b":" in line)
                name, value = line[:-2].split(b":", 1)
                _require(
                    1 <= len(name) <= 256
                    and _HEADER_NAME.fullmatch(name.decode("ascii")) is not None
                    and len(value) <= 4096
                    and all(32 <= char <= 126 for char in value)
                )
        return line


class _StrictResponse(http.client.HTTPResponse):
    def _read_status(self):
        line = self.fp.readline(1100)
        _require(
            re.fullmatch(rb"HTTP/1\.1 200 [\x20-\x7e]{0,1024}\r\n", line)
            is not None
        )
        return "HTTP/1.1", 200, "OK"

    def _read_next_chunk_size(self):
        line = self.fp.readline(12)
        _require(re.fullmatch(rb"(?:0|[1-9a-fA-F][0-9a-fA-F]{0,5})\r\n", line))
        size = int(line[:-2], 16)
        _require(size <= _MAX_BODY)
        return size

    def _get_chunk_left(self):
        left = self.chunk_left
        if left is None or left == 0:
            if left == 0:
                _require(self._safe_read(2) == b"\r\n")
            left = self._read_next_chunk_size()
            if left == 0:
                _require(self._safe_read(2) == b"\r\n")
                self._close_conn()
                left = None
            self.chunk_left = left
        return left


def _headers(response):
    raw = response.getheaders()
    _require(type(raw) is list and len(raw) <= 64)
    size, headers = 0, {}
    for name, value in raw:
        _require(
            type(name) is str
            and type(value) is str
            and 1 <= len(name) <= 256
            and len(value) <= 4096
            and _HEADER_NAME.fullmatch(name) is not None
            and all(32 <= ord(char) <= 126 for char in value)
        )
        size += len(name) + len(value)
        lower = name.lower()
        _require(size <= 16_384 and lower not in headers)
        headers[lower] = value
    _require("link" not in headers and "location" not in headers)
    _require(
        re.fullmatch(
            r"application/(?:json|vnd\.github\+json)(?:; charset=utf-8)?",
            headers.get("content-type", "").lower(),
        )
        is not None
        and headers.get("content-encoding", "identity").lower() == "identity"
    )
    length, transfer = (
        headers.get("content-length"),
        headers.get("transfer-encoding"),
    )
    _require((length is None) != (transfer is None))
    if transfer is not None:
        _require(transfer.lower() == "chunked" and response.chunked)
        return None
    _require(re.fullmatch(r"[1-9][0-9]{0,5}", length) is not None)
    _require(int(length) <= _MAX_BODY and not response.chunked)
    return int(length)


def _json(raw):
    # Bound nesting before json.loads, including ignored upstream fields.
    text = raw.decode("utf-8", errors="strict")
    depth, string, escaped = 0, False, False
    for char in text:
        if string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                string = False
        elif char == '"':
            string = True
        elif char in "[{":
            depth += 1
            _require(depth <= 12)
        elif char in "]}":
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result)
            result[key] = value
        return result

    def constant(_):
        raise MetadataUnavailable()

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    _require(type(value) is dict)
    return value


def _timestamp(value):
    _require(
        type(value) is str
        and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z", value)
        is not None
    )
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _project(run, enrolled, run_id, now):
    _require(type(run) is dict)
    for key in ("id", "workflow_id", "run_number", "run_attempt"):
        _require(_positive_id(run.get(key)))
    _require(
        run["id"] == run_id
        and run["workflow_id"] == enrolled.workflow_id
        and run["run_number"] == run["run_attempt"] == 1
        and run.get("path") == enrolled.workflow_path + "@main"
        and run.get("head_branch") == "main"
        and run.get("head_sha") == enrolled.reviewed_sha
        and run.get("event") == "workflow_dispatch"
        and run.get("status") == "in_progress"
        and "conclusion" in run
        and run["conclusion"] is None
        and run.get("pull_requests") == []
        and run.get("url") == f"https://{_HOST}{_BASE}/runs/{run_id}"
        and run.get("workflow_url")
        == f"https://{_HOST}{_BASE}/workflows/{enrolled.workflow_id}"
    )
    for key in ("repository", "head_repository"):
        repository = run.get(key)
        _require(
            type(repository) is dict
            and _positive_id(repository.get("id"))
            and repository["id"] == enrolled.repository_id
            and repository.get("full_name") == _REPOSITORY
            and repository.get("fork") is False
        )
    for key in ("actor", "triggering_actor"):
        actor = run.get(key)
        _require(
            type(actor) is dict
            and _positive_id(actor.get("id"))
            and actor["id"] == enrolled.actor_id
        )
    created, started, updated = (
        _timestamp(run.get(key))
        for key in ("created_at", "run_started_at", "updated_at")
    )
    _require(enrolled.not_before <= created <= started <= updated <= now)
    return GitHubRunMetadata(
        enrolled.repository_id,
        enrolled.workflow_id,
        enrolled.actor_id,
        enrolled.workflow_path,
        enrolled.ref,
        enrolled.reviewed_sha,
        run_id,
        created,
        started,
        updated,
    )


class GitHubRunMetadataReader:
    """One unselected three-GET observation using an explicit credential handle.

    The handle must be trusted nonblocking host code returning an ephemeral token.
    It is called once per request after TLS, and must not refresh or persist it.
    Private test seams and a compromised Python host can fabricate observations;
    neither this class nor its result attests the caller's job or owner consent.
    """

    def __init__(
        self,
        enrollment: RunEnrollment,
        credential_handle: Callable[[], str],
    ) -> None:
        """Retain explicit host inputs without resolving credentials/network."""
        _require(
            type(enrollment) is RunEnrollment and callable(credential_handle)
        )
        self._enrollment = enrollment
        self._credential = credential_handle
        self._lock = threading.Lock()
        self._used = False

    def read(self, run_id: int) -> GitHubRunMetadata:
        """Consume this reader once; return strict authenticated metadata only."""
        _require(_positive_id(run_id))
        with self._lock:
            _require(not self._used)
            self._used = True
        try:
            enrolled = self._enrollment
            deadline = _Deadline(enrolled)
            run = self._get(f"{_BASE}/runs/{run_id}", deadline)
            observation = _project(run, enrolled, run_id, _wall_clock())
            workflow = self._get(
                f"{_BASE}/workflows/{enrolled.workflow_id}", deadline
            )
            _require(
                _positive_id(workflow.get("id"))
                and workflow["id"] == enrolled.workflow_id
                and workflow.get("path") == enrolled.workflow_path
                and workflow.get("state") == "active"
                and workflow.get("url")
                == f"https://{_HOST}{_BASE}/workflows/{enrolled.workflow_id}"
            )
            history = self._get(
                f"{_BASE}/workflows/{enrolled.workflow_id}/runs"
                "?per_page=100&page=1",
                deadline,
            )
            _require(
                type(history.get("total_count")) is int
                and history["total_count"] == 1
                and type(history.get("workflow_runs")) is list
                and len(history["workflow_runs"]) == 1
            )
            historical = _project(
                history["workflow_runs"][0], enrolled, run_id, _wall_clock()
            )
            _require(observation == historical)
            deadline.check()
            return observation
        except KeyboardInterrupt:
            raise KeyboardInterrupt() from None
        except SystemExit:
            raise SystemExit(1) from None
        except GeneratorExit:
            raise GeneratorExit() from None
        except BaseException:
            # Groups/unexpected host exceptions are unavailable, never evidence.
            # Do not re-emit arbitrary callback/socket/cleanup exception payloads.
            raise MetadataUnavailable() from None

    def _get(self, path, deadline):
        connection = response = established = None
        headers, token = {}, None

        def guard():
            _require(established is not None)
            established.settimeout(deadline.timeout())

        try:
            deadline.check()
            # create_default_context may create SSLKEYLOGFILE before resetting it.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_default_certs(ssl.Purpose.SERVER_AUTH)
            context.keylog_filename = None
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(["http/1.1"])
            deadline.check()
            connection = _connection(deadline, context)
            connection.set_debuglevel(0)
            connection.auto_open = 0

            class GuardedResponse(_StrictResponse):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.fp = _Reader(self.fp, guard)

            connection.response_class = GuardedResponse
            connection.connect()
            established = connection.sock
            guard()
            token = self._credential()
            _require(type(token) is str and _TOKEN.fullmatch(token) is not None)
            headers = {
                "Host": _HOST,
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
                "Accept-Encoding": "identity",
                "User-Agent": "CartReadback-run-metadata-v1",
                "Connection": "close",
            }
            guard()
            try:
                connection.request("GET", path, body=None, headers=headers)
            finally:
                token = None
                headers.clear()
            guard()
            response = connection.getresponse()
            deadline.check()
            _require(
                type(response) is GuardedResponse
                and response.status == 200
                and response.version == 11
            )
            expected = _headers(response)
            raw = bytearray()
            while not response.isclosed():
                guard()
                amount = min(8192, _MAX_BODY - len(raw) + 1)
                chunk = response.read1(amount)
                deadline.check()
                _require(type(chunk) is bytes and len(chunk) <= amount)
                if not chunk:
                    break
                raw.extend(chunk)
                _require(len(raw) <= _MAX_BODY)
            _require(expected is None or len(raw) == expected)
            deadline.check()
            result = _json(bytes(raw))
            deadline.check()
            return result
        finally:
            token = None
            headers.clear()
            primary = sys.exc_info()[1]
            cleanup_fault = None
            cleanup_cancellation = None
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except BaseException as error:
                        if cleanup_fault is None:
                            cleanup_fault = error
                        if (
                            cleanup_cancellation is None
                            and _direct_cancellation(error)
                        ):
                            cleanup_cancellation = error
            if cleanup_cancellation is not None and not _direct_cancellation(
                primary
            ):
                # Preserve cancellation over an ordinary primary/cleanup error.
                # Public read normalizes its type and removes arbitrary payloads.
                raise cleanup_cancellation
            if primary is None and cleanup_fault is not None:
                raise MetadataUnavailable() from None
