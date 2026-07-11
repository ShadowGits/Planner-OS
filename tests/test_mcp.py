from __future__ import annotations

import json
import select
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from openpyxl import load_workbook

from planner_mcp import PlannerMCPConfig, PlannerMCPTools
from test_writer import create_writer_workbook


class PlannerMCPToolsTests(TestCase):
    """Focused tests for Planner OS MCP tools."""

    def test_stdio_server_initializes_and_lists_tools_without_stdout_noise(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        process = subprocess.Popen(
            [sys.executable, "-m", "planner_mcp.server"],
            cwd=repo_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            self._write_json_rpc(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "planner-mcp-test", "version": "1.0"},
                    },
                },
            )
            initialize_response = self._read_json_rpc(process)
            self.assertEqual(initialize_response["id"], 1)

            self._write_json_rpc(
                process,
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
            )
            self._write_json_rpc(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )
            tools_response = self._read_json_rpc(process)
            self.assertEqual(tools_response["id"], 2)
            tool_names = {
                tool["name"] for tool in tools_response["result"]["tools"]
            }
            self.assertEqual(
                tool_names,
                {
                    "validate",
                    "plan_today",
                    "status",
                    "complete_task",
                    "add_task",
                    "update_task",
                    "move_task",
                    "delete_task",
                    "import_plan",
                },
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_validate_plan_today_and_status(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            planner_path = tmp_path / "planner.xlsx"
            create_writer_workbook(planner_path)
            tools = self._tools(tmp_path, planner_path)

            validate = tools.validate()
            plan = tools.plan_today()
            status = tools.status()

            self.assertTrue(validate["success"])
            self.assertEqual(validate["message"], "Everything OK")
            self.assertTrue(plan["success"])
            self.assertIn("blocks", plan["data"])
            self.assertTrue(status["success"])
            self.assertIn("gym_sessions_required", status["data"])

    def test_complete_add_update_move_delete_task(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            planner_path = tmp_path / "planner.xlsx"
            create_writer_workbook(planner_path)
            tools = self._tools(tmp_path, planner_path)

            complete = tools.complete_task("Existing Task")
            add = tools.add_task(
                task="MCP Task",
                week=2,
                category="Study",
                notes="from mcp",
            )
            update = tools.update_task("MCP Task", status="In Progress")
            move = tools.move_task("MCP Task", destination_week=1)
            delete = tools.delete_task("MCP Task")

            self.assertTrue(complete["success"])
            self.assertTrue(complete["data"]["progress_updated"])
            self.assertTrue(add["success"])
            self.assertTrue(update["success"])
            self.assertTrue(move["success"])
            self.assertTrue(delete["success"])
            workbook = load_workbook(planner_path)
            try:
                sheet = workbook["Jul 2026"]
                self.assertEqual(sheet["K38"].value, "Done")
                self.assertIsNone(sheet["B23"].value)
            finally:
                workbook.close()

    def test_import_plan(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            planner_path = tmp_path / "planner.xlsx"
            input_path = tmp_path / "plan.json"
            create_writer_workbook(planner_path)
            input_path.write_text(
                json.dumps(
                    {
                        "month": "Jul 2026",
                        "monthly_goals": [
                            {
                                "goal": "MCP Imported Goal",
                                "category": "Learning",
                                "priority": "High",
                                "target_week": "W2",
                                "status": "Not Started",
                                "notes": "",
                            }
                        ],
                        "weeks": [
                            {
                                "week": 2,
                                "tasks": [
                                    {
                                        "task": "MCP Imported Task",
                                        "category": "Study",
                                        "status": "Not Started",
                                        "notes": "",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            tools = self._tools(tmp_path, planner_path)

            result = tools.import_plan(str(input_path))

            self.assertTrue(result["success"])
            self.assertEqual(result["data"]["goals_imported"], 1)
            self.assertEqual(result["data"]["tasks_imported"], 1)

    def test_error_payload_for_missing_task(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            planner_path = tmp_path / "planner.xlsx"
            create_writer_workbook(planner_path)
            tools = self._tools(tmp_path, planner_path)

            result = tools.complete_task("Missing Task")

            self.assertFalse(result["success"])
            self.assertIn("Task not found: Missing Task", result["errors"])

    def _tools(self, tmp_path: Path, planner_path: Path) -> PlannerMCPTools:
        repo_root = Path(__file__).resolve().parents[1]
        return PlannerMCPTools(
            PlannerMCPConfig(
                planner_path=planner_path,
                backup_dir=tmp_path / "backups",
                rules_path=repo_root / "config" / "rules.yaml",
                month="Jul 2026",
            )
        )

    def _write_json_rpc(
        self,
        process: subprocess.Popen[str],
        message: dict,
    ) -> None:
        self.assertIsNotNone(process.stdin)
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def _read_json_rpc(self, process: subprocess.Popen[str]) -> dict:
        self.assertIsNotNone(process.stdout)
        ready, _, _ = select.select([process.stdout], [], [], 10)
        if not ready:
            stderr = process.stderr.read() if process.stderr else ""
            self.fail(f"Timed out waiting for MCP stdout. stderr: {stderr}")

        line = process.stdout.readline()
        self.assertNotEqual(line, "", "MCP server closed stdout unexpectedly")
        self.assertNotEqual(line, "\n", "MCP server wrote a blank line to stdout")
        try:
            return json.loads(line)
        except json.JSONDecodeError as error:
            self.fail(f"Non-JSON MCP stdout: {line!r}; error: {error}")
