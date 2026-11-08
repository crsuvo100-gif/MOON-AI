# Simple test that launches the Textual UI in headless mode.

import pytest

pytest.importorskip(
    "textual.testing",
    reason="textual.testing not installed; optional UI test",
)

from textual.testing import AppTest

from app.terminal.ui import MoonTerminalApp


def test_ui_launch():
    # Run the app in headful-less mode – ``run`` returns when the UI finishes
    app = MoonTerminalApp()
    AppTest(app).run()
