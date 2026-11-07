"""Run viewer UI against actual loopback HTTP; all provider data is fabricated."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("known", "current-model", "semantic", "protocol", "expired")


def main() -> None:
    """Verify exact server envelopes and fake DOM, without a real browser/key."""
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    fixtures = import_module("test_gemini_service")
    viewer_type = import_module(
        "cartreadback_app.gemini_viewer"
    ).GeminiResultViewer
    service_type = import_module("cartreadback_app.service").Service
    storage = import_module("cartreadback_app.storage")
    client = import_module("cartreadback_app.gemini_client")
    for scenario in SCENARIOS:
        with tempfile.TemporaryDirectory(
            prefix="cr-gemini-viewer-"
        ) as directory:
            store = storage.Store(Path(directory) / "synthetic.sqlite3")
            sid = store.session(None)[0]["sid"]
            model = (
                client.CURRENT_MODEL
                if scenario == "current-model"
                else client.MODEL
            )
            runtime, state, handle = fixtures.fabricate(
                store, (sid,), free=True, max_calls=1, model=model
            )
            if scenario == "semantic":
                state["body"]["candidates"][0]["content"]["parts"][0][
                    "text"
                ] = "bad json"
            if scenario == "protocol":
                state["body"]["modelVersion"] = "unsupported-model"
            service = service_type(
                store,
                gemini_analysis=runtime,
                clock=lambda: datetime.fromtimestamp(
                    fixtures.NOW, timezone.utc
                ),
            )
            server = None
            thread = None
            try:
                with patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("No provider sockets"),
                ):
                    service.mutate(
                        sid,
                        "analyze",
                        {
                            "expected_revision": 0,
                            "sku_id": "KB-UK-C2C",
                            "conditions": [
                                {"kind": item["kind"], "value": item["value"]}
                                for item in fixtures.CHOICES
                            ],
                        },
                    )
                with store.transaction() as connection:
                    product = storage.product_for(connection, "KB-UK-C2C")
                if scenario == "expired":
                    service.clock = lambda: datetime.fromtimestamp(
                        fixtures.NOW + 101, timezone.utc
                    )
                server = viewer_type(
                    ("127.0.0.1", 0),
                    service,
                    sid,
                    product,
                    fixtures.CHOICES,
                    ROOT / "ui",
                )
                thread = threading.Thread(target=server.serve_forever)
                thread.start()

                # Synthetic capability travels only via process stdin, never a
                # file, argv, environment, console or test report.
                def opener(url):
                    capability = url.split("#launch=", 1)[1]
                    subprocess.run(
                        [
                            "node",
                            str(ROOT / "ui/viewer_http.test.mjs"),
                        ],
                        input=json.dumps(
                            {
                                "scenario": scenario,
                                "origin": server.origin,
                                "capability": capability,
                            }
                        ),
                        text=True,
                        env=dict(
                            os.environ, NODE_OPTIONS="--test-reporter=tap"
                        ),
                        timeout=30,
                        check=True,
                    )

                server.launch(opener)
                assert state["calls"] == 1 and handle.calls == 1
            finally:
                if server:
                    if thread:
                        server.shutdown()
                        thread.join(8)
                        assert not thread.is_alive()
                    server.server_close()
                service.close()


if __name__ == "__main__":
    main()
