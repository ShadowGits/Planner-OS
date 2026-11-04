#!/usr/bin/env python3
"""Refuse a tap gesture or a drag source laid over a button.

A SwiftUI `Button` inside a view that also carries `.onTapGesture` or
`.onDrag` works on iPhone and loses its click on the Mac: the outer gesture
takes it. That is how ticking a task off the Mac timeline came to open the
editor instead. Nothing compiles these views on Linux and no unit test sees
them, so the shape is checked here instead: a button must be a sibling of the
tappable part, not a child of it.

Put `// tap-ok` on the modifier's line for the rare case where the outer
gesture really should win.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "apple"
GESTURES = (".onTapGesture", ".onDrag")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def blank_noise(text: str) -> str:
    """Replace comments and string bodies with spaces, keeping every offset."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif two == "/*":
            while i < n and text[i:i + 2] != "*/":
                out[i] = " "
                i += 1
            for j in range(i, min(i + 2, n)):
                out[j] = " "
            i += 2
        elif text[i] == '"':
            out[i] = " "
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    out[i] = " "
                    i += 1
                if i < n:
                    out[i] = " "
                    i += 1
            if i < n:
                out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def skip_back(clean: str, i: int) -> int:
    while i >= 0 and clean[i] in " \t\n\r":
        i -= 1
    return i


def match_back(clean: str, i: int, close: str, open_: str) -> int:
    """Index of the opener matching the closer at `i`, or -1."""
    depth = 0
    while i >= 0:
        if clean[i] == close:
            depth += 1
        elif clean[i] == open_:
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return -1


def base_region(clean: str, start: int):
    """Walk back through a postfix chain to the view the gesture modifies.

    Returns (begin, end) of the braces holding that view's children, or None
    when the view has no children to speak of.
    """
    i = skip_back(clean, start - 1)
    while i >= 0:
        if clean[i] == ")":
            open_paren = match_back(clean, i, ")", "(")
            if open_paren < 0:
                return None
            before = skip_back(clean, open_paren - 1)
            name = IDENT.search(clean[:before + 1])
            if not name:
                return None
            dot = skip_back(clean, name.start() - 1)
            if dot >= 0 and clean[dot] == ".":
                i = dot - 1  # a modifier like .frame(...): keep walking back
                i = skip_back(clean, i)
                continue
            return None  # a call such as Text("x"): no child views
        if clean[i] == "}":
            open_brace = match_back(clean, i, "}", "{")
            if open_brace < 0:
                return None
            before = skip_back(clean, open_brace - 1)
            # Labelled trailing closure: `} preview: {`
            if before >= 0 and clean[before] == ":":
                label = IDENT.search(clean[:skip_back(clean, before - 1) + 1])
                if label:
                    i = skip_back(clean, label.start() - 1)
                    continue
            if before >= 0 and clean[before] == ")":
                args = match_back(clean, before, ")", "(")
                if args < 0:
                    return None
                head = skip_back(clean, args - 1)
            else:
                head = before
            name = IDENT.search(clean[:head + 1])
            if not name:
                return None
            dot = skip_back(clean, name.start() - 1)
            if dot >= 0 and clean[dot] == ".":
                i = skip_back(clean, dot - 1)  # .overlay { ... }: keep walking
                continue
            return (open_brace, i)  # a container: these are its children
        return None
    return None


def button_helpers(clean: str) -> set[str]:
    """Names of helpers in this file that draw a button.

    A row often builds its buttons through a small `private func action(...)`.
    Without this the check would look straight past them, which is how the
    Focus card's Done and Drop buttons stayed hidden under a tap gesture.
    """
    names = set()
    for found in re.finditer(r"\b(?:func|var)\s+([A-Za-z_][A-Za-z0-9_]*)", clean):
        brace = clean.find("{", found.end())
        if brace < 0:
            continue
        depth, i, n = 0, brace, len(clean)
        while i < n:
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if re.search(r"\bButton\s*[({]", clean[brace:i]):
            names.add(found.group(1))
    return names


def check(path: Path) -> list[str]:
    text = path.read_text()
    clean = blank_noise(text)
    lines = text.splitlines()
    helpers = button_helpers(clean)
    wanted = r"\bButton\s*[({]"
    if helpers:
        wanted += r"|\b(?:" + "|".join(sorted(map(re.escape, helpers))) + r")\s*\("
    problems = []
    for gesture in GESTURES:
        for found in re.finditer(re.escape(gesture), clean):
            line_no = text.count("\n", 0, found.start()) + 1
            if "tap-ok" in lines[line_no - 1]:
                continue
            region = base_region(clean, found.start())
            if not region:
                continue
            begin, end = region
            inside = clean[begin:end]
            for button in re.finditer(wanted, inside):
                at = text.count("\n", 0, begin + button.start()) + 1
                problems.append(
                    f"{path.relative_to(ROOT.parent)}:{line_no}: "
                    f"{gesture} covers the button on line {at} — "
                    f"the Mac sends the click to the gesture, not the button"
                )
    return problems


def main() -> int:
    problems = []
    for path in sorted(ROOT.rglob("*.swift")):
        problems += check(path)
    if problems:
        print("Tap gestures laid over buttons:")
        for problem in problems:
            print("  " + problem)
        return 1
    print("swift_gestures: no tap gesture or drag source covers a button")
    return 0


if __name__ == "__main__":
    sys.exit(main())
