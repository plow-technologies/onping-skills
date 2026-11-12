"""Offline harness for the onping-report tests: a fake `requests.post` and a runner for `main`.

No test here touches the network: sockets are disabled for every test, and the fake returns the
server's real shape for a good report request, a JSON string (the URL, quoted).
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_report.py"
SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
ENV_TOKEN = "env-token.sample.value"
START, END = "2026-02-22T06:00:00Z", "2026-02-25T06:00:00Z"
URL = "https://reports.example.invalid/s3/availableFile/user/2026-02-25/report.xlsx"


class Reply:
    def __init__(self, status: int = 200, text: str = ""):
        self.status_code, self.text = status, text


def ok(url: str = URL) -> Reply:
    return Reply(200, '"' + url + '"')  # the server answers a JSON string


@dataclass
class Result:
    code: object
    out: str
    err: str
    calls: list = field(default_factory=list)  # one dict per requests.post call


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def report_module():
    spec = importlib.util.spec_from_file_location("_report_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_report_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def run(monkeypatch, capsys, report_module):
    """run(argv, replies) -> Result. `replies` are consumed one per post; an exception instance is raised.

    time.sleep fails the test if called: the script has no wait between attempts, and a test that pins
    that must see a sleep as a change."""
    def no_sleep(*a, **k):
        raise AssertionError("time.sleep was called")

    monkeypatch.setattr(time, "sleep", no_sleep)

    def runner(argv, replies=(), env=ENV_TOKEN):
        queue = list(replies)
        calls: list = []

        def fake_post(url, json=None, headers=None, timeout=None, **kw):
            calls.append({"url": url, "json": json, "headers": dict(headers or {}), "timeout": timeout, **kw})
            if not queue:
                raise AssertionError("more requests than replies")
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        monkeypatch.setattr(report_module.requests, "post", fake_post)
        if env is None:
            monkeypatch.delenv("ONPING_ACCESS_TOKEN", raising=False)
        else:
            monkeypatch.setenv("ONPING_ACCESS_TOKEN", env)
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), *argv])
        code = 0
        try:
            report_module.main()
        except SystemExit as e:
            code = e.code
        cap = capsys.readouterr()
        return Result(code, cap.out, cap.err, calls)

    return runner
