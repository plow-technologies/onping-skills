"""Write pace for the data-table skills: one process leaves at least MIN_GAP_S seconds between
its write POSTs (routes marked `writes`).

The OnPing request budget is shared by every caller. The gap runs from the answer of the previous
write to the send of the next one; reads are not paced. A 429 is never resent (`lj_http` raises
`RateLimited`); `sent()` is the count of write POSTs this process has sent, for the stop message.
Same behaviour as `_dashboard_routes.pace`, kept separate so this helper imports nothing from the
dashboard helper.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

MIN_GAP_S = 10.0

clock = time.monotonic
sleep = time.sleep
_last_answer: float | None = None
_sent = 0


def wait() -> float:
    if _last_answer is None:
        return 0.0
    left = MIN_GAP_S - (clock() - _last_answer)
    if left <= 0:
        return 0.0
    sleep(left)
    return left


@contextmanager
def post() -> Iterator[None]:
    global _sent, _last_answer
    wait()
    _sent += 1
    try:
        yield
    finally:
        _last_answer = clock()


def sent() -> int:
    return _sent


def reset() -> None:
    global _last_answer, _sent
    _last_answer = None
    _sent = 0
