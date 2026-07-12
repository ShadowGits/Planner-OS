"""Build and validate the canonical Planner OS public-function manifest."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).parents[1]
TECHNICAL_REFERENCE_PATH = PROJECT_ROOT / "docs" / "technical_reference.md"
MCP_SERVER_PATH = PROJECT_ROOT / "planner_mcp" / "server.py"
MANIFEST_PATH = Path(__file__).with_name("function_manifest.json")

_TOOL_ROW = re.compile(
    r"^\|\s*`(?P<name>[a-z][a-z0-9_]*)`\s*\|"
    r"\s*(?P<parameters>.*?)\s*\|\s*(?P<behavior>.*?)\s*\|\s*$"
)

_READ_ONLY_TOOLS = {
    "apple_calendar_calendars",
    "apple_calendar_list_range",
    "apple_calendar_reconcile_range",
    "apple_calendar_status",
    "calendar_list_range",
    "calendar_lookup_event",
    "calendar_reconcile_range",
    "daily_checkin",
    "daily_review",
    "explain_active_constraints",
    "get_active_execution_target",
    "get_preference",
    "list_dated_tasks",
    "list_execution_targets",
    "list_preferences",
    "list_recurrences",
    "list_rules",
    "monthly_review",
    "parse_common_intent",
    "plan_today",
    "plan_today_from_now",
    "planner_doctor",
    "replan_today_from_now",
    "status",
    "validate",
    "weekly_review",
}

_LOCAL_STATE_WRITES = {
    "apply_execution_target_switch",
    "apply_planner_repair",
    "calendar_repair_mapping",
    "reset_preference",
    "set_active_execution_target",
    "set_apple_calendar",
    "set_no_work_days",
    "set_work_days",
    "update_preference",
    "update_rule",
}

_EXTERNAL_WRITES = {
    "apple_calendar_delete_event",
    "apple_calendar_update_event",
    "apply_apple_calendar_delete_range",
    "apply_calendar_cleanup_orphans",
    "apply_calendar_delete_range",
    "apply_move_external_items",
    "calendar_delete_event",
    "calendar_delete_future_series",
    "calendar_delete_series",
    "calendar_sync_current_week",
    "calendar_sync_date",
    "calendar_sync_month",
    "calendar_sync_next_week",
    "calendar_sync_range",
    "calendar_sync_today",
    "calendar_sync_week",
    "calendar_sync_week_number",
    "calendar_update_event",
    "create_apple_calendar",
    "publish_current_week",
    "publish_date",
    "publish_range",
    "publish_today",
}


class ManifestError(ValueError):
    """Raised when documentation and live MCP registration diverge."""


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def parse_documented_tools(path: Path = TECHNICAL_REFERENCE_PATH) -> dict[str, dict[str, str]]:
    """Parse MCP tool rows from the technical reference."""

    tools: dict[str, dict[str, str]] = {}
    category: str | None = None
    in_mcp_reference = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "## MCP Tool Reference":
            in_mcp_reference = True
            continue
        if in_mcp_reference and line.startswith("## "):
            break
        if not in_mcp_reference:
            continue
        if line.startswith("### "):
            category = line[4:].strip()
            continue
        match = _TOOL_ROW.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name in tools:
            raise ManifestError(f"Duplicate documented MCP tool: {name}")
        if category is None:
            raise ManifestError(f"Documented MCP tool has no category: {name}")
        tools[name] = {
            "category": category,
            "category_key": _slug(category),
            "documented_parameters": match.group("parameters").strip(),
            "documented_behavior": match.group("behavior").strip(),
        }
    if not tools:
        raise ManifestError(f"No MCP tools found in {path}")
    return tools


def _is_mcp_tool(decorator: ast.expr) -> bool:
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "tool"
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "mcp"
    )


def _parameter_records(arguments: ast.arguments) -> list[dict[str, Any]]:
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults))
    defaults.extend(arguments.defaults)
    records = [
        _parameter_record(argument, default)
        for argument, default in zip(positional, defaults, strict=True)
    ]
    if arguments.vararg is not None:
        records.append(_parameter_record(arguments.vararg, None, kind="var_positional"))
    records.extend(
        _parameter_record(argument, default, kind="keyword_only")
        for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
    )
    if arguments.kwarg is not None:
        records.append(_parameter_record(arguments.kwarg, None, kind="var_keyword"))
    return records


def _parameter_record(
    argument: ast.arg,
    default: ast.expr | None,
    *,
    kind: str = "positional_or_keyword",
) -> dict[str, Any]:
    return {
        "name": argument.arg,
        "annotation": ast.unparse(argument.annotation) if argument.annotation else None,
        "required": default is None and kind not in {"var_positional", "var_keyword"},
        "default": ast.unparse(default) if default is not None else None,
        "kind": kind,
    }


def parse_registered_tools(path: Path = MCP_SERVER_PATH) -> dict[str, dict[str, Any]]:
    """Parse decorated MCP functions without importing the live server."""

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    tools: dict[str, dict[str, Any]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_mcp_tool(decorator) for decorator in node.decorator_list):
            continue
        if node.name in tools:
            raise ManifestError(f"Duplicate registered MCP tool: {node.name}")
        tools[node.name] = {
            "parameters": _parameter_records(node.args),
            "return_annotation": ast.unparse(node.returns) if node.returns else None,
            "description": ast.get_docstring(node) or "",
            "source_line": node.lineno,
        }
    if not tools:
        raise ManifestError(f"No decorated MCP tools found in {path}")
    return tools


def _effect_for(name: str) -> str:
    if name.startswith("preview_"):
        return "preview"
    if name in _READ_ONLY_TOOLS:
        return "read"
    if name in _LOCAL_STATE_WRITES:
        return "local_state_write"
    if name in _EXTERNAL_WRITES:
        return "external_write"
    if name == "route_planner_command":
        return "mixed"
    return "workbook_write"


def _cloud_policy(name: str, category_key: str) -> dict[str, str]:
    if category_key == "apple_calendar":
        return {
            "status": "disabled",
            "reason": "Requires the local macOS EventKit helper and cannot run on Vercel.",
        }
    if name == "import_plan":
        return {
            "status": "adaptation_required",
            "reason": "Replace the local input_path with a validated upload_id or request body.",
        }
    return {
        "status": "candidate",
        "reason": "Stage 2 must bind this tool to tenant-safe ports and policy metadata.",
    }


def build_manifest(
    technical_reference_path: Path = TECHNICAL_REFERENCE_PATH,
    mcp_server_path: Path = MCP_SERVER_PATH,
) -> dict[str, Any]:
    """Build a deterministic manifest and enforce exact documentation parity."""

    documented = parse_documented_tools(technical_reference_path)
    registered = parse_registered_tools(mcp_server_path)
    missing_from_server = sorted(set(documented) - set(registered))
    missing_from_docs = sorted(set(registered) - set(documented))
    if missing_from_server or missing_from_docs:
        raise ManifestError(
            "MCP documentation/registration mismatch: "
            f"missing_from_server={missing_from_server}, missing_from_docs={missing_from_docs}"
        )

    tools: list[dict[str, Any]] = []
    for name in sorted(documented):
        doc = documented[name]
        live = registered[name]
        tools.append(
            {
                "name": name,
                "category": doc["category"],
                "category_key": doc["category_key"],
                "description": live["description"],
                "documented_parameters": doc["documented_parameters"],
                "documented_behavior": doc["documented_behavior"],
                "parameters": live["parameters"],
                "return_annotation": live["return_annotation"],
                "effect": _effect_for(name),
                "cloud": _cloud_policy(name, doc["category_key"]),
                "source_line": live["source_line"],
            }
        )
    return {
        "schema_version": 1,
        "tool_count": len(tools),
        "sources": {
            "technical_reference": str(technical_reference_path.relative_to(PROJECT_ROOT)),
            "mcp_server": str(mcp_server_path.relative_to(PROJECT_ROOT)),
        },
        "tools": tools,
    }


def manifest_json(manifest: dict[str, Any] | None = None) -> str:
    """Serialize a manifest deterministically."""

    return json.dumps(manifest or build_manifest(), indent=2, sort_keys=True) + "\n"


def check_manifest(path: Path = MANIFEST_PATH) -> None:
    """Raise when the checked-in manifest differs from its source files."""

    expected = manifest_json()
    actual = path.read_text(encoding="utf-8") if path.exists() else ""
    if actual != expected:
        raise ManifestError(
            f"Function manifest is stale: run python -m planner_platform.function_manifest --write"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the canonical manifest")
    mode.add_argument("--check", action="store_true", help="verify the checked-in manifest")
    args = parser.parse_args()
    if args.write:
        MANIFEST_PATH.write_text(manifest_json(), encoding="utf-8")
        print(f"Wrote {MANIFEST_PATH}")
        return 0
    if args.check:
        check_manifest()
        print(f"Manifest OK: {len(build_manifest()['tools'])} tools")
        return 0
    print(manifest_json(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

