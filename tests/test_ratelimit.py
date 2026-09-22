"""HTTP 541 is Apple telling us to slow down. Retrying it in-process turns
one blocked check into three requests in six seconds, which keeps the limiter
tripped -- the failure mode that took the watcher offline for ~10 minutes."""
import pytest
import watcher.apple as apple
from watcher.apple import RateLimited, TransientError, _get


class _Resp:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("should not reach raise_for_status in these tests")


class _Session:
    def __init__(self, status):
        self.status = status
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return _Resp(self.status)


def test_541_raises_immediately_without_retrying():
    s = _Session(541)
    with pytest.raises(RateLimited):
        _get("https://example.test", None, s)
    assert s.calls == 1, f"retried a rate limit {s.calls} times"


def test_rate_limited_is_a_transient_error():
    """Callers catching TransientError must still treat it as a failed run."""
    assert issubclass(RateLimited, TransientError)


def test_500_still_retries_three_times(monkeypatch):
    monkeypatch.setattr(apple.time, "sleep", lambda *_: None)
    s = _Session(503)
    with pytest.raises(TransientError):
        _get("https://example.test", None, s)
    assert s.calls == 3


def test_success_returns_first_time():
    s = _Session(200)
    assert _get("https://example.test", None, s).status_code == 200
    assert s.calls == 1
