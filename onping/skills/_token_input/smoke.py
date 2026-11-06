"""Post-parse smoke helper: run a script's main() with the HTTP layer faked and the real typed arguments.

`Contract` only exercises parsing. This runs the code after parsing, where a value that is now an int
(or a str) meets `str.replace`, string joins and helper signatures, and records the requests it sent.

    res = run_main(script, ["1234", "--output", str(out)], monkeypatch, responder=lambda m, u, kw: {...})
    assert res.exc is None and "/1234" in res.calls[0].url
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests

from _token_input import token_source

TOKEN = "tok.smoke.value"


@dataclass
class Call:
    method: str
    url: str
    kwargs: dict


@dataclass
class Result:
    calls: list[Call] = field(default_factory=list)
    code: object = None
    exc: BaseException | None = None


class FakeResponse:
    def __init__(self, url: str, body):
        self.url = url
        self.status_code = 200
        self.ok = True
        self.reason = "OK"
        self.history = []
        self.encoding = "utf-8"
        self.cookies = {}
        if isinstance(body, bytes):
            self.content = body
            self.headers = {"Content-Type": "application/octet-stream"}
        else:
            self.content = json.dumps(body).encode()
            self.headers = {"Content-Type": "application/json"}
        self._body = body

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self):
        if isinstance(self._body, bytes):
            raise ValueError("not json")
        return self._body

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        yield self.content

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _load(script: Path):
    name = f"_smoke_{script.parent.parent.name}_{script.stem}".replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_main(script: Path | str, argv: list[str], monkeypatch, *, responder=None, cwd=None, env_token: str | None = TOKEN) -> Result:
    """Run the script's main with `$ONPING_ACCESS_TOKEN` set and every `requests` call answered by `responder`.

    `responder(method, url, kwargs)` returns a JSON-able body or bytes; the default answers `{}`.
    A SystemExit is reported in `code`; any other exception in `exc`."""
    script = Path(script)
    res = Result()
    respond = responder or (lambda m, u, kw: {})

    def make(method):
        def fake(*args, **kw):
            if method == "REQUEST":
                m, url = args[0].upper(), args[1]
            else:
                m, url = method, args[0] if args else kw.get("url", "")
            res.calls.append(Call(m, url, kw))
            return FakeResponse(url, respond(m, url, kw))

        return fake

    for m in ("get", "post", "put", "delete", "patch"):
        monkeypatch.setattr(requests, m, make(m.upper()))
    monkeypatch.setattr(requests, "request", make("REQUEST"))

    class FakeSession:
        def __init__(self, *a, **k):
            self.headers = {}

        def request(self, method, url, **kw):
            return make("REQUEST")(method, url, **kw)

        def get(self, url, **kw):
            return make("GET")(url, **kw)

        def post(self, url, **kw):
            return make("POST")(url, **kw)

        def mount(self, *a, **k):
            return None

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(requests, "Session", FakeSession)
    if env_token is None:
        monkeypatch.delenv(token_source.ACCESS_TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(token_source.ACCESS_TOKEN_ENV, env_token)
    monkeypatch.setattr(sys, "argv", [str(script), *argv])
    if cwd is not None:
        monkeypatch.chdir(cwd)
    mod = _load(script)
    try:
        params = inspect.signature(mod.main).parameters
        res.code = mod.main(list(argv)) if params else mod.main()
    except SystemExit as e:
        res.code = e.code
    except BaseException as e:  # noqa: BLE001 - the point is to surface any crash
        res.exc = e
    return res
