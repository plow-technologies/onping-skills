#!/usr/bin/env python3
"""Fail when an OnPing skill takes the access token as a command-line argument.

Four kinds of finding, counted separately:
  script    a skill .py that declares an add_argument whose option name, dest or (folded) dynamic name
            is token-like (`token`, `access_token`, `api_token`, `bearer`, `tok`, `auth`, `jwt` ...;
            `--token-stdin`, `--token-file` and the like are fine), that builds an option name the
            check cannot resolve, or that binds a token-named variable (also inside a tuple or
            starred unpacking) to anything read from sys.argv, including slices and `argv`
  password  a skill .py or markdown that puts a database password on a command line: a string
            containing `PGPASSWORD=` (the password then shows in `ps` on every machine the command
            reaches), an add_argument whose option name or dest is password-like (`--password`,
            `--db-passwd`, `--pgpassword`, `--dbPassword`, `--pw`; `--password-stdin`, `--password-file`,
            `--password-prompt` and `--pwd` are fine), or a string that puts a password in a URL
            (`postgresql://u:{pw}@h/db`, `user:{password}@`)
  document  a markdown example that shows the token as an argument ("$ACCESS_TOKEN",
            `login.py)"`, a bare ACCESS_TOKEN word on a command or Input line)
  hint      a string in a skill's Python that prints one of the same forms, or an f-string that
            interpolates a token-named attribute (`{args.token}`) outside an Authorization header

Allowlist: `_token_input` (documents the deprecated first-word form), any tests directory, and
`ml-model-cost-sweep/SKILL.md`, and CHANGELOG.md (history).

Usage: check-token-argv.py [--report] [--list] [ROOT ...]
  default roots: onping onping-charts under the repository root
  --report  print the counts and exit 0 whatever was found (enforcing is the default)
  --list    print every finding (always printed when enforcing and something was found)
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path

ALLOW_DIRS = {"_token_input", "tests", "__pycache__", "node_modules", ".git", ".claude"}
ALLOW_FILES = {"ml-model-cost-sweep/SKILL.md", "CHANGELOG.md"}
TOKEN_WORDS = {"token", "tokens", "tok", "bearer", "auth", "jwt", "apikey", "authorization"}
PASSWORD_STEMS = ("password", "passwd", "passphrase")
PASSWORD_ABBREVIATIONS = {"pw"}
NOT_A_PASSWORD_VALUE = {"prompt", "prompts", "ask", "hint"}
PGPASSWORD_ASSIGN = re.compile(r"PGPASSWORD\s*=")
URL_CREDENTIALS = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s@:]*:([^/\s@]+)@")
BARE_CREDENTIALS = re.compile(r"[\w.%+-]+:\{([^{}]*)\}@")
NOT_A_SECRET_WORDS = {"stdin", "file", "path", "env", "url", "endpoint", "max", "min", "source", "count", "limit", "usage", "budget"}

QUOTED_VAR = re.compile(r'"\$\{?(?:ACCESS_)?TOKEN\}?"')
QUOTED_LOGIN = re.compile(r"login\.py\)\"")
BARE_VAR = re.compile(r"(?<![\w=])\$\{?(?:ACCESS_)?TOKEN\}?(?![\w=])")
BARE_WORD = re.compile(r"(?<![\w$<{])(?:ACCESS_TOKEN|<token>|<access[-_]token>|<ACCESS_TOKEN>)(?![\w=])", re.I)
HINT = re.compile(r"\"\$\{?(?:ACCESS_)?TOKEN\}?\"|\$\{?(?:ACCESS_)?TOKEN\}?(?![\w=])|<token>|<ACCESS_TOKEN>|login\.py\)\"|\$\(uv run [^)]*login\.py\)")


def _skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    return any(part in ALLOW_DIRS for part in rel.parts) or any(rel.as_posix().endswith(a) for a in ALLOW_FILES)


def _walk(root: Path, suffix: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in ALLOW_DIRS)
        for name in sorted(filenames):
            if name.endswith(suffix):
                yield Path(dirpath) / name


def _words(name: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    words = {w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if w}
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    if compact.endswith(("token", "bearer", "apikey")):
        words.add(compact[-5:] if compact.endswith("token") else compact[-6:] if compact.endswith("bearer") else "apikey")
    return words


def token_like(name: str) -> bool:
    """True for a name that reads as an access token: `token`, `accessToken`, `api_token`, `bearer`, `tok`, `auth`."""
    words = _words(name)
    return bool(words & TOKEN_WORDS) and not words & NOT_A_SECRET_WORDS


_UNKNOWN = "\0"


def _fold(node: ast.AST, env: dict[str, str] | None = None) -> str | None:
    """The text a string expression builds, with \\0 for the parts that are not known; None when it is not text."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name) and env and node.id in env:
        return env[node.id]
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) else (_fold(v.value, env) or _UNKNOWN) if isinstance(v, ast.FormattedValue) else _UNKNOWN
            for v in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        left, right = _fold(node.left, env), _fold(node.right, env)
        if isinstance(node.op, ast.Add):
            return None if left is None or right is None else left + right
        return left
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        base = _fold(node.func.value, env)
        if base is None:
            return None
        if node.func.attr == "format":
            return base
        if node.func.attr == "join" and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
            parts = [_fold(e, env) or _UNKNOWN for e in node.args[0].elts]
            return base.join(parts)
        if node.func.attr in ("lower", "upper", "strip", "replace", "removeprefix", "removesuffix"):
            return base
    return None


def _identifiers(node: ast.AST) -> list[str]:
    return [n.id for n in ast.walk(node) if isinstance(n, ast.Name)] + [n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)]


def _option_name_problem(node: ast.AST, env: dict[str, str]) -> str | None:
    text = _fold(node, env)
    if text is not None:
        names = [w for w in re.split(r"\s+", text) if w]
        return next((w.replace(_UNKNOWN, "*") for w in names if token_like(w.replace(_UNKNOWN, " "))), None)
    if isinstance(node, ast.Starred):
        return "<unresolved option names>"
    ids = _identifiers(node)
    hit = next((i for i in ids if token_like(i)), None)
    return f"<{hit}>" if hit else "<unresolved option name>"


def _is_argv(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "argv" and isinstance(node.value, ast.Name) and node.value.id == "sys"
    return isinstance(node, ast.Name) and node.id == "argv"


def _reads_argv(node: ast.AST) -> bool:
    return any(_is_argv(n) for n in ast.walk(node))


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for e in target.elts for n in _target_names(e)]
    return []


def _string_env(tree: ast.AST) -> dict[str, str]:
    """Names bound once to a string constant, so `name = "tok"; add_argument(f"--{name}en")` folds."""
    env: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    env[t.id] = n.value.value
    return env


def _py_files(root: Path):
    for path in _walk(root, ".py"):
        if not _skip(path, root):
            yield path


def script_findings(root: Path) -> list[str]:
    out = []
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        rel = path.relative_to(root)
        env = _string_env(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                problems = [p for p in (_option_name_problem(a, env) for a in node.args) if p]
                for kw in node.keywords:
                    if kw.arg in ("dest", "metavar"):
                        text = _fold(kw.value, env)
                        if text is not None and token_like(text.replace(_UNKNOWN, " ")):
                            problems.append(f"{kw.arg}={text!r}")
                if problems:
                    out.append(f"{rel}:{node.lineno}: add_argument({problems[0]})")
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.AugAssign)):
                value = node.value
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if value is not None and _reads_argv(value):
                    names = [n for t in targets for n in _target_names(t)]
                    bad = next((n for n in names if token_like(n)), None)
                    if bad:
                        out.append(f"{rel}:{node.lineno}: {bad} = sys.argv[...]")
    return out


def document_findings(root: Path) -> list[str]:
    out = []
    for path in _walk(root, ".md"):
        if _skip(path, root):
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "Bearer" in line or "Authorization" in line or "curl " in line:
                continue
            hit = QUOTED_VAR.search(line) or QUOTED_LOGIN.search(line) or BARE_VAR.search(line)
            if not hit and (".py" in line or "**Input:**" in line or line.lstrip().startswith(("Usage", "usage"))):
                hit = BARE_WORD.search(line)
            if hit:
                out.append(f"{path.relative_to(root)}:{n}: {line.strip()[:110]}")
    return out


def password_like(name: str) -> bool:
    """True for a name that reads as a password: `password`, `db_password`, `--pgpassword`, `--dbPasswd`, `--pw`.

    `--password-stdin`, `--password-file`, `--password-prompt` (a switch, not a value) and `--pwd` (print working
    directory) are not passwords.
    """
    words = _words(name)
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    exempt = NOT_A_SECRET_WORDS | NOT_A_PASSWORD_VALUE
    if words & exempt or compact.endswith(tuple(exempt)):
        return False
    return any(stem in compact for stem in PASSWORD_STEMS) or bool(words & PASSWORD_ABBREVIATIONS) or compact.endswith(tuple(PASSWORD_ABBREVIATIONS))


def _render(node: ast.AST) -> str | None:
    """The text a string expression builds, with {expr} wherever a value is spliced in; None when it is not text."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}" for v in node.values if isinstance(v, (ast.Constant, ast.FormattedValue)))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _render(node.left), _render(node.right)
        if left is None and right is None:
            return None
        return (left if left is not None else "{" + ast.unparse(node.left) + "}") + (right if right is not None else "{" + ast.unparse(node.right) + "}")
    return None


def url_password(text: str) -> bool:
    """True for text that carries a password in a URL: `scheme://user:secret@host`, or `user:{password}@`."""
    if URL_CREDENTIALS.search(text):
        return True
    return any(password_like(m.group(1)) for m in BARE_CREDENTIALS.finditer(text))


def password_findings(root: Path) -> list[str]:
    out = []
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        rel = path.relative_to(root)
        url_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and PGPASSWORD_ASSIGN.search(node.value):
                out.append(f"{rel}:{node.lineno}: PGPASSWORD= in a string")
            elif isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)) and node.lineno not in url_lines:
                text = _render(node)
                if text is not None and url_password(text):
                    url_lines.add(node.lineno)
                    out.append(f"{rel}:{node.lineno}: a password inside a URL string")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                texts = [_fold(a) for a in node.args] + [_fold(kw.value) for kw in node.keywords if kw.arg == "dest"]
                names = [w for t in texts if t is not None for w in t.split()]
                hit = next((n for n in names if password_like(n)), None)
                if hit:
                    out.append(f"{rel}:{node.lineno}: add_argument({hit})")
    for path in _walk(root, ".md"):
        if _skip(path, root):
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if PGPASSWORD_ASSIGN.search(line):
                out.append(f"{path.relative_to(root)}:{n}: {line.strip()[:110]}")
    return out


def _is_header_text(parts: list[str]) -> bool:
    joined = " ".join(parts)
    return "Bearer" in joined or "Authorization" in joined


def hint_findings(root: Path) -> list[str]:
    out = []
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        rel = path.relative_to(root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "Bearer" not in node.value:
                m = HINT.search(node.value)
                if m:
                    out.append(f"{rel}:{node.lineno}: {m.group(0)}")
            elif isinstance(node, ast.JoinedStr):
                pieces = [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
                if _is_header_text(pieces):
                    continue
                for v in node.values:
                    if isinstance(v, ast.FormattedValue):
                        hit = next((n.attr for n in ast.walk(v.value) if isinstance(n, ast.Attribute) and token_like(n.attr)), None)
                        if hit:
                            out.append(f"{rel}:{node.lineno}: f-string interpolates .{hit}")
                            break
    return out


def run(roots: list[Path]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {"script": [], "document": [], "hint": [], "password": []}
    for root in roots:
        found["script"] += [f"{root.name}/{x}" for x in script_findings(root)]
        found["document"] += [f"{root.name}/{x}" for x in document_findings(root)]
        found["hint"] += [f"{root.name}/{x}" for x in hint_findings(root)]
        found["password"] += [f"{root.name}/{x}" for x in password_findings(root)]
    return found


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("roots", nargs="*", type=Path)
    p.add_argument("--report", action="store_true", help="never fail")
    p.add_argument("--list", action="store_true", help="print every finding")
    args = p.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    roots = [r.resolve() for r in args.roots] or [repo / "onping", repo / "onping-charts"]
    found = run([r for r in roots if r.is_dir()])
    total = sum(len(v) for v in found.values())
    print("command-line secret findings: " + ", ".join(f"{k} {len(v)}" for k, v in found.items()) + f" (total {total})")
    if args.list or (total and not args.report):
        for kind, items in found.items():
            for item in items:
                print(f"  [{kind}] {item}")
    if total and not args.report:
        print("FAIL: the access token must come from $ONPING_ACCESS_TOKEN or --token-stdin, and a database password from stdin, never an argument.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
