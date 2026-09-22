from watcher.apple import PartAvailability, Store
from watcher.notify import format_available, format_unhealthy, format_recovered

S1 = Store("R623", "Brickell City Centre", "701 S. Miami Avenue", "Miami", "FL",
           "0.63 mi", "Available Today")
S2 = Store("R115", "Lincoln Road", "1021 Lincoln Road", "Miami Beach", "FL",
           "4.33 mi", "Available Today")


def test_available_message_names_config_and_stores():
    msg = format_available(
        PartAvailability("MJW44LL/A", "iPhone 18 Pro Max 256GB Black", [S1, S2]), "33130")
    for expected in ("iPhone 18 Pro Max 256GB Black", "2 stores", "Brickell City Centre",
                     "701 S. Miami Avenue", "0.63 mi", "33130", "apple.com"):
        assert expected in msg


def test_repeat_message_is_marked_as_reminder():
    msg = format_available(
        PartAvailability("M", "iPhone 18 Pro Max 256GB Black", [S1]), "33130", repeat=True)
    assert "reminder" in msg.lower()


def test_single_store_is_not_pluralized():
    msg = format_available(
        PartAvailability("M", "iPhone 18 Pro Max 256GB Black", [S1]), "33130")
    assert "1 store near" in msg and "1 stores" not in msg


def test_long_store_lists_are_truncated():
    stores = [Store(f"R{i}", f"Store {i}", "st", "Miami", "FL", "1 mi", "Today")
              for i in range(20)]
    msg = format_available(PartAvailability("M", "name", stores), "33130")
    assert "20 stores" in msg and "and 10 more" in msg


def test_unhealthy_message_includes_reason():
    msg = format_unhealthy("canary MJQ34LL/A reports 0 stores", 5)
    assert "canary" in msg and "5" in msg


def test_recovered_message():
    assert "recover" in format_recovered().lower()


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_migrated_chat_id_extracted():
    from watcher.notify import migrated_chat_id
    r = _Resp(400, {"ok": False, "parameters": {"migrate_to_chat_id": -1004333816460}})
    assert migrated_chat_id(r) == "-1004333816460"


def test_migrated_chat_id_none_for_other_errors():
    from watcher.notify import migrated_chat_id
    assert migrated_chat_id(_Resp(400, {"ok": False, "description": "chat not found"})) is None
    assert migrated_chat_id(_Resp(200, {"ok": True})) is None
    assert migrated_chat_id(_Resp(400, None, "not json")) is None


def test_send_follows_supergroup_migration(monkeypatch):
    """A group upgrading to a supergroup must not lose the alert."""
    from watcher.notify import Telegram
    import watcher.notify as mod

    calls = []

    def fake_post(url, json, timeout):
        calls.append(json["chat_id"])
        if json["chat_id"] == "-123":
            return _Resp(400, {"ok": False,
                               "parameters": {"migrate_to_chat_id": -1009}})
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(mod.requests, "post", fake_post)
    tg = Telegram("tok", "-123")
    assert tg.send("hello") is True
    assert calls == ["-123", "-1009"]


def test_send_reports_failure_when_not_migration(monkeypatch):
    from watcher.notify import Telegram
    import watcher.notify as mod
    monkeypatch.setattr(mod.requests, "post",
                        lambda url, json, timeout: _Resp(403, {"ok": False}, "forbidden"))
    assert Telegram("tok", "-123").send("hi") is False


# ---------- heartbeat ----------

from datetime import datetime, timezone
from watcher.notify import format_heartbeat

NOW = datetime(2026, 9, 21, 23, 12, 6, tzinfo=timezone.utc)


def _pa(name, stores):
    return PartAvailability("P" + name, name, stores)


def test_heartbeat_shows_time_and_every_part():
    res = [_pa("iPhone 18 Pro Max 256GB Black", []),
           _pa("iPhone 18 Pro Max 256GB Silver", [])]
    msg = format_heartbeat(res, "33130", NOW)
    assert "live" in msg.lower()
    assert "2026-09-21 23:12:06" in msg
    assert "256GB Black" in msg and "256GB Silver" in msg
    assert "33130" in msg


def test_heartbeat_marks_available_parts():
    res = [_pa("iPhone 18 Pro Max 256GB Black", [S1, S2]),
           _pa("iPhone 18 Pro Max 256GB Silver", [])]
    msg = format_heartbeat(res, "33130", NOW)
    assert "✅" in msg and "2 stores" in msg
    assert "▫️" in msg and "none" in msg


def test_heartbeat_includes_canary_state():
    canary = _pa("iPhone 18 Pro 256GB Black", [S1])
    msg = format_heartbeat([], "33130", NOW, canary)
    assert "Canary" in msg and "✓" in msg


def test_heartbeat_flags_unhealthy_canary():
    msg = format_heartbeat([], "33130", NOW, _pa("iPhone 18 Pro 256GB Black", []))
    assert "⚠️" in msg


def test_heartbeat_text_changes_between_checks():
    """Telegram rejects an edit whose text is identical, so the timestamp
    must make consecutive heartbeats differ."""
    res = [_pa("iPhone 18 Pro Max 256GB Black", [])]
    later = datetime(2026, 9, 21, 23, 15, 9, tzinfo=timezone.utc)
    assert format_heartbeat(res, "33130", NOW) != format_heartbeat(res, "33130", later)


# ---------- edit / delete ----------

def test_edit_success(monkeypatch):
    from watcher.notify import Telegram
    import watcher.notify as mod
    monkeypatch.setattr(mod.requests, "post",
                        lambda url, json, timeout: _Resp(200, {"ok": True}))
    assert Telegram("t", "-1").edit("5", "hi") is True


def test_edit_treats_not_modified_as_success(monkeypatch):
    from watcher.notify import Telegram
    import watcher.notify as mod
    monkeypatch.setattr(mod.requests, "post", lambda url, json, timeout: _Resp(
        400, {"ok": False, "description": "Bad Request: message is not modified"}))
    assert Telegram("t", "-1").edit("5", "hi") is True


def test_edit_returns_false_when_message_gone(monkeypatch):
    """A deleted heartbeat must make the caller send a fresh one."""
    from watcher.notify import Telegram
    import watcher.notify as mod
    monkeypatch.setattr(mod.requests, "post", lambda url, json, timeout: _Resp(
        400, {"ok": False, "description": "Bad Request: message to edit not found"}))
    assert Telegram("t", "-1").edit("5", "hi") is False


def test_send_id_returns_message_id(monkeypatch):
    from watcher.notify import Telegram
    import watcher.notify as mod
    monkeypatch.setattr(mod.requests, "post", lambda url, json, timeout: _Resp(
        200, {"ok": True, "result": {"message_id": 4242}}))
    assert Telegram("t", "-1").send_id("hi") == "4242"


def test_send_id_none_on_failure(monkeypatch):
    from watcher.notify import Telegram
    import watcher.notify as mod
    monkeypatch.setattr(mod.requests, "post",
                        lambda url, json, timeout: _Resp(403, {"ok": False}, "nope"))
    assert Telegram("t", "-1").send_id("hi") is None
