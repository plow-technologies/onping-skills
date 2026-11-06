#!/usr/bin/env python3
"""Fail when a skill script imports a shared `_helper` without the one canonical path line.

A skill script is installed by copy and run from any directory, so the shared helpers that sit
beside the skills (`_token_input`, `_dashboard_routes`, ...) are reachable only if the script puts
the skills root on `sys.path` first. The line cannot move into a helper: the helper is what it
makes importable. This check keeps the line uniform instead.

A script under `<root>/<skill>/` (not a test, not inside an underscore helper) that imports any
top-level `_name` directory of the root must hold, as a top-level statement of the module and
before its first module-level import of such a directory, exactly

    sys.path.insert(0, str(Path(__file__).resolve().parents[N]))

where N is the number of directories between the script and the root (2 for
`<skill>/scripts/x.py`). A trailing comment is fine. These are findings: a different form, a
wrong N, a late line, no line, a line nested inside `try`, `if`, `with` or a function (the
import can then run without it), and a file that does not parse or cannot be read (it cannot
be checked, so it is never skipped quietly). An import inside a function body is deferred: it
needs the line to exist but does not make a module-level line late.

Files are read as bytes, so a BOM or a coding cookie is honoured; a file in another encoding is
reported as a finding for that file, not a crash.

Usage: check-skill-bootstrap.py [ROOT ...]
  default roots: every `<provider>/skills` directory of the repository that has a `_helper`
  directory (onping, ramp, paypal ...). A provider without one (aha, azdo, google ...) reaches its
  own code another way, has nothing to import from the skills root, and is named on a
  "not covered" line. A ROOT given on the command line must have a `_helper` directory and must
  exist, or the check fails with exit 2 instead of passing on nothing.
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

SKIP_DIRS = {"tests", "__pycache__", "node_modules", ".git", ".claude"}


def _helpers(root: Path) -> set[str]:
    return {p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("_")}


def _bootstrap_depth(node: ast.stmt) -> int | None:
    """N when the statement is the canonical `sys.path.insert(0, str(Path(__file__).resolve().parents[N]))`."""
    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
        return None
    call = node.value
    f = call.func
    if not (
        isinstance(f, ast.Attribute)
        and f.attr == "insert"
        and isinstance(f.value, ast.Attribute)
        and f.value.attr == "path"
        and isinstance(f.value.value, ast.Name)
        and f.value.value.id == "sys"
    ):
        return None
    if len(call.args) != 2 or call.keywords:
        return None
    zero, arg = call.args
    if not (isinstance(zero, ast.Constant) and zero.value == 0):
        return None
    if not (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "str" and len(arg.args) == 1 and not arg.keywords):
        return None
    sub = arg.args[0]
    if not (isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant) and isinstance(sub.slice.value, int)):
        return None
    parents = sub.value
    if not (isinstance(parents, ast.Attribute) and parents.attr == "parents"):
        return None
    resolve = parents.value
    if not (isinstance(resolve, ast.Call) and not resolve.args and isinstance(resolve.func, ast.Attribute) and resolve.func.attr == "resolve"):
        return None
    path_call = resolve.func.value
    if not (
        isinstance(path_call, ast.Call)
        and isinstance(path_call.func, ast.Name)
        and path_call.func.id == "Path"
        and len(path_call.args) == 1
        and isinstance(path_call.args[0], ast.Name)
        and path_call.args[0].id == "__file__"
    ):
        return None
    return sub.slice.value


def _helper_imports(tree: ast.AST, helpers: set[str]) -> list[tuple[int, str, bool]]:
    """(line, helper, deferred) for each import of a shared helper; deferred when it sits in a function body."""
    hits: list[tuple[int, str, bool]] = []

    def visit(node: ast.AST, deferred: bool) -> None:
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top = node.module.split(".")[0]
            if top in helpers:
                hits.append((node.lineno, top, deferred))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in helpers:
                    hits.append((node.lineno, top, deferred))
        inner = deferred or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        for child in ast.iter_child_nodes(node):
            visit(child, inner)

    visit(tree, False)
    return sorted(hits)


def _path_lines(tree: ast.Module) -> list[tuple[int, int, bool]]:
    """(line, N, top_level) for each canonical bootstrap statement anywhere in the file."""
    top = {id(s) for s in tree.body}
    return sorted((s.lineno, d, id(s) in top) for s in ast.walk(tree) if isinstance(s, ast.stmt) and (d := _bootstrap_depth(s)) is not None)


def _parse(path: Path) -> tuple[ast.Module | None, str | None]:
    """The tree, or the reason the file cannot be checked. The bytes go to the parser so a BOM or a coding cookie is honoured."""
    try:
        return ast.parse(path.read_bytes(), filename=str(path)), None
    except SyntaxError as exc:
        return None, f"cannot be checked, it does not parse: {exc.msg} (line {exc.lineno})"
    except (OSError, ValueError, RecursionError, MemoryError) as exc:
        return None, f"cannot be checked, it cannot be read: {type(exc).__name__}: {exc}"


def check_file(rel: Path, tree: ast.Module, helpers: set[str]) -> list[str]:
    imports = _helper_imports(tree, helpers)
    if not imports:
        return []
    line, helper, _ = imports[0]
    want = len(rel.parts) - 1
    canonical = f"sys.path.insert(0, str(Path(__file__).resolve().parents[{want}]))"
    lines = _path_lines(tree)
    top = [(ln, d) for ln, d, is_top in lines if is_top]
    if not top:
        if lines:
            ln = lines[0][0]
            return [f"{rel}:{ln}: the path line is nested inside a block (try, if, with, a function); it must be a top-level statement before the first {helper} import, or the import can run without it"]
        return [f"{rel}:{line}: imports {helper} but has no `{canonical}`"]
    right = [ln for ln, d in top if d == want]
    if not right:
        ln, got = top[0]
        return [f"{rel}:{ln}: parents[{got}] reaches the wrong directory; this file needs parents[{want}]"]
    module_level = [ln for ln, _, deferred in imports if not deferred]
    if module_level and right[0] > module_level[0]:
        return [f"{rel}:{right[0]}: the path line comes after the first {helper} import on line {module_level[0]}"]
    return []


def findings(root: Path) -> list[str]:
    helpers = _helpers(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if not rel_dir.parts:
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("_"))
            continue
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            rel = (Path(dirpath) / name).relative_to(root)
            tree, problem = _parse(Path(dirpath) / name)
            if tree is None:
                out.append(f"{rel}: {problem}")
                continue
            out.extend(check_file(rel, tree, helpers))
    return out


def discover(repo: Path) -> tuple[list[Path], list[Path]]:
    """Every `<provider>/skills` directory in the repository, split into (roots with `_helper` dirs, roots without)."""
    roots = sorted(p for p in repo.glob("*/skills") if p.is_dir() and not p.parent.name.startswith("."))
    return [r for r in roots if _helpers(r)], [r for r in roots if not _helpers(r)]


def _own_path_form(root: Path) -> bool:
    """True when a script under the root edits sys.path itself: the provider reaches its code another way."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py") and b"sys.path.insert" in (Path(dirpath) / name).read_bytes():
                return True
    return False


def _label(root: Path) -> str:
    return f"{root.parent.name}/{root.name}" if root.name == "skills" else root.name


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("roots", nargs="*", type=Path)
    args = p.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    uncovered: list[Path] = []
    if args.roots:
        roots = [r.resolve() for r in args.roots]
        missing = [r for r in roots if not r.is_dir()]
        if missing:
            print(f"FAIL: not a directory: {', '.join(str(r) for r in missing)}", file=sys.stderr)
            return 2
        bare = [r for r in roots if not _helpers(r)]
        if bare:
            print(
                "FAIL: no `_helper` directory beside the skills in "
                + ", ".join(str(r) for r in bare)
                + ". This check covers the shared-helper line only; a skills root whose scripts reach their code another way is not covered.",
                file=sys.stderr,
            )
            return 2
    else:
        roots, uncovered = discover(repo)
        if not roots:
            print(f"FAIL: no `<provider>/skills` directory with a `_helper` directory under {repo}", file=sys.stderr)
            return 2
    found = [f"{_label(r)}/{x}" for r in roots for x in findings(r)]
    print(f"skill bootstrap roots: {', '.join(_label(r) for r in roots)}")
    if uncovered:
        names = [_label(r) + (" [own sys.path form]" if _own_path_form(r) else "") for r in uncovered]
        print(f"not covered (no `_helper` directory, nothing to import): {', '.join(names)}")
    print(f"skill bootstrap findings: {len(found)}")
    for item in found:
        print(f"  {item}")
    if found:
        print("FAIL: a script that imports a shared _helper needs the canonical sys.path line at the right depth.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
