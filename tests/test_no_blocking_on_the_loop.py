"""One rule, enforced across the service: don't block the event loop.

This is the bug that kept taking Planner OS down, in three separate places,
wearing a different disguise each time. The shape is always the same — a
coroutine that never awaits, whose body does blocking network I/O. While it
runs, the process serves nothing else: not another tool call, not another
request, not /api/health, which does no work at all and still timed out.

A coroutine that never awaits is either a mistake or a blocking body that
must be handed to a thread. Both are worth failing a build over, so the rule
is mechanical rather than a judgement call: if it doesn't await, it must say
why it is allowed to be a coroutine.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Handlers are declared async only because an interface demands it; the marker
# says the body was deliberately moved onto a worker thread.
OFFLOAD_MARKERS = {"_offload_blocking", "_OffloadedTools"}

SCANNED = [
    "planner_api/mcp.py",
    "planner_core/mcp_tools.py",
]


def _decorator_names(node: ast.AST) -> set[str]:
    names = set()
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


@pytest.mark.parametrize("path", SCANNED)
def test_no_coroutine_runs_a_blocking_body_on_the_loop(path: str) -> None:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        awaits = [
            child
            for child in ast.walk(node)
            if isinstance(child, (ast.Await, ast.AsyncFor, ast.AsyncWith))
        ]
        if awaits or _decorator_names(node) & OFFLOAD_MARKERS:
            continue
        offenders.append(f"{path}:{node.lineno} {node.name}")

    assert not offenders, (
        "these coroutines never await, so their bodies run on the event loop "
        "and stall the whole process for their duration. Give the blocking "
        f"work a worker thread: {offenders}"
    )
