"""Run the browser regression suite as part of the normal test run.

The day screen is a plain HTML app served from planner_api/static/pwa, and for
a long time nothing tested it. Every bug that reached the phone this week lived
there: a tick that silently undid itself, a day that snapped back to today, an
add button offering a time in the middle of another task. None of it could be
caught by a Python test.

Those tests are written in JavaScript because they drive the real file in a
real DOM. This bridges them into pytest so `pytest` alone runs everything and
nobody has to remember a second command.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PWA_TESTS = Path(__file__).parent / "pwa"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_pwa_day_screen_suite() -> None:
    if not (PWA_TESTS / "node_modules").exists():
        pytest.skip("run `npm install` in tests/pwa first")

    result = subprocess.run(
        ["node", "--test", "--test-force-exit"],
        cwd=PWA_TESTS,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        # The TAP output names the failing case, so show it rather than a code.
        pytest.fail(result.stdout[-6000:] + "\n" + result.stderr[-2000:], pytrace=False)
