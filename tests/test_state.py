from datetime import datetime, timedelta, timezone
import pytest
from watcher.apple import PartAvailability, Store
from watcher.state import State, decide, record_failure, record_success

T0 = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
STORE = Store("R623", "Brickell City Centre", "701 S. Miami Avenue",
              "Miami", "FL", "0.63 mi", "Available Today")


def avail(part, stores):
    return PartAvailability(part, f"name-{part}", stores)


def test_first_time_available_is_a_transition():
    d = decide(State.empty(), {"A": avail("A", [STORE])}, T0, 30)
    assert d.newly_available == ["A"] and d.repeats == []


def test_unavailable_stays_silent():
    d = decide(State.empty(), {"A": avail("A", [])}, T0, 30)
    assert d.newly_available == [] and d.repeats == []


def test_still_available_before_interval_is_silent():
    st = State.empty()
    res = {"A": avail("A", [STORE])}
    decide(st, res, T0, 30)
    d = decide(st, res, T0 + timedelta(minutes=10), 30)
    assert d.newly_available == [] and d.repeats == []


def test_still_available_after_interval_repeats():
    st = State.empty()
    res = {"A": avail("A", [STORE])}
    decide(st, res, T0, 30)
    d = decide(st, res, T0 + timedelta(minutes=31), 30)
    assert d.newly_available == [] and d.repeats == ["A"]


def test_going_away_clears_timer_and_reports():
    st = State.empty()
    decide(st, {"A": avail("A", [STORE])}, T0, 30)
    d = decide(st, {"A": avail("A", [])}, T0 + timedelta(minutes=5), 30)
    assert d.went_away == ["A"]
    d2 = decide(st, {"A": avail("A", [STORE])}, T0 + timedelta(minutes=6), 30)
    assert d2.newly_available == ["A"]


def test_failure_counter_increments():
    st = State.empty()
    assert [record_failure(st) for _ in range(6)] == [1, 2, 3, 4, 5, 6]


def test_success_after_failures_signals_recovery():
    st = State.empty()
    for _ in range(5):
        record_failure(st)
    st["alerted_unhealthy"] = True
    assert record_success(st) is True
    assert record_success(st) is False
    assert st["consecutive_failures"] == 0


def test_round_trips_through_disk(tmp_path):
    st = State.empty()
    decide(st, {"A": avail("A", [STORE])}, T0, 30)
    p = tmp_path / "state.json"
    st.save(p)
    assert State.load(p)["parts"]["A"]["available"] is True


def test_load_missing_file_returns_empty(tmp_path):
    assert State.load(tmp_path / "nope.json")["parts"] == {}


def test_load_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert State.load(p)["parts"] == {}


def test_empty_state_has_watch_fingerprint_slot():
    assert "watch_fingerprint" in State.empty()
