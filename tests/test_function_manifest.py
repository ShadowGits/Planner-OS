from __future__ import annotations

import json

import pytest

from planner_platform.function_manifest import (
    MANIFEST_PATH,
    ManifestError,
    build_manifest,
    check_manifest,
    parse_documented_tools,
    parse_registered_tools,
)


def test_technical_reference_and_mcp_server_have_exact_tool_parity() -> None:
    documented = parse_documented_tools()
    registered = parse_registered_tools()

    assert len(documented) == 93
    assert set(documented) == set(registered)


def test_manifest_is_deterministic_and_matches_checked_in_file() -> None:
    check_manifest()

    checked_in = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert checked_in == build_manifest()
    assert checked_in["tool_count"] == 93


def test_every_manifest_parameter_resolves_at_cloud_boot() -> None:
    # The cloud MCP server builds a handler for every tool at startup and maps
    # each parameter's annotation string through planner_api.mcp._ANNOTATIONS.
    # An annotation missing from that table (e.g. a bare "list" instead of
    # "list[str]") raises KeyError and takes the whole /mcp endpoint down at
    # boot. Exercise that exact resolution here so it fails in CI, not in prod.
    from planner_api.mcp import _parameter

    for tool in build_manifest()["tools"]:
        for parameter in tool["parameters"]:
            try:
                _parameter(parameter)
            except Exception as error:  # pragma: no cover - failure path
                raise AssertionError(
                    f"{tool['name']}.{parameter['name']} has annotation "
                    f"{parameter.get('annotation')!r} that the cloud MCP boot "
                    f"cannot resolve: {error}"
                ) from error


def test_manifest_marks_local_apple_tools_cloud_disabled() -> None:
    tools = {tool["name"]: tool for tool in build_manifest()["tools"]}

    assert tools["apple_calendar_status"]["cloud"]["status"] == "disabled"
    assert tools["apple_calendar_delete_event"]["effect"] == "external_write"


def test_manifest_marks_local_path_import_for_cloud_adaptation() -> None:
    tools = {tool["name"]: tool for tool in build_manifest()["tools"]}

    assert tools["import_plan"]["cloud"]["status"] == "adaptation_required"
    assert "input_path" in tools["import_plan"]["cloud"]["reason"]


def test_manifest_fails_when_documentation_and_registration_diverge(tmp_path) -> None:
    reference = tmp_path / "technical_reference.md"
    reference.write_text(
        "## MCP Tool Reference\n\n"
        "### Test\n\n"
        "| Tool | Parameters | Behavior and side effects |\n"
        "|---|---|---|\n"
        "| `not_registered` | none | Read-only. |\n\n"
        "## Shadow CLI Reference\n",
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="documentation/registration mismatch"):
        build_manifest(technical_reference_path=reference)

