"""generate_report.py stays a requests-only PEP 723 script: no spreadsheet library, open format only."""

from __future__ import annotations

import ast
import re
import json

from conftest import SCRIPT

SPREADSHEET_LIBS = {"openpyxl", "xlsxwriter", "xlwt", "xlrd", "pandas", "pyexcel", "xlsx2csv", "pylightxl"}


def _header() -> dict:
    block = re.search(r"(?m)^# /// script\n((?:#.*\n)+?)# ///$", SCRIPT.read_text())
    assert block, "no PEP 723 header"
    text = "\n".join(line[2:] if line.startswith("# ") else line[1:] for line in block.group(1).splitlines())
    deps = re.search(r"(?s)^dependencies\s*=\s*(\[.*?\])", text, re.M)
    assert deps, "no dependencies line in the PEP 723 header"
    return {"dependencies": json.loads(deps.group(1))}  # a TOML string list of plain strings is JSON


def test_dependencies_are_exactly_requests():
    assert _header()["dependencies"] == ["requests"]


def test_header_lists_no_spreadsheet_requirement():
    deps = " ".join(_header()["dependencies"]).lower()
    assert not any(lib in deps for lib in SPREADSHEET_LIBS)


def test_the_script_imports_no_spreadsheet_library():
    imported = set()
    for node in ast.walk(ast.parse(SCRIPT.read_text())):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & SPREADSHEET_LIBS
