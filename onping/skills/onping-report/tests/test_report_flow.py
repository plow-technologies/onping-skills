"""Flow of onping-report with a fake requests.post: output, exit codes, retries, token handling.

The fake returns what the server returns for a good request, a JSON string. time.sleep fails the
test when called, which pins the current rule that a retry waits for nothing.
"""

from __future__ import annotations

import pytest

from conftest import END, ENV_TOKEN, START, URL, Reply, ok

ARGS = [START, END, "500019"]
LEGACY = "legacy-token.sample.value"


@pytest.mark.parametrize("extra", [[], ["--format", "csv"], ["--format", "xlsx"]])
def test_success_prints_only_the_url_and_exits_0(run, extra):
    r = run([*ARGS, *extra], [ok()])
    assert r.code == 0
    assert r.out == URL + "\n"
    assert len(r.calls) == 1
    assert ENV_TOKEN not in r.out + r.err


def test_request_goes_to_the_report_route_with_the_bearer_and_a_120s_timeout(run, report_module):
    r = run(ARGS, [ok()])
    call = r.calls[0]
    assert call["url"] == report_module.REPORT_URL == "https://onping.plowtech.net/tachdb/report"
    assert call["headers"]["Authorization"] == f"Bearer {ENV_TOKEN}"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["timeout"] == 120


def test_500_is_not_retried_and_exits_1(run):
    r = run(ARGS, [Reply(500, "boom")])
    assert (r.code, len(r.calls)) == (1, 1)
    assert r.out == ""
    assert "boom" in r.err


def test_401_every_time_is_sent_three_times_without_a_sleep_and_exits_1(run):
    r = run(ARGS, [Reply(401, "no")] * 3)
    assert (r.code, len(r.calls)) == (1, 3)
    assert r.out == ""
    assert "3 attempts" in r.err


def test_403_then_200_prints_the_url_after_two_requests(run):
    r = run(ARGS, [Reply(403, "no"), ok()])
    assert (r.code, len(r.calls)) == (0, 2)
    assert r.out == URL + "\n"


@pytest.mark.parametrize("status", [300, 302, 400, 404, 429, 499])
def test_every_status_from_300_to_499_is_retried(run, status):
    r = run(ARGS, [Reply(status, "x"), ok()])
    assert (r.code, len(r.calls)) == (0, 2)


@pytest.mark.parametrize("status", [199, 201, 204, 500, 502, 503])
def test_other_non_200_statuses_are_not_retried(run, status):
    r = run(ARGS, [Reply(status, "x")])
    assert (r.code, len(r.calls)) == (1, 1)


def test_the_retry_budget_is_shared_across_statuses(run):
    r = run(ARGS, [Reply(401), Reply(429), Reply(403)])
    assert (r.code, len(r.calls)) == (1, 3)


def test_a_200_json_object_is_not_a_url_and_exits_1(run):
    r = run(ARGS, [Reply(200, '{"error": "x"}')])
    assert (r.code, len(r.calls)) == (1, 1)
    assert r.out == ""
    assert "Unexpected decoded result" in r.err


def test_a_200_json_string_that_is_not_a_url_exits_1(run):
    r = run(ARGS, [Reply(200, '"nope"')])
    assert r.code == 1 and r.out == ""


def test_a_200_body_that_is_not_json_exits_1(run):
    r = run(ARGS, [Reply(200, "<html>login</html>")])
    assert r.code == 1 and r.out == ""
    assert "Failed to decode" in r.err


def test_a_request_exception_exits_1_with_request_error(run):
    r = run(ARGS, [ConnectionError("down")])
    assert (r.code, len(r.calls)) == (1, 1)
    assert "Request error" in r.err and r.out == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["not-a-date", END, "1"],
        [START, END],
        [START, END, "abc"],
        [START, END, "1", "--step", "x"],
        [START, END, "1", "--format"],
    ],
)
def test_usage_errors_exit_2_and_send_nothing(run, argv):
    r = run(argv)
    assert r.code == 2 and r.calls == []


def test_no_token_exits_2_and_sends_nothing(run):
    r = run(ARGS, env=None)
    assert r.code == 2 and r.calls == []


# ---- token contract with the new option -------------------------------------------------------

def test_a_token_shaped_first_word_with_format_xlsx_is_read_as_an_old_form_line(run):
    r = run([LEGACY, *ARGS, "--format", "xlsx"], [ok()])
    assert r.code == 0 and len(r.calls) == 1
    call = r.calls[0]
    assert call["headers"]["Authorization"] == f"Bearer {LEGACY}"  # the environment token is ignored
    assert ENV_TOKEN not in str(call["headers"])
    assert LEGACY not in str(call["json"])
    assert call["json"]["startDate"] == START and call["json"]["endDate"] == END
    assert call["json"]["format"] == "xlsx"
    assert "deprecated" in r.err.lower()
    assert LEGACY not in r.err and LEGACY not in r.out


def test_the_token_never_appears_in_the_body_for_either_format(run):
    for extra in ([], ["--format", "xlsx"]):
        r = run([*ARGS, *extra], [ok()])
        assert ENV_TOKEN not in str(r.calls[0]["json"])


def test_token_stdin_with_format_xlsx(run, monkeypatch):
    import io, sys
    monkeypatch.setattr(sys, "stdin", io.StringIO("stdin-token.sample.value\n"))
    r = run([*ARGS, "--format", "xlsx", "--token-stdin"], [ok()], env=None)
    assert r.code == 0
    assert r.calls[0]["headers"]["Authorization"] == "Bearer stdin-token.sample.value"
