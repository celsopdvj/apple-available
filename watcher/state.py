from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


class State(dict):
    """Plain JSON-backed state. Part states are only ever advanced by a run
    that completed with a healthy canary."""

    @classmethod
    def empty(cls) -> "State":
        return cls({
            "parts": {},
            "products": {},
            "products_fetched_at": None,
            "watch_fingerprint": None,
            "consecutive_failures": 0,
            "alerted_unhealthy": False,
        })

    @classmethod
    def load(cls, path: Path) -> "State":
        try:
            data = json.loads(Path(path).read_text())
        except FileNotFoundError:
            return cls.empty()
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("state file unreadable (%s); starting fresh", exc)
            return cls.empty()
        base = cls.empty()
        base.update(data)
        return base

    def save(self, path: Path) -> None:
        path = Path(path)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self, indent=2, sort_keys=True))
        tmp.replace(path)  # atomic; a crash cannot leave a half-written state


@dataclass
class Decision:
    newly_available: list[str] = field(default_factory=list)
    repeats: list[str] = field(default_factory=list)
    went_away: list[str] = field(default_factory=list)


def decide(state: State, results, now: datetime, repeat_minutes: int) -> Decision:
    parts = state.setdefault("parts", {})
    d = Decision()

    for part, res in sorted(results.items()):
        prev = parts.get(part, {})
        was = bool(prev.get("available"))

        if res.available and not was:
            d.newly_available.append(part)
            last_notified = now
        elif res.available and was:
            last = prev.get("last_notified_at")
            last_dt = datetime.fromisoformat(last) if last else None
            if last_dt is None or now - last_dt >= timedelta(minutes=repeat_minutes):
                d.repeats.append(part)
                last_notified = now
            else:
                last_notified = last_dt
        else:
            if was:
                d.went_away.append(part)
            last_notified = None

        parts[part] = {
            "available": res.available,
            "store_count": res.store_count,
            "name": res.name,
            "last_notified_at": last_notified.isoformat() if last_notified else None,
            "last_seen_at": now.isoformat(),
        }

    return d


def record_failure(state: State) -> int:
    state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
    return state["consecutive_failures"]


def record_success(state: State) -> bool:
    """Returns True if this success ends a previously-alerted unhealthy streak."""
    recovered = bool(state.get("alerted_unhealthy"))
    state["consecutive_failures"] = 0
    state["alerted_unhealthy"] = False
    return recovered
