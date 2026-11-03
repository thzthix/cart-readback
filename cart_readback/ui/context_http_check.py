"""Run C12 client checks over loopback with fabricated host/HTTPS exchanges.

No browser rendering, provider network, real credentials or billing is tested.
Run separately from the unchanged fixture runner: python ui/context_http_check.py.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
SCENARIOS = ("unavailable", "known", "semantic", "protocol")


def main() -> None:
    """Exercise actual HTTP/client validation while denying provider sockets."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    fixtures = import_module("test_context_service")
    local_server = import_module("cartreadback_app.http").LocalServer
    service_type = import_module("cartreadback_app.service").Service
    store_type = import_module("cartreadback_app.storage").Store
    runtime_type = import_module(
        "cartreadback_app.context_runtime"
    ).ContextAnalysisRuntime
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS)
    chosen = parser.parse_args().scenario
    scenarios = (chosen,) if chosen else SCENARIOS

    class ObservedServer(local_server):
        """Count handler completion without logging any request contents."""

        def finish_request(self, request, client_address):
            """Observe actual request lifetime, preserving server behavior."""
            with self.observations:
                self.started += 1
            try:
                super().finish_request(request, client_address)
            finally:
                with self.observations:
                    self.finished += 1
                    self.observations.notify_all()

        def handle_error(self, request, client_address):
            """Count server exceptions and preserve the original traceback."""
            self.errors += 1
            super().handle_error(request, client_address)

    for scenario in scenarios:
        with tempfile.TemporaryDirectory(prefix="cr-ui-context-") as temporary:
            store = store_type(Path(temporary) / "synthetic.sqlite3")
            sid = store.session(None)[0]["sid"]
            state = None
            handle = None
            if scenario == "unavailable":
                runtime = runtime_type()
            else:
                runtime, state, handle = fixtures.fabricate(store, (sid,))
                if scenario == "semantic":
                    state["body"]["output"][0]["content"][0]["text"] = (
                        "bad json"
                    )
                elif scenario == "protocol":
                    state["body"]["status"] = "queued"
            service = service_type(
                store,
                context_analysis=runtime,
                clock=lambda: datetime.fromtimestamp(
                    fixtures.NOW, timezone.utc
                ),
            )
            # Session/runtime setup must not leave an active writer behind.
            probe = store.connect()
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.rollback()
                assert not probe.in_transaction
            finally:
                probe.close()
            server = ObservedServer(("127.0.0.1", 0), service, UI)
            server.started = server.finished = server.errors = 0
            server.observations = threading.Condition()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                environment = dict(
                    os.environ,
                    CART_READBACK_CONTEXT_ORIGIN=server.origin,
                    CART_READBACK_CONTEXT_COOKIE=f"cr_session={sid}",
                    CART_READBACK_CONTEXT_SCENARIO=scenario,
                )
                with (
                    patch(
                        "socket.create_connection",
                        side_effect=AssertionError(
                            "Provider sockets forbidden"
                        ),
                    ),
                    patch(
                        "http.client.HTTPSConnection",
                        side_effect=AssertionError("Real HTTPS forbidden"),
                    ),
                ):
                    subprocess.run(
                        ["node", "--test", str(UI / "context_http.test.mjs")],
                        check=True,
                        env=environment,
                        timeout=60,
                    )
                if state is not None:
                    assert state["calls"] == 1, "One fabricated exchange only"
                    assert handle.calls == 1, "One fabricated handle borrow"
                with server.observations:
                    assert server.observations.wait_for(
                        lambda: server.started == server.finished, timeout=5
                    ), (
                        "Loopback handlers did not finish after the client exited"
                    )
                assert server.errors == 0
            finally:
                print(
                    f"{scenario}: server_alive={thread.is_alive()}, "
                    f"requests_started={server.started}, "
                    f"requests_finished={server.finished}, "
                    f"server_errors={server.errors}",
                    flush=True,
                )
                server.shutdown()
                server.server_close()
                thread.join(timeout=10)
                service.close()
                if thread.is_alive():
                    raise RuntimeError("Loopback test server failed to stop")
    print(
        "C12 loopback/client checks passed with fabricated host and HTTPS only. "
        "Rendered browser, native keyboard, real providers and billing NOT tested.",
        flush=True,
    )


if __name__ == "__main__":
    main()
