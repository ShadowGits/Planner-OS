"""Fails when Apple code reads a task field the Swift PlannerTask lacks.

SwiftUI views cannot be compiled off a Mac, so a missing field there (as
recurrenceKey once was) would only show up in Xcode. This reads PlannerTask's
properties from Models.swift and every `task.<name>` the app uses.
"""
import pathlib, re, sys

root = pathlib.Path(__file__).resolve().parent.parent / "apple" / "PlannerOS"
models = (root / "Models.swift").read_text()
body = models[models.index("struct PlannerTask"):]
body = body[:body.index("\nextension ")]
fields = set(re.findall(r"^\s{4}(?:var|let) (\w+)", body, re.M))
missing = {}
for path in sorted(root.glob("*.swift")):
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        for name in re.findall(r"\btask\.(\w+)\b(?!\()", line):
            if name not in fields:
                missing.setdefault(name, []).append(f"{path.name}:{line_no}")
if missing:
    for name, places in sorted(missing.items()):
        print(f"PlannerTask has no '{name}', used at {', '.join(places[:5])}")
    sys.exit(1)
print(f"Every task field the Apple app reads exists ({len(fields)} fields).")
