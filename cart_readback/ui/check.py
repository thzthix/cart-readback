"""Check the local UI, then its contract against an ephemeral fixture server.

This does not launch a browser or claim visual/accessibility certification.
Run from any directory: python path/to/cart_readback/ui/check.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from html.parser import HTMLParser
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"


class MarkupCheck(HTMLParser):
    """Collect identifiers and external resources without rendering HTML."""

    def __init__(self) -> None:
        """Initialize static check records."""
        super().__init__()
        self.ids: list[str] = []
        self.resources: list[str] = []
        self.label_targets: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Reject inline event handlers and record IDs/resource references."""
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.append(attributes["id"] or "")
        if tag == "label" and "for" in attributes:
            self.label_targets.append(attributes["for"] or "")
        for name, value in attrs:
            if name.startswith("on"):
                raise AssertionError("Inline event handler found")
            if name in {"src", "href"} and value and not value.startswith("#"):
                self.resources.append(value)


def contrast(first: str, second: str) -> float:
    """Return WCAG sRGB token contrast, not a rendered UI assessment."""

    def luminance(color: str) -> float:
        channels = [
            int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)
        ]
        linear = [
            value / 12.92
            if value <= 0.04045
            else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return sum(
            value * weight
            for value, weight in zip(
                linear, (0.2126, 0.7152, 0.0722), strict=True
            )
        )

    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return round((light + 0.05) / (dark + 0.05), 2)


def run(command: list[str], environment: dict[str, str] | None = None) -> None:
    """Run a check and propagate any failure."""
    subprocess.run(command, check=True, env=environment)


def main() -> None:
    """Run static, pure logic, minimal-DOM and local HTTP contract checks."""
    markup = MarkupCheck()
    markup.feed((UI / "index.html").read_text())
    assert len(markup.ids) == len(set(markup.ids)), "Duplicate HTML IDs"
    assert all(target in markup.ids for target in markup.label_targets)
    assert set(markup.resources) == {"./styles.css", "./app.mjs"}
    for name in ("app.mjs", "core.mjs"):
        source = (UI / name).read_text()
        unsafe = r"\b(?:innerHTML|outerHTML|insertAdjacentHTML|eval)\b"
        assert not re.search(unsafe, source)
        run(["node", "--check", str(UI / name)])
    ratios = {
        "ink/paper": contrast("#242a27", "#f8f7f2"),
        "muted/paper": contrast("#565d56", "#f8f7f2"),
        "white/action": contrast("#ffffff", "#274d3a"),
        "warning/background": contrast("#76500d", "#fff1d4"),
        "conflict/background": contrast("#963728", "#fff0eb"),
        "focus/paper": contrast("#005fcc", "#f8f7f2"),
        "control-border/white": contrast("#757d72", "#fffefa"),
    }
    assert all(
        value >= 4.5 for name, value in ratios.items() if "border" not in name
    )
    assert ratios["control-border/white"] >= 3
    print(
        "Static markup/source checks passed; token contrast only: "
        + json.dumps(ratios),
        flush=True,
    )
    run(
        [
            "node",
            "--test",
            str(UI / "core.test.mjs"),
            str(UI / "app.test.mjs"),
            str(UI / "return.test.mjs"),
        ]
    )
    sys.path.insert(0, str(ROOT))
    local_server = import_module("cartreadback_app.http").LocalServer
    service = import_module("cartreadback_app.service").Service
    store = import_module("cartreadback_app.storage").Store
    with tempfile.TemporaryDirectory(prefix="cr-ui-check-") as temporary:
        fixture_service = service(store(Path(temporary) / "fixture.sqlite3"))
        server = local_server(("127.0.0.1", 0), fixture_service, UI)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            environment = dict(
                os.environ,
                CART_READBACK_TEST_ORIGIN=server.origin,
            )
            run(["node", "--test", str(UI / "http.test.mjs")], environment)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    print(
        "UI checks passed. Browser rendering, native keyboard and real "
        "adapters NOT tested.",
        flush=True,
    )


if __name__ == "__main__":
    main()
