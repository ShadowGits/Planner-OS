#!/usr/bin/env python3
"""Build the reference inventory from a committed revision; never read secrets."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode()


def cell(value):
    return str(value).replace("|", "&#124;").replace("\n", " ")


def link(path, line=None):
    return f"[{path}{':' + str(line) if line else ''}](../{path})"


def signature(node):
    return f"{node.name}({ast.unparse(node.args)})" + (f" → {ast.unparse(node.returns)}" if node.returns else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Committed Git revision to inventory")
    parser.add_argument("--output", default="docs/interface_inventory.md")
    args = parser.parse_args()
    revision = git("rev-parse", args.ref).strip()
    files = git("ls-tree", "-r", "--name-only", revision).splitlines()
    sources = {p: git("show", f"{revision}:{p}") for p in files if p.endswith((".py", ".sql", ".ts", ".tsx", ".mjs")) and p.startswith(("planner_", "adapters/", "app/", "lib/", "scripts/", "supabase/"))}
    routes, tools, models, services = [], [], [], []
    env = {}
    migrations = []
    for path, source in sources.items():
        if path.endswith(".py"):
            tree = ast.parse(source)
            named_keys = {}
            for assignment in ast.walk(tree):
                if isinstance(assignment, ast.Assign):
                    values = [v.value for v in ast.walk(assignment.value) if isinstance(v, ast.Constant) and isinstance(v.value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", v.value)]
                    for target in assignment.targets:
                        if isinstance(target, ast.Name):
                            named_keys.setdefault(target.id, set()).update(values)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = (ast.get_docstring(node) or "").split("\n\n")[0]
                    for dec in node.decorator_list:
                        if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                            continue
                        method = dec.func.attr
                        if method in ("get", "post", "patch", "put", "delete") and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str) and dec.args[0].value.startswith("/"):
                            routes.append((path, node.lineno, method.upper(), dec.args[0].value, signature(node), doc))
                        if method == "tool":
                            name = next((k.value.value for k in dec.keywords if k.arg == "name" and isinstance(k.value, ast.Constant)), node.name)
                            tools.append((path, node.lineno, name, signature(node), doc))
                if isinstance(node, ast.ClassDef):
                    if any(ast.unparse(base).split(".")[-1] == "BaseModel" for base in node.bases):
                        fields = [f"{f.target.id}: {ast.unparse(f.annotation)}" + (f" = {ast.unparse(f.value)}" if f.value else "") for f in node.body if isinstance(f, ast.AnnAssign) and isinstance(f.target, ast.Name)]
                        models.append((path, node.lineno, node.name, fields))
                    if path == "planner_core/services.py":
                        for fn in node.body:
                            if isinstance(fn, ast.FunctionDef) and not fn.name.startswith("_"):
                                services.append((node.name, signature(fn), path, fn.lineno, (ast.get_docstring(fn) or "").split("\n\n")[0]))
                if isinstance(node, ast.Call) and ast.unparse(node.func) in ("os.environ.get", "os.getenv") and node.args:
                    names = [str(node.args[0].value)] if isinstance(node.args[0], ast.Constant) else named_keys.get(node.args[0].id, ()) if isinstance(node.args[0], ast.Name) else ()
                    for name in names:
                        env.setdefault(name, set()).add(path)
                if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ" and isinstance(node.slice, ast.Constant):
                    env.setdefault(str(node.slice.value), set()).add(path)
        else:
            for name in re.findall(r"process\.env\.([A-Z][A-Z0-9_]+)", source):
                env.setdefault(name, set()).add(path)
        if path.startswith("supabase/migrations/"):
            tables = sorted(set(re.findall(r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?([\w]+)", source, re.I)))
            functions = sorted(set(re.findall(r"create\s+(?:or\s+replace\s+)?function\s+(?:public\.)?([\w]+)", source, re.I)))
            migrations.append((path, tables, functions))
    lines = ["# Planner OS interface inventory", "", f"Generated from committed revision `{revision}`. Regenerate with `python3 scripts/generate_reference_inventory.py --ref HEAD`.", "", "This is a source inventory, not proof of live deployment. Auth, invariants, feature behavior and operational instructions are in [technical_reference.md](technical_reference.md). Signatures include framework parameters, not just JSON body fields. Source links include line labels for lookup; GitHub links open files. Dynamic routes and OAuth/MCP transport endpoints are explained in the handoff.", "", f"Inventory: {len(routes)} decorated HTTP routes, {len(tools)} MCP tools, {len(models)} request/model classes, {len(services)} public core service methods, {len(migrations)} tracked SQL migrations.", "", "## HTTP routes", "", "| Method | Path | Handler / parameters | Source |", "|---|---|---|---|"]
    for p, n, method, route, sig, doc in sorted(routes, key=lambda r: (r[3], r[2])):
        lines.append(f"| {method} | `{route}` | `{cell(sig)}` | {link(p,n)} |")
    lines += ["", "## MCP tools", "", "Return annotations vary: several tools return JSON strings rather than objects. Read the handler before composing a client parser. All registered core tools resolve the authenticated caller's active workspace.", "", "| Tool | Signature | Behavior from source docstring | Source |", "|---|---|---|---|"]
    for p,n,name,sig,doc in sorted(tools,key=lambda r:r[2]):
        lines.append(f"| `{name}` | `{cell(sig)}` | {cell(doc)} | {link(p,n)} |")
    lines += ["", "## Pydantic request and model fields", "", "A field without a default is required. `Field(...)` contains source-level bounds and patterns. These declarations do not replace business rules or auth. Some models are internal rather than public requests."]
    for p,n,name,fields in sorted(models):
        lines += ["", f"### {name}", "", f"Source: {link(p,n)}", "", "```python", *fields, "```"]
    lines += ["", "## Core service methods", "", "| Service | Method | Behavior from source docstring | Source |", "|---|---|---|---|"]
    for cls,sig,p,n,doc in services:
        lines.append(f"| `{cls}` | `{cell(sig)}` | {cell(doc)} | {link(p,n)} |")
    lines += ["", "## SQL migrations", "", "Lists declarations introduced/replaced in each migration. ALTERs, policies, grants, triggers and data repairs require reading the linked SQL. Number gaps are intentional; untracked migration 0033 is excluded.", "", "| Migration | CREATE TABLE declarations | CREATE FUNCTION declarations |", "|---|---|---|"]
    for p,t,f in sorted(migrations):
        lines.append(f"| {link(p)} | {', '.join('`'+x+'`' for x in t) or '—'} | {', '.join('`'+x+'`' for x in f) or '—'} |")
    lines += ["", "## Environment variable usage", "", "Names only; no credentials or environment files are read. Includes deployment/runtime controls and OAuth library switches. Availability here does not imply every optional integration must be configured.", "", "| Name | Referencing source files |", "|---|---|"]
    for name,paths in sorted(env.items()):
        lines.append(f"| `{name}` | {', '.join(link(p) for p in sorted(paths))} |")
    target = ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines)+"\n")
    print(f"Wrote {target.relative_to(ROOT)}: {len(routes)} routes, {len(tools)} tools, {len(models)} models")


if __name__ == "__main__":
    main()
