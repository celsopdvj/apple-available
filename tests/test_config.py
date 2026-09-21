import pytest
from pathlib import Path
from watcher.config import load_config, ConfigError


def _cfg(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(Path("config.toml").read_text())
    return p


def test_loads_all_fields(tmp_path):
    cfg = load_config(_cfg(tmp_path), {"TELEGRAM_BOT_TOKEN": "tok"})
    assert cfg.zip == "33130"
    assert cfg.model == "iPhone 18 Pro Max"
    assert cfg.capacity == "256GB"
    assert cfg.colors == ["*"]
    assert cfg.canary_part == "MJQ34LL/A"
    assert cfg.chat_id == "-5597962862"
    assert cfg.bot_token == "tok"
    assert cfg.repeat_minutes == 30
    assert cfg.failure_alert_threshold == 5


def test_missing_token_raises(tmp_path):
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config(_cfg(tmp_path), {})


def test_env_chat_id_overrides_file(tmp_path):
    cfg = load_config(_cfg(tmp_path), {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "-999"})
    assert cfg.chat_id == "-999"
