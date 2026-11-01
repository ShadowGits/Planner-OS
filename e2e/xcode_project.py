"""Check apple/PlannerOS.xcodeproj parses and hangs together.

Xcode cannot run here, and a project file it refuses to open is a dead end on
the other side — no error worth reading, just a project that will not open. So
the structure is checked where it can be: the file parses as the OpenStep plist
Xcode writes, every id referenced exists, and each target still has the phases,
folders and configurations it needs.
"""
from __future__ import annotations

import pathlib
import re
import sys

PROJECT = pathlib.Path(__file__).resolve().parent.parent / "apple" / "PlannerOS.xcodeproj" / "project.pbxproj"
TOKEN = re.compile(r"[A-Za-z0-9_./$()\[\]*@+:~-]+")
OBJECT_ID = re.compile(r"[0-9A-F]{24}")


def _skip(text: str, i: int) -> int:
    while i < len(text):
        if text[i] in " \t\n":
            i += 1
        elif text.startswith("//", i):
            i = text.index("\n", i)
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
        else:
            return i
    return i


def _value(text: str, i: int):
    i = _skip(text, i)
    if text[i] == "{":
        i, out = i + 1, {}
        while True:
            i = _skip(text, i)
            if text[i] == "}":
                return out, i + 1
            key, i = _value(text, i)
            i = _skip(text, i)
            if text[i] != "=":
                raise SystemExit(f"expected = near: {text[i - 50:i + 50]!r}")
            val, i = _value(text, i + 1)
            i = _skip(text, i)
            if text[i] != ";":
                raise SystemExit(f"expected ; near: {text[i - 60:i + 40]!r}")
            out[key], i = val, i + 1
    if text[i] == "(":
        i, out = i + 1, []
        while True:
            i = _skip(text, i)
            if text[i] == ")":
                return out, i + 1
            val, i = _value(text, i)
            out.append(val)
            i = _skip(text, i)
            if text[i] == ",":
                i += 1
    if text[i] == '"':
        j = i + 1
        while text[j] != '"' or text[j - 1] == "\\":
            j += 1
        return text[i + 1:j], j + 1
    match = TOKEN.match(text, i)
    if not match:
        raise SystemExit(f"bad token near: {text[i - 40:i + 40]!r}")
    return match.group(0), match.end()


def _ids(value):
    if isinstance(value, str):
        if OBJECT_ID.fullmatch(value):
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _ids(item)


def main() -> int:
    text = PROJECT.read_text()
    root, end = _value(text, 0)
    if _skip(text, end) < len(text):
        raise SystemExit("there is something after the project's closing brace")

    objects = root["objects"]
    dangling = sorted({ref for ref in _ids(objects) if ref not in objects})
    if dangling:
        raise SystemExit(f"these ids are referenced but not defined: {dangling}")

    project = objects[root["rootObject"]]
    targets = {objects[t]["name"]: objects[t] for t in project["targets"]}

    expected = {
        "PlannerOS": "com.apple.product-type.application",
        "PlannerWidget": "com.apple.product-type.app-extension",
    }
    for name, kind in expected.items():
        if name not in targets:
            raise SystemExit(f"the {name} target is missing")
        if targets[name]["productType"] != kind:
            raise SystemExit(f"{name} should be a {kind}")

    app, widget = targets["PlannerOS"], targets["PlannerWidget"]

    # The widget only reaches the app's data through the folder they share.
    for name, target in (("PlannerOS", app), ("PlannerWidget", widget)):
        folders = [objects[g]["path"] for g in target.get("fileSystemSynchronizedGroups", [])]
        if "Shared" not in folders:
            raise SystemExit(f"{name} does not compile the Shared folder: {folders}")

    # Without the embed phase the widget is built and then left behind.
    phases = [objects[p] for p in app["buildPhases"]]
    embed = [p for p in phases if p["isa"] == "PBXCopyFilesBuildPhase"]
    if not embed:
        raise SystemExit("the app has no phase that embeds the widget")
    embedded = [objects[objects[f]["fileRef"]]["path"] for f in embed[0]["files"]]
    if "PlannerWidget.appex" not in embedded:
        raise SystemExit(f"the embed phase does not carry the widget: {embedded}")
    if embed[0]["dstSubfolderSpec"] != "13":
        raise SystemExit("extensions have to be embedded in PlugIns (dstSubfolderSpec 13)")
    if not app.get("dependencies"):
        raise SystemExit("the app does not depend on the widget, so it may embed a stale one")

    for name, target in (("PlannerOS", app), ("PlannerWidget", widget)):
        configs = {objects[c]["name"]: objects[c]["buildSettings"]
                   for c in objects[target["buildConfigurationList"]]["buildConfigurations"]}
        if set(configs) != {"Debug", "Release"}:
            raise SystemExit(f"{name} should have Debug and Release, has {sorted(configs)}")
        for config, settings in configs.items():
            keys = [k for k in settings if k.startswith("CODE_SIGN_ENTITLEMENTS")]
            if not keys:
                raise SystemExit(f"{name} {config} signs no entitlements, so there is no App Group")
            for key in keys:
                entitlement = PROJECT.parent.parent / settings[key]
                if not entitlement.exists():
                    raise SystemExit(f"{name} {config} points at a missing {settings[key]}")

    print(f"Xcode project: {len(objects)} objects, {len(targets)} targets, every reference resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
