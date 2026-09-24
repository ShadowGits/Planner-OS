import unittest
import ast
import re

class TestMCPExports(unittest.TestCase):
    def test_all_service_methods_exported(self):
        with open("planner_core/services.py", "r") as f:
            services_ast = ast.parse(f.read())
            
        with open("planner_core/mcp_tools.py", "r") as f:
            mcp_content = f.read()
            
        # Find all public methods in service classes
        service_methods = set()
        for node in ast.walk(services_ast):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Service"):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        # ignore private methods and __init__
                        if not item.name.startswith("_"):
                            service_methods.add(item.name)
                            
        # Find all registered MCP tools using regex
        mcp_tools = set(re.findall(r'@server\.tool\(name="([^"]+)"\)', mcp_content))
                
        # Known mappings or intentional omissions
        whitelist = {
            "day_view", # mapped to core_today
            "due_reminders", # mapped to core_today
            "today_checklist", # mapped to core_today
            "week_view", # not an MCP tool
            "timed_items", # reminder cron only: lean read of today's timed items
            "project_tree", # not an MCP tool
            "snapshot", # mapped to core_metrics
            "flat_snapshot",
            "push_notification", # reminder service internals
            "mark_notification_sent",
            "record_sent",
            "cancel_notification",
            "clear_all_reminders",
            "sync_reminders",
            "complete_by_title",
            "reopen_task",
            # Finance tools are named for what they do rather than after the
            # method, so Claude picks the right one from the tool list alone.
            "log_transaction",  # split into core_log_expense / core_log_income
            "monthly_summary",  # mapped to core_finance_summary
            "goal_progress",  # mapped to core_finance_goals
            "add_recurring",  # mapped to core_add_recurring_charge
            "list_recurring",  # mapped to core_list_recurring_charges
            "update_recurring",  # mapped to core_update_recurring_charge
            "delete_recurring",  # mapped to core_delete_recurring_charge
            "materialize_recurring",  # cron only: POST /v2/finance/recurring/run
            "import_ics",  # cron/manual only: POST /v2/calendar/import-apple
            # Recovery, not planning: reached by asking the import to forget
            # deletions (POST /v2/calendar/import-apple?forget_deletions=true).
            "forget_deleted_events",
            # A habit's occurrences have no rows, so the tools are named for
            # the day they act on rather than after the method.
            "occurrences",  # read through core_today and the day view
            # Starring one day of a habit: reached from the PWA by patching the
            # occurrence, alongside ticking and rescheduling it.
            "star_occurrence",
            "complete_occurrence",  # mapped to core_complete_habit_day
            "reopen_occurrence",  # mapped to core_reopen_habit_day
            "reschedule_occurrence",  # mapped to core_reschedule_habit_day
            "skip_occurrence",  # mapped to core_skip_habit_day
        }
        
        missing = []
        for method in service_methods:
            if method in whitelist:
                continue
            expected_tool = f"core_{method}"
            if expected_tool not in mcp_tools:
                missing.append(expected_tool)
                
        self.assertEqual(len(missing), 0, f"The following service methods are missing MCP tool exports: {missing}")

if __name__ == "__main__":
    unittest.main()


def test_registered_tools_do_not_run_on_the_event_loop() -> None:
    """The handlers block; registration must move them off the loop.

    An earlier version of this test asserted the handlers were declared `def`,
    on the belief that FastMCP then ran them in a threadpool. It does not —
    it calls a non-coroutine handler inline, so `def` blocked the event loop
    exactly as much as a non-awaiting `async def` did, and asserting on the
    keyword proved nothing about the thing that mattered.

    So this asserts the behaviour instead: call a registered tool and check it
    ran somewhere other than the thread running the loop, and that the loop
    kept going while it blocked.
    """

    import anyio
    import threading
    import time

    from planner_core.mcp_tools import _OffloadedTools

    registered = {}

    class StubServer:
        def tool(self, **kwargs):
            def register(fn):
                registered[kwargs["name"]] = fn
                return fn
            return register

    server = _OffloadedTools(StubServer())
    ran_on = {}

    @server.tool(name="core_pretend_sync")
    def core_pretend_sync(days: int = 7) -> dict:
        ran_on["thread"] = threading.current_thread().name
        time.sleep(0.4)  # stand in for blocking HTTP
        return {"days": days}

    handler = registered["core_pretend_sync"]
    ticks = 0

    async def main():
        nonlocal ticks
        ran_on["loop"] = threading.current_thread().name

        async def ticker():
            nonlocal ticks
            for _ in range(10):
                await anyio.sleep(0.02)
                ticks += 1

        async with anyio.create_task_group() as group:
            group.start_soon(ticker)
            ran_on["result"] = await handler(days=3)

    try:
        anyio.run(main)
    finally:
        # anyio.run closes the loop it made and leaves asyncio with none, which
        # breaks any later test still using the deprecated get_event_loop().
        import asyncio

        asyncio.set_event_loop(asyncio.new_event_loop())

    assert ran_on["result"] == {"days": 3}, "the tool still returns its value"
    assert ran_on["thread"] != ran_on["loop"], (
        "the handler ran on the event loop thread, so it blocks the whole service"
    )
    assert ticks == 10, "the event loop stalled while the handler blocked"


def test_tool_signatures_survive_being_offloaded() -> None:
    """FastMCP builds each tool's argument model from the signature.

    Wrapping a handler must not hide its parameters, or the tool registers
    with the wrong schema and every call fails validation.
    """

    import inspect

    from planner_core.mcp_tools import _OffloadedTools

    registered = {}

    class StubServer:
        def tool(self, **kwargs):
            def register(fn):
                registered[kwargs["name"]] = fn
                return fn
            return register

    server = _OffloadedTools(StubServer())

    @server.tool(name="core_pretend")
    def core_pretend(project_id: str, limit: int = 10) -> dict:
        """Docstring the tool description comes from."""
        return {}

    handler = registered["core_pretend"]
    signature = inspect.signature(handler)

    assert list(signature.parameters) == ["project_id", "limit"]
    assert signature.parameters["limit"].default == 10
    assert handler.__name__ == "core_pretend"
    assert handler.__doc__ == "Docstring the tool description comes from."
