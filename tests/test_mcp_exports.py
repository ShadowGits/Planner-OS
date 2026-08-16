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
            # A habit's occurrences have no rows, so the tools are named for
            # the day they act on rather than after the method.
            "occurrences",  # read through core_today and the day view
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
