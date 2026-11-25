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
# The apps' Fit checks are written against one plain stretch of the day.
os.environ["PLANNER_FIT_HOURS"] = "07:00-22:00"
os.environ["PLANNER_FIT_BREAK_MINUTES"] = "0"
os.environ["PLANNER_FIT_OFFICE"] = ""
for name in ("MCP_API_KEY", "TELEGRAM_BOT_TOKEN"):
    os.environ.pop(name, None)

from planner_api.app import create_app  # noqa: E402

if __name__ == "__main__":
    import asyncio

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    runtime = FakeRuntime()
    app = create_app(runtime=runtime, verifier=FakeVerifier())

    # The UI tests start every test from an empty planner. Only this test
    # server has it; the real API has no such route.
    @app.post("/e2e/reset")
    def reset():
        tables = runtime.service_client.tables
        for name in [name for name in tables if name != "workspaces"]:
            del tables[name]
        return {"success": True}

    # Habits are made through MCP, which this server does not serve.
    @app.post("/e2e/habit")
    def habit(body: dict):
        from planner_api.v2 import build_core

        return build_core(runtime.service_client, USER_ID).habits.add_habit(**body)

    # Every write waits a little, like a phone network, so the tests can see a
    # change on screen before the server has it. E2E_WRITE_DELAY=0 turns it off.
    delay = float(os.environ.get("E2E_WRITE_DELAY", "0.4"))
    read_counts: dict[str, int] = {}
    reminder_mode = "normal"

    @app.post("/v2/e2e/reminder-mode")
    def set_reminder_mode(body: dict):
        global reminder_mode
        reminder_mode = body["mode"]
        return {"success": True}

    @app.get("/v2/e2e/read-counts")
    def counts():
        return {"success": True, "data": {"counts": dict(read_counts)}}

    @app.middleware("http")
    async def network_delay(request, call_next):
        if request.method == "GET" and request.url.path != "/v2/e2e/read-counts":
            path = request.url.path
            if request.query_params.get("date"):
                path += "?date=" + request.query_params["date"]
            read_counts[path] = read_counts.get(path, 0) + 1
        if request.url.path == "/v2/day/reminder-schedule" and reminder_mode != "normal":
            from starlette.responses import JSONResponse
            if reminder_mode == "partial":
                return JSONResponse({"success": True, "data": {"days": []}})
            return JSONResponse({"detail": "fixture failure"}, status_code=int(reminder_mode))
        if delay and request.method != "GET":
            await asyncio.sleep(delay)
        return await call_next(request)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
