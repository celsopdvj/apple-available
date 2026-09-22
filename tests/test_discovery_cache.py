"""The part cache must not outlive a change to the watch configuration."""
import pytest
from watcher.config import WatchTarget
from watcher.__main__ import watch_fingerprint


class FakeCfg:
    def __init__(self, watch, canary="MJQ34LL/A"):
        self.watch = watch
        self.canary_part = canary


T256 = WatchTarget("iPhone 18 Pro Max", "256GB", ["*"])
T2TB = WatchTarget("iPhone 18 Pro Max", "2TB", ["*"])


def test_fingerprint_stable_for_same_config():
    assert watch_fingerprint(FakeCfg([T256])) == watch_fingerprint(FakeCfg([T256]))


def test_fingerprint_ignores_target_order():
    assert watch_fingerprint(FakeCfg([T256, T2TB])) == watch_fingerprint(FakeCfg([T2TB, T256]))


def test_fingerprint_changes_when_target_added():
    assert watch_fingerprint(FakeCfg([T256])) != watch_fingerprint(FakeCfg([T256, T2TB]))


def test_fingerprint_changes_when_colors_change():
    narrowed = WatchTarget("iPhone 18 Pro Max", "256GB", ["Black"])
    assert watch_fingerprint(FakeCfg([T256])) != watch_fingerprint(FakeCfg([narrowed]))


def test_fingerprint_changes_when_canary_changes():
    assert watch_fingerprint(FakeCfg([T256])) != watch_fingerprint(FakeCfg([T256], "MJW44LL/A"))
