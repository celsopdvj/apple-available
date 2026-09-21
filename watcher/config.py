from __future__ import annotations
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigError(Exception):
    """Configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    zip: str
    model: str
    capacity: str
    colors: list[str]
    canary_part: str
    chat_id: str
    bot_token: str
    jitter_seconds: int
    repeat_minutes: int
    discovery_ttl_hours: int
    failure_alert_threshold: int


def load_config(path: Path, env: Mapping[str, str]) -> Config:
    try:
        raw = tomllib.loads(Path(path).read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file is not valid TOML: {exc}") from exc

    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "TELEGRAM_BOT_TOKEN is not set. Put it in .env (mode 600); "
            "get one from @BotFather."
        )

    polling = raw.get("polling", {})
    chat_id = env.get("TELEGRAM_CHAT_ID") or raw["telegram"]["chat_id"]
    return Config(
        zip=str(raw["location"]["zip"]),
        model=raw["watch"]["model"],
        capacity=raw["watch"]["capacity"],
        colors=list(raw["watch"]["colors"]),
        canary_part=raw["canary"]["part"],
        chat_id=str(chat_id),
        bot_token=token,
        jitter_seconds=int(polling.get("jitter_seconds", 45)),
        repeat_minutes=int(polling.get("repeat_minutes", 30)),
        discovery_ttl_hours=int(polling.get("discovery_ttl_hours", 24)),
        failure_alert_threshold=int(polling.get("failure_alert_threshold", 5)),
    )
