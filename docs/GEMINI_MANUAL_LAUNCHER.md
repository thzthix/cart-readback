# Manual private Gemini launcher (#62)

This thin POSIX terminal launcher accepts an **existing externally reviewed**
Free-only, one-call, $0 host approval. It does not create a database, owner,
project, key, binding, approval or eligibility evidence. Do not fabricate those
records to unblock a run. Existing UNKNOWN/capacity history remains authoritative.

From `cart_readback/`, manually run on the trusted host:

```sh
python scripts/launch_gemini_analysis.py --db /private/existing.sqlite3 \
  --owner-file /private/existing-owner \
  --approved-record /private/reviewed-approval.json
```

Only these nonsecret paths are arguments. Never place a key in a command, shell
history, environment variable, file, chat or approval record. The launcher checks
approval schema/hash, runtime and request identities, the existing database's
path/device/inode and internal identity, owner, revision, catalog and time window
before prompting. It additionally requires Free-only admission, exactly one call,
$0, and exact one-call input/output reservations of 1,048,576/2,048 tokens.
The model and expected version must match the runner's current reviewed model.
The unchanged runner still enforces durable reservation/claim and actual capacity
admission. A preflight pass does not guarantee dispatch or available capacity.

The hidden prompt requires `/dev/tty`; any unavailable terminal, echo-control
warning, EOF, invalid key or interrupt stops the launch. There is no stdin echo
fallback, ambient credential lookup, retry, paid fallback, browser opening or
payment action. Expiry and database identity are rechecked after manual entry.

A private mode-0700 temporary directory contains a mode-0600 named FIFO. Both
ends are opened and verified, then the name is unlinked before key bytes are
written. The writer closes before the unchanged runner receives the read
handle. This deliberately avoids relying on anonymous-pipe modes (which can
be 0660 on macOS). The secret is not stored in a regular file or inherited by a
child process. Handles and temporary paths are cleaned up on ordinary failures,
SIGINT, SIGTERM and SIGHUP. SIGKILL, host crashes, malicious same-user processes,
debuggers, swap and core dumps are not solved by this mechanism.

Python immutable strings and interpreter copies cannot be reliably erased.
Mutable staging bytes are overwritten and references dropped; this is not a
claim of complete memory erasure. Terminal input length is validated after entry,
not a claim that Python's prompt buffers at most 256 bytes.

The launcher prints the existing runner's public result envelope on return and
a fixed failure message on exceptions, never exception details or the key.
A return does not establish semantic correctness or an actual zero-charge
invoice. Do not rerun after an uncertain outcome to hide it.

Development tests use fabricated approvals and keys with socket/HTTPS calls
prohibited. They establish offline mechanics only, not real provider access,
macOS terminal behavior, external eligibility, live billing or buyer benefit.

## Preparing the existing reviewed inputs

1. Obtain the real host plan from its authorized owner, including independently
   established binding, free-tier eligibility and adopted pricing records. The
   expected version uses the reviewed stable code `gemini-3.5-flash-lite`;
   the actual returned version remains unobserved until the authorized call.
   A mismatch is handled by the existing runner as UNKNOWN without retry,
   not by adding an extra smoke call.
2. Use the existing runner's local `prepare` workflow on the same database and
   owner file with the one authorized synthetic SKU and typed conditions.
   Preparation is offline and does not create approval.
3. A real person reviews that exact nonsecret disclosure and scope. The reviewed
   record is independently created through the existing trusted-host process.
   This launcher never generates, signs, renews or approves it.
4. Only then run the command above and enter the key in the hidden terminal
   prompt. This slice does not authorize corpus/evaluation or user-data calls.

No runnable fake plan/approval is provided: fabricated records in tests are not
valid external authorization, eligibility or pricing evidence.
