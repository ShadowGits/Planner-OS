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


def test_no_mcp_tool_blocks_the_event_loop() -> None:
    """A tool that never awaits must not be declared async.

    Every core tool talks to Postgres or Google over synchronous HTTP. Declared
    `async def`, the handler runs to completion on the event loop and the whole
    process serves nothing until it returns — /api/health included. A calendar
    sync takes minutes, so one call took the service down while the container
    sat there perfectly healthy. Declared `def`, the framework hands it to the
    threadpool and the loop stays free.

    The rule is mechanical: if it does not await, it is not async.
    """

    tree = ast.parse(open("planner_core/mcp_tools.py").read())

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or not node.name.startswith("core_"):
            continue
        awaits = [
            child
            for child in ast.walk(node)
            if isinstance(child, (ast.Await, ast.AsyncFor, ast.AsyncWith))
        ]
        if not awaits:
            offenders.append(node.name)

    assert not offenders, (
        "these tools are async but never await, so they block the event loop "
        f"for their whole duration: {sorted(offenders)}"
    )
