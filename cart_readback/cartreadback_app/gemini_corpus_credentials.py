"""Finite per-request inherited FIFOs, never ambient keys or a secret cache."""

import fcntl
import os
import re
import select
import stat
import threading

from cartreadback_app.gemini_corpus import blocked
from cartreadback_app.responses_adapter import Deadline


def _pipe_identity(descriptor):
    if type(descriptor) is not int or descriptor < 3:
        raise blocked()
    info = os.fstat(descriptor)
    if (
        not stat.S_ISFIFO(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
        or fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
    ):
        raise blocked()
    return info.st_dev, info.st_ino


class CorpusPipes:
    """Own exactly the still-eligible request descriptors for one finite grant.

    Ownership transfers on construction. Even failed validation closes valid
    descriptor numbers supplied here. Callers must not pass unrelated handles.
    Descriptor metadata is checked without reading any secret bytes.
    """

    def __init__(self, descriptors, ordinals, binding, grant_sha256):
        """Validate readable private pipes and forbid dup aliases before reserve."""
        self._descriptors = dict(descriptors)
        self._binding = binding
        self._grant = grant_sha256
        self._identities = {}
        self._used = set()
        self._lock = threading.Lock()
        self._closed = False
        try:
            if set(self._descriptors) != set(ordinals) or any(
                type(i) is not int for i in self._descriptors
            ):
                raise blocked()
            for ordinal, descriptor in self._descriptors.items():
                identity = _pipe_identity(descriptor)
                if identity in self._identities.values():
                    raise blocked()
                self._identities[ordinal] = identity
        except BaseException:
            self.close()
            raise

    def validate(self, ordinal, grant_sha256):
        """Recheck descriptor identity, privacy and unconsumed grant membership."""
        if (
            self._closed
            or grant_sha256 != self._grant
            or ordinal not in self._identities
            or ordinal in self._used
            or _pipe_identity(self._descriptors[ordinal])
            != self._identities[ordinal]
        ):
            raise blocked()

    def handle(self, ordinal, grant_sha256):
        """Select one scope-bound lazy handle, never a reusable cached key."""
        self.validate(ordinal, grant_sha256)
        return _RequestPipe(self, ordinal, grant_sha256)

    def close(self):
        """Close owned used and unused descriptors without reading unused pipes."""
        if self._closed:
            return
        self._closed = True
        for descriptor in set(self._descriptors.values()):
            if type(descriptor) is int and descriptor >= 3:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


class _RequestPipe:
    def __init__(self, owner, ordinal, grant):
        self._owner = owner
        self.ordinal = ordinal
        self.grant_sha256 = grant
        self.binding = owner._binding

    def borrow(self, *, expected_binding, deadline):
        if expected_binding != self.binding or type(deadline) is not Deadline:
            raise blocked()
        owner = self._owner
        with owner._lock:
            owner.validate(self.ordinal, self.grant_sha256)
            owner._used.add(self.ordinal)
        descriptor = owner._descriptors[self.ordinal]
        raw = bytearray()
        try:
            # A consumed request cannot reclaim capacity even if this fails.
            if _pipe_identity(descriptor) != owner._identities[self.ordinal]:
                raise blocked()
            os.set_blocking(descriptor, False)
            while True:
                readable, _, _ = select.select(
                    [descriptor], [], [], deadline.remaining()
                )
                deadline.remaining()
                if not readable:
                    raise blocked()
                try:
                    part = os.read(descriptor, 257 - len(raw))
                except BlockingIOError:
                    continue
                if not part:
                    break
                raw.extend(part)
                if len(raw) > 256:
                    raise blocked()
            value = raw.decode("ascii")
            if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value) is None:
                raise blocked()
            deadline.remaining()
            return value
        except Exception:
            raise blocked() from None
        finally:
            raw[:] = b"\x00" * len(raw)
