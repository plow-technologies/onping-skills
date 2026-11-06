"""Status handling of the shared event-table HTTP helper (_event_table_routes/event_table_http.py).

Run from onping/skills:
    uv run --with pytest --with requests pytest -q _event_table_routes/tests
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _event_table_routes import event_table_http as eh  # noqa: E402

HTML = "<!DOCTYPE html><html><body>429 Too Many Requests</body></html>"


def answer(monkeypatch, status, text, *, history=(), url="https://onping.plowtech.net/event/table/export/x"):
    sent = []

    def request(method, url_, **kw):
        sent.append((method, url_))
        return SimpleNamespace(status_code=status, text=text, history=list(history), url=url)

    monkeypatch.setattr(eh.requests, "request", request)
    return sent


@pytest.mark.parametrize("body", [HTML, '{"error": "slow down"}', ""])
def test_a_429_keeps_its_status_whatever_the_body(monkeypatch, body):
    sent = answer(monkeypatch, 429, body)
    with pytest.raises(eh.EventTableError) as e:
        eh.get_text("T", "GET /event/table/export/{filename}", path_params={"filename": "x"})
    assert e.value.status == 429 and "429" in str(e.value)
    assert len(sent) == 1                       # never resent


def test_a_429_after_a_redirect_is_still_a_429(monkeypatch):
    answer(monkeypatch, 429, HTML, history=[object()], url="https://onping.plowtech.net/auth/login")
    with pytest.raises(eh.EventTableError) as e:
        eh.post_json("T", "POST /event/table/config", {})
    assert e.value.status == 429


def test_a_200_html_page_is_still_the_expired_token_failure(monkeypatch):
    answer(monkeypatch, 200, HTML)
    with pytest.raises(eh.EventTableError) as e:
        eh.post_json("T", "POST /event/table/config", {})
    assert e.value.status is None and "received HTML" in str(e.value)
