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
