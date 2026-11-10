#!/usr/bin/env python3
"""Refuse a Siri action that Siri AI cannot see or cannot understand.

Since the 27.3 Siri AI preview, Siri only uses an app intent marked
`@AppIntent(.tool)`, and it tells intents apart — and fills in their
parameters — from the description on each intent, each parameter and each
entity property. Leave one out and nothing fails anywhere: Siri just answers
"Planner OS can't be used for this", which is exactly how it shipped once.
Nothing compiles these files on Linux, so the shape is checked here.

Apple: developer.apple.com/documentation/appintents/
bringing-custom-actions-and-content-to-siri

The widget's own intents live in apple/PlannerWidget and are not tools: they
run one tap on the home screen, which is the kind Apple says not to mark.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "apple" / "PlannerOS"


def call_at(text: str, start: int) -> str:
    """The whole `@Name(...)` starting at `start`, however many lines it spans."""
    open_at = text.index("(", start)
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def body_of(text: str, start: int) -> str:
    brace = text.index("{", start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace : i + 1]
    return text[brace:]


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def check(path: Path) -> list[str]:
    text = path.read_text()
    where = path.relative_to(ROOT.parent.parent)
    problems = []

    for found in re.finditer(r"^struct (\w+)\s*:\s*AppIntent\b", text, re.M):
        name = found.group(1)
        before = text[: found.start()].rstrip().splitlines()
        attribute = before[-1].strip() if before else ""
        if not attribute.startswith("@AppIntent(.tool"):
            problems.append(f"{where}:{line_of(text, found.start())}: {name} is not marked @AppIntent(.tool), "
                            f"so Siri AI cannot see it")
        body = body_of(text, found.start())
        if "static let title" not in body and "static var title" not in body:
            problems.append(f"{where}:{line_of(text, found.start())}: {name} has no title")
        if "static let description" not in body and "static var description" not in body:
            problems.append(f"{where}:{line_of(text, found.start())}: {name} has no description, "
                            f"which is how Siri tells it apart from the others")

    for wrapper in ("@Parameter(", "@Property("):
        for found in re.finditer(re.escape(wrapper), text):
            call = call_at(text, found.start())
            if not re.search(r"\bdescription\s*:", call):
                problems.append(f"{where}:{line_of(text, found.start())}: {wrapper[:-1]} has no description, "
                                f"so Siri has to guess what to put in it")
    return problems


def main() -> int:
    problems = []
    intents = 0
    for path in sorted(ROOT.glob("*.swift")):
        intents += len(re.findall(r"^struct \w+\s*:\s*AppIntent\b", path.read_text(), re.M))
        problems += check(path)
    if problems:
        print("Siri actions Siri AI cannot use properly:")
        for problem in problems:
            print("  " + problem)
        return 1
    print(f"swift_intents: all {intents} Siri actions are tools, with every description Siri reads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
