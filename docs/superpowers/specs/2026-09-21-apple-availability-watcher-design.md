# iPhone 18 Pro Max Availability Watcher — Design

**Date:** 2026-09-21
**Status:** Approved for planning

## Purpose

Notify the user via Telegram as soon as an iPhone 18 Pro Max 256GB (any
color) becomes available for in-store pickup near ZIP 33130 (Miami).

Today all four 256GB Pro Max colors report zero stores near 33130 while the
iPhone 18 Pro equivalents are widely stocked, so the window that
matters is the moment stock first appears. The user must hear about it in
minutes, not hours.

## Non-goals

- Buying, reserving, or holding the phone. Notification only.
- Watching delivery/ship-date changes. Store pickup only.
- Watching Pro (non-Max), other capacities, or other ZIPs. The config
  supports them; the shipped default does not use them.
- A web UI, a database, or multi-user support.

## Key findings from live investigation

These were verified against apple.com on 2026-09-21 and drive the design.

### The availability endpoint

```
GET https://www.apple.com/shop/sba/availability-message
      ?location=<zip>&parts.0=<part>&parts.1=<part>...
```

Returns JSON. Per part it carries `partAvailableStoresCount`,
`availableAtAnyStore`, `eligibleStores` (comma-separated store IDs), a
`pickupMessage` with store name/street address, and a `deliveryMessage`
whose `subHeader` names the configuration in plain text
(e.g. `For iPhone 18 Pro Max 256GB Black`).

No browser automation is required. The wizard steps in the user's video
(trade-in, carrier, AppleCare) do not change the part number; unlocked with
no AppleCare is what these part numbers already mean.

At least 8 parts per request work. The whole watch list plus canary is 5,
so a poll costs **one** HTTP request.

### The session requirement, and the silent-failure trap

The endpoint requires a location cookie. Without it, it returns
`200 OK` with `partAvailableStoresCount: 0` and
`availableAtAnyStore: false` for **every** part — including parts that are
in stock at a dozen stores. A broken session is therefore
indistinguishable from "no stock" by inspection of the response alone.

This is not hypothetical: it produced a full page of false zeros during
investigation, including for a year-old iPhone 17, before being caught.

The cookie is set by a **POST**:

```
POST https://www.apple.com/shop/address/location/update
Content-Type: application/x-www-form-urlencoded

location=<zip>&postalCode=<zip>
```

A successful response reports `"dudeCookieSet": true` and
`"userEnteredLocation": true`, and sets an `as_loc` cookie. The GET form of
the same URL returns 200 but does **not** set the cookie.

### Part numbers (as of 2026-09-21)

Watch list — iPhone 18 Pro Max 256GB:

| Part | Color |
|---|---|
| `MJW44LL/A` | Black |
| `MJW54LL/A` | Silver |
| `MJW64LL/A` | Burgundy |
| `MJW74LL/A` | Glacier |

Canary — `MJQ34LL/A` (iPhone 18 Pro 256GB Black), 9 stores at time of
capture.

Part numbers are recorded here for reference only. The implementation
rediscovers them at runtime (see Part discovery).

## Architecture

A one-shot script invoked by cron. Each run is a complete, independent
check: bootstrap, fetch, compare, notify, persist, exit. A failed run is a
skipped cycle and nothing more. There is no daemon, no long-lived process,
and no restart policy to maintain.

```
cron (*/3) → python -m watcher        → watcher/__main__.py
                                          ├── watcher/config.py  load + validate config, secrets from env
                                          ├── watcher/apple.py   session bootstrap, discovery, availability fetch
                                          ├── watcher/state.py   load/save JSON, compute transitions
                                          └── watcher/notify.py  Telegram delivery
```

All modules live in a `watcher/` package so the cron entry below can invoke
it as `python -m watcher`.

### Module boundaries

**`watcher/apple.py`** — the only module that knows apple.com exists. Owns cookie
bootstrap, part discovery, the availability request, and response parsing.
Exposes `fetch_availability(session, zip, parts) -> list[PartAvailability]`
and raises `SessionExpired` / `TransientError`. Returns dataclasses, never
raw JSON. If Apple changes anything, this is the file that changes.

**`watcher/state.py`** — reads and writes `state.json`; given previous and current
readings, returns the list of parts that transitioned to available and
those due for a repeat reminder. Pure logic over plain data; no I/O beyond
the one file.

**`watcher/notify.py`** — formats and sends Telegram messages. Knows nothing about
Apple; takes already-computed events.

**`watcher/__main__.py`** — wiring, CLI flags, logging, exit codes.

### Data model

```python
@dataclass(frozen=True)
class PartAvailability:
    part: str            # "MJW44LL/A"
    config: str          # "iPhone 18 Pro Max 256GB Black"
    model: str           # "iPhone 18 Pro Max"
    capacity: str        # "256GB"
    color: str           # "Black"
    store_count: int
    available: bool
    stores: list[Store]  # name, street, city, state, pickup quote
```

`config`, `model`, `capacity` and `color` are parsed from the API's own
`subHeader`, so labels never drift from what Apple reports.

## Part discovery

Hardcoded part numbers are the standard way this kind of script dies
quietly: Apple rotates them between drops and the watcher goes on
cheerfully reporting nothing about a SKU that no longer exists.

Instead the config names the target by configuration:

```toml
[watch]
model = "iPhone 18 Pro Max"
capacity = "256GB"
colors = ["*"]          # or ["Black", "Silver"]
```

Each run, if the cached part list is older than `discovery_ttl_hours`
(default 24) or empty, the script fetches the buy page, extracts candidate
part numbers by regex (`[A-Z0-9]{5,6}LL/A`), queries them in batches of 6,
and keeps those whose `subHeader` matches the watch config. AppleCare SKUs
(which appear in the same page and whose `subHeader` contains `AppleCare`)
are excluded. The result is cached in `state.json`.

If discovery finds **zero** matching parts, that is an error condition, not
an empty result: the script alerts once and leaves prior state untouched.
Silently watching nothing is the failure this whole section exists to
prevent.

## The canary

Every availability request includes one control part that is expected to be
in stock. Config:

```toml
[canary]
part = "MJQ34LL/A"      # iPhone 18 Pro 256GB Black
```

Decision rule, applied before any comparison:

- Canary `store_count > 0` → session healthy, trust the readings.
- Canary `store_count == 0` → **do not trust the zeros.** Re-bootstrap the
  session and retry once. If the canary is still zero, raise
  `SessionExpired`, leave state untouched, and count it as a failed run.

This converts the silent-failure trap into a self-healing one. The two
captured fixtures pin both sides of the discrimination:
`availability_watched_unavailable_canary_ok.json` (canary 9, watched 0 —
genuine scarcity) and `availability_session_expired_all_zero.json`
(everything 0 — broken session).

The canary is itself a supply risk: if the iPhone 18 Pro sells out
everywhere, the canary reads zero and the watcher alerts as broken. That
is the correct failure direction — it fails loud, not silent — and the
alert text names the canary explicitly so the fix (pick a different control
part) is obvious. Choosing a durable staple such as a current AirPods or
Apple TV SKU is a reasonable later refinement; it is not needed for launch.

## Alerting

**Trigger.** A watched part goes `available == False` → `available == True`.

**Repeat.** While a part remains available, re-notify every
`repeat_minutes` (default 30). One missed notification should not cost the
purchase.

**Recovery.** When a part goes available → unavailable, log it and clear
its repeat timer. No message; the user declined that.

**Health.** After `failure_alert_threshold` consecutive failed runs
(default 5, ≈15 min at a 3-minute cadence) send exactly one "watcher is
unhealthy" message naming the cause. Stay silent until a run succeeds,
then send a single recovery message. This covers the died-quietly risk
without the periodic heartbeat the user declined.

**Message format:**

```
🟢 iPhone 18 Pro Max 256GB Black — available for pickup

4 stores near 33130:
• Apple Brickell City Centre — 701 S. Miami Avenue, Miami FL
  Tomorrow 10:30 a.m. – 12:30 p.m.
• Apple Lincoln Road — 1021 Lincoln Road, Miami Beach FL
  ...

https://www.apple.com/shop/buy-iphone/iphone-18-pro
```

## Failure handling

| Condition | Response |
|---|---|
| Connection error, timeout, 5xx | Retry 3× with exponential backoff (2s, 4s, 8s) |
| HTTP 541 (Apple bot-block) | Treat as transient; backoff and retry |
| Canary reads zero | Re-bootstrap once, then `SessionExpired` |
| Missing/renamed JSON fields | Log at WARNING, treat part as unknown, never as a change |
| Discovery matches zero parts | Alert once; preserve prior state |
| Any failed run | **State is never written.** |

The invariant that matters: a transition is only ever recorded from a run
that fully succeeded with a healthy canary. A transient blip cannot
fabricate a "now available" alert, and — equally — cannot erase one.

## Configuration

`config.toml` in the project root, secrets from environment:

```toml
[watch]
model = "iPhone 18 Pro Max"
capacity = "256GB"
colors = ["*"]

[location]
zip = "33130"

[canary]
part = "MJQ34LL/A"

[polling]
jitter_seconds = 45
repeat_minutes = 30
discovery_ttl_hours = 24
failure_alert_threshold = 5
```

`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` come from a `.env` file
(mode 600, gitignored). Secrets never go in `config.toml`.

## Runtime and deployment

Python 3.12 in a project-local venv with `requests`, avoiding any
dependence on system site-packages.

Cron entry, every 3 minutes, with 0–45s in-script jitter so requests do not
land on a robotic boundary:

```
*/3 * * * * cd /home/celsopdvj/projects/apple-available && mkdir -p logs && .venv/bin/python -m watcher >> logs/watcher.log 2>&1
```

Cost per run is one availability request, plus a bootstrap POST when the
session is cold and a buy-page fetch at most daily.

**Known limitation, accepted by the user:** on WSL this runs only while
Windows is awake and the distro is up. Stock appearing overnight with the
laptop closed will be missed. Nothing in the code assumes WSL, so moving
to a VPS or GitHub Actions later is a deployment change, not a rewrite.

## Testing

Unit tests run offline against the captured fixtures in `tests/fixtures/`:

- Canary healthy + watched at zero → no alert (genuine scarcity).
- Canary zero → `SessionExpired`, state untouched, no alert.
- Watched part 0 → 4 stores → exactly one alert, correct store list.
- Watched part stays available → repeat only after `repeat_minutes`.
- Watched part available → unavailable → no message, timer cleared.
- `subHeader` parsing across all 37 real strings, AppleCare SKUs excluded.
- Malformed/truncated JSON → treated as failure, state untouched.
- Consecutive failures → exactly one health alert, then silence.

CLI affordances: `--once` (single cycle), `--dry-run` (print the message
instead of sending), `--test-telegram` (verify credentials end to end),
`--status` (print current state and last run).

A `scripts/get_chat_id.py` helper reads the chat ID from the Bot API
`getUpdates` after the user messages their bot once.

## Open risks

1. **Apple changes the endpoint or response shape.** Contained to
   `watcher/apple.py`; surfaces as a health alert rather than silence.
2. **Rate limiting or bot-blocking at higher volume.** One request per
   3 minutes is modest, and a transient `000`/`541` was observed only
   during a rapid investigation burst. Backoff plus jitter is the
   mitigation; if blocks become routine, lengthen the interval.
3. **Canary sells out.** Fails loud, as designed; see The canary.
4. **WSL sleep window.** Accepted.
