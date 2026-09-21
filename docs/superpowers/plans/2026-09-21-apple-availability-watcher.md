# Apple Availability Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poll Apple's store-pickup endpoint every 3 minutes and send a Telegram message the moment an iPhone 18 Pro Max 256GB becomes available for pickup near ZIP 33130.

**Architecture:** A one-shot Python script run by cron. Each run fetches per-store availability for the watched parts plus an in-stock canary part, compares against a JSON state file, notifies on transitions, and exits. No daemon, no cookies, no session state.

**Tech Stack:** Python 3.12, `requests`, stdlib `tomllib`, `pytest`. Project-local venv.

**Spec:** `docs/superpowers/specs/2026-09-21-apple-availability-watcher-design.md`

## Global Constraints

- Python 3.12+; dependencies limited to `requests` and `pytest`.
- Package lives in `watcher/`, invoked as `python -m watcher`.
- **All Apple-supplied text must be NBSP-normalized before comparison:** `unicodedata.normalize("NFKC", s).replace(" ", " ")`. Matching raw names yields an empty watch list.
- **State is never written on a failed run.** A transition may only be recorded from a run that completed with a healthy canary.
- Secrets (`TELEGRAM_BOT_TOKEN`) live only in `.env` (mode 600, gitignored). Never in `config.toml`, never committed.
- Telegram chat ID: `-5597962862` (group — bot must be a member, admin if privacy mode is on).
- Canary part: `MJQ34LL/A` (iPhone 18 Pro 256GB Black).
- Watch target: model `iPhone 18 Pro Max`, capacity `256GB`, colors `["*"]`.
- Endpoint: `https://www.apple.com/shop/retail/pickup-message?pl=true&mts.0=regular&location=<zip>&parts.N=<part>`
- Buy page: `https://www.apple.com/shop/buy-iphone/iphone-18-pro`
- Send a browser `User-Agent` on every request; Apple returns HTTP 541 to unadorned clients.

---

## File Structure

| File | Responsibility |
|---|---|
| `watcher/__init__.py` | Package marker, version |
| `watcher/config.py` | Load/validate `config.toml` + `.env`; typed `Config` |
| `watcher/apple.py` | Everything that knows apple.com: discovery, fetch, parse, canary |
| `watcher/state.py` | Load/save `state.json`; compute transitions, repeats, failure counts |
| `watcher/notify.py` | Telegram formatting and delivery |
| `watcher/__main__.py` | CLI, wiring, logging, exit codes |
| `config.toml` | Non-secret configuration |
| `.env` | `TELEGRAM_BOT_TOKEN` (mode 600, gitignored) |
| `tests/test_config.py` | Config loading and validation |
| `tests/test_apple.py` | Discovery, parsing, canary — against captured fixtures |
| `tests/test_state.py` | Transition/repeat/failure logic |
| `tests/test_notify.py` | Message formatting |
| `tests/fixtures/*.json` | Already captured from live site — do not regenerate |

Existing fixtures:
- `buypage_product_array.json` — 32 real products with NBSP names
- `pickup_message_watched_unavailable_canary_ok.json` — 12 stores, canary available at 9, watched at 0
- `availability_session_expired_all_zero.json` — all-negative response that must not be believed

---

### Task 1: Project scaffolding and configuration

**Files:**
- Create: `watcher/__init__.py`, `watcher/config.py`, `config.toml`, `.env.example`, `requirements.txt`, `pytest.ini`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Config` dataclass with fields `zip: str`, `model: str`, `capacity: str`, `colors: list[str]`, `canary_part: str`, `chat_id: str`, `bot_token: str`, `jitter_seconds: int`, `repeat_minutes: int`, `discovery_ttl_hours: int`, `failure_alert_threshold: int`; and `load_config(path: Path, env: Mapping[str,str]) -> Config`.

- [ ] **Step 1: Create the venv and install dependencies**

```bash
cd /home/celsopdvj/projects/apple-available
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
printf 'requests>=2.31\npytest>=8.0\n' > requirements.txt
.venv/bin/pip install -q -r requirements.txt
printf '[pytest]\ntestpaths = tests\n' > pytest.ini
```

- [ ] **Step 2: Write `config.toml` and `.env.example`**

```toml
# config.toml
[watch]
model = "iPhone 18 Pro Max"
capacity = "256GB"
colors = ["*"]

[location]
zip = "33130"

[telegram]
chat_id = "-5597962862"

[canary]
part = "MJQ34LL/A"

[polling]
jitter_seconds = 45
repeat_minutes = 30
discovery_ttl_hours = 24
failure_alert_threshold = 5
```

```bash
# .env.example
TELEGRAM_BOT_TOKEN=123456:ABC-your-token-from-BotFather
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_config.py
import pytest
from pathlib import Path
from watcher.config import load_config, ConfigError

def test_loads_all_fields(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(Path("config.toml").read_text())
    cfg = load_config(cfg_file, {"TELEGRAM_BOT_TOKEN": "tok"})
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
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(Path("config.toml").read_text())
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config(cfg_file, {})

def test_env_chat_id_overrides_file(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(Path("config.toml").read_text())
    cfg = load_config(cfg_file, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "-999"})
    assert cfg.chat_id == "-999"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watcher'`

- [ ] **Step 5: Implement `watcher/config.py`**

```python
# watcher/config.py
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
```

Also create `watcher/__init__.py` containing `__version__ = "1.0.0"`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add watcher/ tests/test_config.py config.toml .env.example requirements.txt pytest.ini
git commit -m "feat: project scaffolding and configuration loading"
```

---

### Task 2: Product discovery with NBSP normalization

**Files:**
- Create: `watcher/apple.py`
- Test: `tests/test_apple.py`

**Interfaces:**
- Consumes: `Config` from Task 1
- Produces: `normalize(s: str) -> str`; `Product(part: str, name: str, price: float)`; `discover_products(html: str) -> list[Product]`; `select_watched(products: list[Product], model: str, capacity: str, colors: list[str]) -> list[Product]`; `DiscoveryError`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apple.py
import json
import pytest
from pathlib import Path
from watcher.apple import (
    normalize, discover_products, select_watched, DiscoveryError,
)

FIXTURES = Path(__file__).parent / "fixtures"


def buypage_html() -> str:
    # The fixture is the product array as embedded in the page; wrap it so the
    # parser sees the same shape it will see in the real page.
    return "<html><script>var x = " + (
        FIXTURES / "buypage_product_array.json"
    ).read_text() + ";</script></html>"


def test_normalize_collapses_nbsp():
    assert normalize("iPhone 18 Pro Max") == "iPhone 18 Pro Max"


def test_discovers_all_products():
    products = discover_products(buypage_html())
    assert len(products) == 32
    assert all(p.part.endswith("LL/A") for p in products)


def test_discovered_names_are_normalized():
    products = discover_products(buypage_html())
    assert all(" " not in p.name for p in products)


def test_selects_exactly_the_four_pro_max_256():
    products = discover_products(buypage_html())
    watched = select_watched(products, "iPhone 18 Pro Max", "256GB", ["*"])
    assert sorted(p.part for p in watched) == [
        "MJW44LL/A", "MJW54LL/A", "MJW64LL/A", "MJW74LL/A",
    ]
    assert all(p.price == 1299.00 for p in watched)


def test_selects_named_colors_only():
    products = discover_products(buypage_html())
    watched = select_watched(products, "iPhone 18 Pro Max", "256GB", ["Black"])
    assert [p.part for p in watched] == ["MJW44LL/A"]


def test_regression_raw_names_would_match_nothing():
    """Pins the bug actually hit: Apple uses U+00A0 in product names, so a
    naive substring match silently yields an empty watch list."""
    raw = json.loads((FIXTURES / "buypage_product_array.json").read_text())
    naive = [p for p in raw if "iPhone 18 Pro Max" in p["name"]]
    assert naive == [], "fixture no longer contains NBSP; regression test is moot"


def test_empty_selection_raises():
    products = discover_products(buypage_html())
    with pytest.raises(DiscoveryError, match="no products matched"):
        select_watched(products, "iPhone 42 Pro", "256GB", ["*"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_apple.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize'`

- [ ] **Step 3: Implement the discovery half of `watcher/apple.py`**

```python
# watcher/apple.py
from __future__ import annotations
import logging
import re
import unicodedata
from dataclasses import dataclass

log = logging.getLogger(__name__)

BUY_PAGE = "https://www.apple.com/shop/buy-iphone/iphone-18-pro"

# Matches the product objects embedded in the buy page, e.g.
# {"sku":"MJW44","partNumber":"MJW44LL/A","price":{"fullPrice":1299.00},
#  "category":"iphone","name":"iPhone 18 Pro Max 256GB Black"}
_PRODUCT_RE = re.compile(
    r'\{"sku":"[A-Z0-9]+",'
    r'"partNumber":"([A-Z0-9]+LL/A)",'
    r'"price":\{"fullPrice":([0-9.]+)\},'
    r'"category":"[a-z]+",'
    r'"name":"([^"]+)"\}'
)


class DiscoveryError(Exception):
    """The buy page yielded no usable products, or none matched the watch."""


def normalize(s: str) -> str:
    """Apple embeds U+00A0 in product names. Matching raw names silently
    yields nothing, so every comparison goes through here first."""
    return unicodedata.normalize("NFKC", s).replace(" ", " ").strip()


@dataclass(frozen=True)
class Product:
    part: str
    name: str
    price: float


def discover_products(html: str) -> list[Product]:
    seen: dict[str, Product] = {}
    for part, price, name in _PRODUCT_RE.findall(html):
        seen[part] = Product(part=part, name=normalize(name), price=float(price))
    if not seen:
        raise DiscoveryError(
            "no products found on the buy page; the page structure likely changed"
        )
    return sorted(seen.values(), key=lambda p: p.name)


def select_watched(
    products: list[Product], model: str, capacity: str, colors: list[str]
) -> list[Product]:
    model_n, capacity_n = normalize(model), normalize(capacity)
    wanted = {normalize(c).lower() for c in colors}
    take_all = "*" in wanted

    matched = []
    for p in products:
        if not p.name.startswith(model_n) or capacity_n not in p.name:
            continue
        color = p.name.split()[-1].lower()
        if take_all or color in wanted:
            matched.append(p)

    if not matched:
        raise DiscoveryError(
            f"no products matched model={model!r} capacity={capacity!r} "
            f"colors={colors!r}; watching nothing is always a bug"
        )
    return matched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_apple.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add watcher/apple.py tests/test_apple.py
git commit -m "feat: product discovery with NBSP normalization"
```

---

### Task 3: Availability fetch, parsing, and the canary

**Files:**
- Modify: `watcher/apple.py`
- Test: `tests/test_apple.py` (append)

**Interfaces:**
- Consumes: `Product`, `normalize` from Task 2
- Produces: `Store(store_id, name, street, city, state, distance, quote)`; `PartAvailability(part, name, stores)` with `.available` and `.store_count` properties; `parse_pickup(payload: dict, products: dict[str, Product]) -> dict[str, PartAvailability]`; `check_canary(results, canary_part) -> None` raising `ImplausibleResponse`; `fetch_pickup(zip_code, parts, session=None) -> dict`; exceptions `TransientError`, `ImplausibleResponse`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_apple.py
from watcher.apple import (
    Store, PartAvailability, parse_pickup, check_canary,
    ImplausibleResponse, Product,
)

CANARY = "MJQ34LL/A"
WATCHED = ["MJW44LL/A", "MJW54LL/A", "MJW64LL/A", "MJW74LL/A"]


def pickup_payload():
    return json.loads(
        (FIXTURES / "pickup_message_watched_unavailable_canary_ok.json").read_text()
    )


def all_zero_payload():
    return json.loads(
        (FIXTURES / "availability_session_expired_all_zero.json").read_text()
    )


def product_map():
    names = {
        CANARY: "iPhone 18 Pro 256GB Black",
        "MJW44LL/A": "iPhone 18 Pro Max 256GB Black",
        "MJW54LL/A": "iPhone 18 Pro Max 256GB Silver",
        "MJW64LL/A": "iPhone 18 Pro Max 256GB Burgundy",
        "MJW74LL/A": "iPhone 18 Pro Max 256GB Glacier",
    }
    return {k: Product(k, v, 1299.0) for k, v in names.items()}


def test_parses_canary_as_available_with_stores():
    results = parse_pickup(pickup_payload(), product_map())
    canary = results[CANARY]
    assert canary.available is True
    assert canary.store_count == 9
    assert "Brickell City Centre" in [s.name for s in canary.stores]


def test_store_details_are_populated():
    results = parse_pickup(pickup_payload(), product_map())
    store = next(s for s in results[CANARY].stores if s.name == "Brickell City Centre")
    assert store.store_id == "R623"
    assert store.street == "701 S. Miami Avenue"
    assert store.city == "Miami"
    assert store.state == "FL"
    assert store.distance == "0.63 mi"
    assert store.quote == "Available Today"


def test_watched_parts_are_unavailable_in_fixture():
    results = parse_pickup(pickup_payload(), product_map())
    for part in WATCHED:
        assert results[part].available is False
        assert results[part].store_count == 0


def test_only_available_stores_are_listed():
    results = parse_pickup(pickup_payload(), product_map())
    # 12 stores total, 3 report "unavailable" for the canary
    assert results[CANARY].store_count == 9


def test_canary_healthy_passes():
    results = parse_pickup(pickup_payload(), product_map())
    check_canary(results, CANARY)  # must not raise


def test_canary_zero_raises_implausible():
    results = parse_pickup(pickup_payload(), product_map())
    stripped = dict(results)
    stripped[CANARY] = PartAvailability(CANARY, "iPhone 18 Pro 256GB Black", [])
    with pytest.raises(ImplausibleResponse, match="canary"):
        check_canary(stripped, CANARY)


def test_missing_canary_raises_implausible():
    results = parse_pickup(pickup_payload(), product_map())
    del results[CANARY]
    with pytest.raises(ImplausibleResponse):
        check_canary(results, CANARY)


def test_malformed_store_entries_are_skipped_not_fatal():
    payload = pickup_payload()
    payload["body"]["stores"].insert(0, {"storeName": "Broken"})  # no partsAvailability
    results = parse_pickup(payload, product_map())
    assert results[CANARY].store_count == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_apple.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_pickup'`

- [ ] **Step 3: Implement the fetch/parse half of `watcher/apple.py`**

```python
# append to watcher/apple.py
import random
import time
import requests

PICKUP_URL = "https://www.apple.com/shop/retail/pickup-message"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class TransientError(Exception):
    """Network failure, timeout, or bot-block. Retry later; do not write state."""


class ImplausibleResponse(Exception):
    """A well-formed but entirely negative response that must not be believed."""


@dataclass(frozen=True)
class Store:
    store_id: str
    name: str
    street: str
    city: str
    state: str
    distance: str
    quote: str


@dataclass(frozen=True)
class PartAvailability:
    part: str
    name: str
    stores: list[Store]

    @property
    def available(self) -> bool:
        return bool(self.stores)

    @property
    def store_count(self) -> int:
        return len(self.stores)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _get(url: str, params: dict | None, session: requests.Session) -> requests.Response:
    delay = 2.0
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=25)
            if r.status_code == 541 or r.status_code >= 500:
                raise TransientError(f"HTTP {r.status_code} from {url}")
            r.raise_for_status()
            return r
        except (requests.RequestException, TransientError) as exc:
            last = exc
            log.warning("request failed (attempt %d/3): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(delay)
                delay *= 2
    raise TransientError(f"giving up after 3 attempts: {last}")


def fetch_buy_page(session: requests.Session | None = None) -> str:
    session = session or _session()
    r = _get(BUY_PAGE, None, session)
    return r.text


def fetch_pickup(
    zip_code: str, parts: list[str], session: requests.Session | None = None
) -> dict:
    session = session or _session()
    params = {"pl": "true", "mts.0": "regular", "location": zip_code}
    for i, part in enumerate(parts):
        params[f"parts.{i}"] = part
    r = _get(PICKUP_URL, params, session)
    try:
        return r.json()
    except ValueError as exc:
        raise TransientError(f"response was not JSON: {exc}") from exc


def parse_pickup(
    payload: dict, products: dict[str, Product]
) -> dict[str, PartAvailability]:
    stores = (payload.get("body") or {}).get("stores") or []
    found: dict[str, list[Store]] = {part: [] for part in products}

    for raw in stores:
        avail = raw.get("partsAvailability")
        if not isinstance(avail, dict):
            log.warning("store %r has no partsAvailability; skipping",
                        raw.get("storeName"))
            continue
        addr = raw.get("address") or {}
        for part, info in avail.items():
            if part not in found:
                continue
            if (info or {}).get("pickupDisplay") != "available":
                continue
            found[part].append(
                Store(
                    store_id=raw.get("storeNumber") or raw.get("storeId") or "",
                    name=normalize(raw.get("storeName") or ""),
                    street=normalize(addr.get("address2") or addr.get("address") or ""),
                    city=normalize(raw.get("city") or ""),
                    state=raw.get("state") or "",
                    distance=raw.get("storeDistanceWithUnit") or "",
                    quote=normalize((info or {}).get("pickupSearchQuote") or ""),
                )
            )

    return {
        part: PartAvailability(part, products[part].name, sorted(s, key=lambda x: x.name))
        for part, s in found.items()
    }


def check_canary(results: dict[str, PartAvailability], canary_part: str) -> None:
    """An all-negative response is indistinguishable from a broken one, so a
    control part known to be in stock decides whether to believe the zeros."""
    canary = results.get(canary_part)
    if canary is None:
        raise ImplausibleResponse(
            f"canary {canary_part} missing from response; not believing the result"
        )
    if not canary.available:
        raise ImplausibleResponse(
            f"canary {canary_part} ({canary.name}) reports 0 stores. Either the "
            f"endpoint stopped honouring the location, or the canary genuinely "
            f"sold out everywhere. Not believing the zeros. Pick a different "
            f"canary part if this persists."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_apple.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add watcher/apple.py tests/test_apple.py
git commit -m "feat: pickup availability fetch, parsing, and canary check"
```

---

### Task 4: State and transition logic

**Files:**
- Create: `watcher/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `PartAvailability` from Task 3
- Produces: `State` (dict-backed, with `load(path)`, `save(path)`); `decide(state, results, now, repeat_minutes) -> Decision`; `Decision(newly_available: list[str], repeats: list[str], went_away: list[str])`; `record_failure(state) -> int`; `record_success(state) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from watcher.apple import PartAvailability, Store
from watcher.state import State, decide, record_failure, record_success

T0 = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
STORE = Store("R623", "Brickell City Centre", "701 S. Miami Avenue",
              "Miami", "FL", "0.63 mi", "Available Today")


def avail(part, stores):
    return PartAvailability(part, f"name-{part}", stores)


def test_first_time_available_is_a_transition():
    st = State.empty()
    results = {"A": avail("A", [STORE])}
    d = decide(st, results, T0, repeat_minutes=30)
    assert d.newly_available == ["A"]
    assert d.repeats == []


def test_unavailable_stays_silent():
    st = State.empty()
    d = decide(st, {"A": avail("A", [])}, T0, repeat_minutes=30)
    assert d.newly_available == []
    assert d.repeats == []


def test_still_available_before_interval_is_silent():
    st = State.empty()
    results = {"A": avail("A", [STORE])}
    decide(st, results, T0, repeat_minutes=30)
    d = decide(st, results, T0 + timedelta(minutes=10), repeat_minutes=30)
    assert d.newly_available == []
    assert d.repeats == []


def test_still_available_after_interval_repeats():
    st = State.empty()
    results = {"A": avail("A", [STORE])}
    decide(st, results, T0, repeat_minutes=30)
    d = decide(st, results, T0 + timedelta(minutes=31), repeat_minutes=30)
    assert d.newly_available == []
    assert d.repeats == ["A"]


def test_going_away_clears_timer_and_reports():
    st = State.empty()
    decide(st, {"A": avail("A", [STORE])}, T0, repeat_minutes=30)
    d = decide(st, {"A": avail("A", [])}, T0 + timedelta(minutes=5), repeat_minutes=30)
    assert d.went_away == ["A"]
    # becoming available again is a fresh transition
    d2 = decide(st, {"A": avail("A", [STORE])}, T0 + timedelta(minutes=6),
                repeat_minutes=30)
    assert d2.newly_available == ["A"]


def test_failure_counter_trips_once_at_threshold():
    st = State.empty()
    counts = [record_failure(st) for _ in range(6)]
    assert counts == [1, 2, 3, 4, 5, 6]


def test_success_after_failures_signals_recovery():
    st = State.empty()
    for _ in range(5):
        record_failure(st)
    st["alerted_unhealthy"] = True
    assert record_success(st) is True     # recovered
    assert record_success(st) is False    # already healthy
    assert st["consecutive_failures"] == 0


def test_round_trips_through_disk(tmp_path):
    st = State.empty()
    decide(st, {"A": avail("A", [STORE])}, T0, repeat_minutes=30)
    p = tmp_path / "state.json"
    st.save(p)
    again = State.load(p)
    assert again["parts"]["A"]["available"] is True


def test_load_missing_file_returns_empty(tmp_path):
    st = State.load(tmp_path / "nope.json")
    assert st["parts"] == {}


def test_load_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert State.load(p)["parts"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watcher.state'`

- [ ] **Step 3: Implement `watcher/state.py`**

```python
# watcher/state.py
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


class State(dict):
    """Plain JSON-backed state. Only ever written by a fully successful run."""

    @classmethod
    def empty(cls) -> "State":
        return cls({"parts": {}, "products": {}, "products_fetched_at": None,
                    "consecutive_failures": 0, "alerted_unhealthy": False})

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_state.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add watcher/state.py tests/test_state.py
git commit -m "feat: state persistence and transition logic"
```

---

### Task 5: Telegram notification

**Files:**
- Create: `watcher/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `PartAvailability`, `Store` from Task 3
- Produces: `format_available(res, zip_code, repeat=False) -> str`; `format_unhealthy(reason, failures) -> str`; `format_recovered() -> str`; `Telegram(token, chat_id)` with `.send(text) -> bool` and `.check() -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notify.py
from watcher.apple import PartAvailability, Store
from watcher.notify import format_available, format_unhealthy, format_recovered

S1 = Store("R623", "Brickell City Centre", "701 S. Miami Avenue", "Miami", "FL",
           "0.63 mi", "Available Today")
S2 = Store("R115", "Lincoln Road", "1021 Lincoln Road", "Miami Beach", "FL",
           "4.33 mi", "Available Today")


def test_available_message_names_config_and_stores():
    res = PartAvailability("MJW44LL/A", "iPhone 18 Pro Max 256GB Black", [S1, S2])
    msg = format_available(res, "33130")
    assert "iPhone 18 Pro Max 256GB Black" in msg
    assert "2 store" in msg
    assert "Brickell City Centre" in msg
    assert "701 S. Miami Avenue" in msg
    assert "0.63 mi" in msg
    assert "33130" in msg
    assert "apple.com" in msg


def test_repeat_message_is_marked_as_reminder():
    res = PartAvailability("MJW44LL/A", "iPhone 18 Pro Max 256GB Black", [S1])
    assert "reminder" in format_available(res, "33130", repeat=True).lower()


def test_single_store_is_not_pluralized():
    res = PartAvailability("MJW44LL/A", "iPhone 18 Pro Max 256GB Black", [S1])
    assert "1 store:" in format_available(res, "33130")


def test_long_store_lists_are_truncated():
    stores = [Store(f"R{i}", f"Store {i}", "st", "Miami", "FL", "1 mi", "Today")
              for i in range(20)]
    res = PartAvailability("MJW44LL/A", "iPhone 18 Pro Max 256GB Black", stores)
    msg = format_available(res, "33130")
    assert "20 stores" in msg
    assert "and 10 more" in msg


def test_unhealthy_message_includes_reason():
    msg = format_unhealthy("canary MJQ34LL/A reports 0 stores", 5)
    assert "canary" in msg
    assert "5" in msg


def test_recovered_message():
    assert "recover" in format_recovered().lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_notify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watcher.notify'`

- [ ] **Step 3: Implement `watcher/notify.py`**

```python
# watcher/notify.py
from __future__ import annotations
import logging
import requests

log = logging.getLogger(__name__)

BUY_URL = "https://www.apple.com/shop/buy-iphone/iphone-18-pro"
MAX_STORES_LISTED = 10


def format_available(res, zip_code: str, repeat: bool = False) -> str:
    head = "🔔 Still available (reminder)" if repeat else "🟢 Available for pickup"
    noun = "store" if res.store_count == 1 else "stores"
    lines = [
        f"{head}",
        f"*{res.name}*",
        "",
        f"{res.store_count} {noun} near {zip_code}:",
    ]
    for s in res.stores[:MAX_STORES_LISTED]:
        where = ", ".join(x for x in (s.street, f"{s.city} {s.state}".strip()) if x)
        lines.append(f"• {s.name} — {where} ({s.distance})")
        if s.quote:
            lines.append(f"  {s.quote}")
    if res.store_count > MAX_STORES_LISTED:
        lines.append(f"…and {res.store_count - MAX_STORES_LISTED} more")
    lines += ["", BUY_URL]
    return "\n".join(lines)


def format_unhealthy(reason: str, failures: int) -> str:
    return (
        "🔴 Availability watcher is unhealthy\n\n"
        f"{failures} consecutive failed checks.\n"
        f"Reason: {reason}\n\n"
        "No further alerts until it recovers."
    )


def format_recovered() -> str:
    return "🟡 Availability watcher has recovered and is checking normally again."


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self._base = f"https://api.telegram.org/bot{token}"
        self._chat_id = chat_id

    def send(self, text: str) -> bool:
        try:
            r = requests.post(
                f"{self._base}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            log.error("telegram send failed: %s", exc)
            return False
        if not r.ok:
            log.error("telegram rejected the message: %s %s", r.status_code, r.text[:300])
            return False
        return True

    def check(self) -> str:
        """Verify the token and that the bot can reach the configured chat."""
        me = requests.get(f"{self._base}/getMe", timeout=20)
        if not me.ok:
            raise RuntimeError(f"bot token rejected: {me.status_code} {me.text[:200]}")
        name = me.json()["result"]["username"]
        chat = requests.get(
            f"{self._base}/getChat", params={"chat_id": self._chat_id}, timeout=20
        )
        if not chat.ok:
            raise RuntimeError(
                f"bot @{name} cannot see chat {self._chat_id}: {chat.text[:200]}. "
                "Add the bot to the group; if privacy mode is on, make it an admin."
            )
        return name
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_notify.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add watcher/notify.py tests/test_notify.py
git commit -m "feat: telegram message formatting and delivery"
```

---

### Task 6: CLI wiring, logging, and cron installation

**Files:**
- Create: `watcher/__main__.py`, `scripts/install-cron.sh`, `README.md`
- Test: manual verification steps below

**Interfaces:**
- Consumes: everything from Tasks 1–5
- Produces: `python -m watcher` with flags `--once`, `--dry-run`, `--status`, `--check-telegram`, `--verbose`

- [ ] **Step 1: Implement `watcher/__main__.py`**

```python
# watcher/__main__.py
from __future__ import annotations
import argparse
import logging
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from watcher import apple, notify, state as state_mod
from watcher.config import load_config, ConfigError

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "state.json"
CONFIG_PATH = ROOT / "config.toml"
log = logging.getLogger("watcher")


def read_dotenv(path: Path) -> dict[str, str]:
    env = dict(os.environ)
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def refresh_products(cfg, st, session):
    """Re-discover parts if the cache is stale, else reuse it."""
    fetched = st.get("products_fetched_at")
    fresh = False
    if fetched:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched)
        fresh = age < timedelta(hours=cfg.discovery_ttl_hours)
    if fresh and st.get("products"):
        return {p: apple.Product(p, d["name"], d["price"])
                for p, d in st["products"].items()}

    log.info("refreshing product list from the buy page")
    html = apple.fetch_buy_page(session)
    products = apple.discover_products(html)
    watched = apple.select_watched(products, cfg.model, cfg.capacity, cfg.colors)
    canary = next((p for p in products if p.part == cfg.canary_part), None)
    if canary is None:
        raise apple.DiscoveryError(
            f"canary part {cfg.canary_part} not found on the buy page"
        )
    chosen = {p.part: p for p in [*watched, canary]}
    st["products"] = {p.part: {"name": p.name, "price": p.price}
                      for p in chosen.values()}
    st["products_fetched_at"] = datetime.now(timezone.utc).isoformat()
    log.info("watching %d parts: %s", len(watched),
             ", ".join(p.name for p in watched))
    return chosen


def run_once(cfg, dry_run: bool) -> int:
    st = state_mod.State.load(STATE_PATH)
    tg = notify.Telegram(cfg.bot_token, cfg.chat_id)
    session = apple._session()

    try:
        products = refresh_products(cfg, st, session)
        payload = apple.fetch_pickup(cfg.zip, list(products), session)
        results = apple.parse_pickup(payload, products)
        try:
            apple.check_canary(results, cfg.canary_part)
        except apple.ImplausibleResponse:
            log.warning("canary failed; retrying once after backoff")
            time.sleep(5)
            payload = apple.fetch_pickup(cfg.zip, list(products), session)
            results = apple.parse_pickup(payload, products)
            apple.check_canary(results, cfg.canary_part)
    except (apple.TransientError, apple.ImplausibleResponse,
            apple.DiscoveryError) as exc:
        n = state_mod.record_failure(st)
        log.error("check failed (%d consecutive): %s", n, exc)
        if n >= cfg.failure_alert_threshold and not st.get("alerted_unhealthy"):
            if not dry_run:
                tg.send(notify.format_unhealthy(str(exc), n))
            st["alerted_unhealthy"] = True
        st.save(STATE_PATH)   # failure bookkeeping only; part states untouched
        return 1

    if state_mod.record_success(st) and not dry_run:
        tg.send(notify.format_recovered())

    watched = {p: r for p, r in results.items() if p != cfg.canary_part}
    decision = state_mod.decide(st, watched, datetime.now(timezone.utc),
                                cfg.repeat_minutes)

    for part in decision.newly_available + decision.repeats:
        msg = notify.format_available(
            watched[part], cfg.zip, repeat=part in decision.repeats
        )
        if dry_run:
            print(msg + "\n" + "-" * 50)
        else:
            tg.send(msg)
        log.info("notified: %s", watched[part].name)

    for part in decision.went_away:
        log.info("no longer available: %s", watched[part].name)

    if not decision.newly_available and not decision.repeats:
        log.info("no change; %s",
                 ", ".join(f"{r.name}={r.store_count}" for r in watched.values()))

    if not dry_run:
        st.save(STATE_PATH)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="watcher")
    ap.add_argument("--once", action="store_true", help="single check (default)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print messages instead of sending; do not persist state")
    ap.add_argument("--status", action="store_true", help="print state and exit")
    ap.add_argument("--check-telegram", action="store_true",
                    help="verify bot token and chat access")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-jitter", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    try:
        cfg = load_config(CONFIG_PATH, read_dotenv(ROOT / ".env"))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.status:
        st = state_mod.State.load(STATE_PATH)
        print(f"consecutive failures: {st.get('consecutive_failures', 0)}")
        for part, d in sorted(st.get("parts", {}).items()):
            mark = "AVAILABLE" if d.get("available") else "-"
            print(f"  {part:<12} {mark:<10} {d.get('store_count', 0):>3} stores  "
                  f"{d.get('name', '')}")
        return 0

    if args.check_telegram:
        try:
            name = notify.Telegram(cfg.bot_token, cfg.chat_id).check()
        except RuntimeError as exc:
            print(f"telegram check failed: {exc}", file=sys.stderr)
            return 2
        print(f"telegram OK: bot @{name} can post to {cfg.chat_id}")
        return 0

    if not args.no_jitter and not args.dry_run and cfg.jitter_seconds:
        time.sleep(random.uniform(0, cfg.jitter_seconds))

    return run_once(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify the full suite passes**

Run: `.venv/bin/pytest -q`
Expected: 36 passed

- [ ] **Step 3: Verify against the live site without sending anything**

Run: `.venv/bin/python -m watcher --dry-run --verbose --no-jitter`
Expected: discovers 4 watched parts, fetches live availability, canary passes, reports "no change" with each watched part at 0 stores. Exit 0.

- [ ] **Step 4: Write `scripts/install-cron.sh`**

```bash
#!/usr/bin/env bash
# Installs the every-3-minutes cron entry, idempotently.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINE="*/3 * * * * cd $ROOT && mkdir -p logs && .venv/bin/python -m watcher >> logs/watcher.log 2>&1"
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v -F "python -m watcher" > "$TMP" || true
echo "$LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "installed:"
crontab -l | grep "python -m watcher"
```

- [ ] **Step 5: Install cron and confirm it runs**

```bash
chmod +x scripts/install-cron.sh && ./scripts/install-cron.sh
# wait for the next 3-minute boundary, then:
tail -n 20 logs/watcher.log
```

Expected: a log line per run showing "no change" and the per-part store counts.

- [ ] **Step 6: Write `README.md`** covering: what it watches, how to set `TELEGRAM_BOT_TOKEN`, the CLI flags, how to change the watch target in `config.toml`, how to read `--status`, and the WSL sleep limitation.

- [ ] **Step 7: Commit**

```bash
git add watcher/__main__.py scripts/install-cron.sh README.md
git commit -m "feat: CLI, logging, and cron installation"
```

---

## Self-Review

**Spec coverage:** Purpose → Task 6. pickup-message endpoint → Task 3. Buy-page discovery → Task 2. NBSP normalization → Task 2 (with regression test). Canary → Task 3 + retry in Task 6. Alerting (transition/repeat/health/recovery) → Tasks 4, 5, 6. Failure handling table → Tasks 3, 4, 6. Configuration → Task 1. Runtime/cron → Task 6. Testing → Tasks 1–5.

**Placeholders:** none; every step carries runnable content.

**Type consistency:** `Product(part, name, price)`, `Store(store_id, name, street, city, state, distance, quote)` and `PartAvailability(part, name, stores)` are defined in Tasks 2–3 and used with those exact names in Tasks 4–6. `decide()`, `record_failure()`, `record_success()` signatures match between Task 4 and Task 6.
