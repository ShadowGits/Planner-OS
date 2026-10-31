"""The real Planner OS API on an in-memory database, for end-to-end app tests.

Uses the same fakes as tests/test_day_api.py, so it starts empty and needs no
Supabase. App key: app-secret. Run from the repo root:

    python3 e2e/server.py 8765
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

# Importing the app module also builds its default production app; give it
# placeholders so it builds quietly. It is never served or contacted.
os.environ.setdefault("SUPABASE_URL", "https://placeholder.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "placeholder")

import uvicorn  # noqa: E402
from test_day_api import USER_ID, FakeRuntime, FakeVerifier  # noqa: E402

os.environ["MCP_USER_ID"] = str(USER_ID)
os.environ["PWA_ACCESS_KEY"] = "app-secret"
for name in ("MCP_API_KEY", "TELEGRAM_BOT_TOKEN"):
    os.environ.pop(name, None)

from planner_api.app import create_app  # noqa: E402

if __name__ == "__main__":
    import asyncio

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    app = create_app(runtime=FakeRuntime(), verifier=FakeVerifier())
    # Every write waits a little, like a phone network, so the tests can see a
    # change on screen before the server has it. E2E_WRITE_DELAY=0 turns it off.
    delay = float(os.environ.get("E2E_WRITE_DELAY", "0.4"))

    @app.middleware("http")
    async def network_delay(request, call_next):
        if delay and request.method != "GET":
            await asyncio.sleep(delay)
        return await call_next(request)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
