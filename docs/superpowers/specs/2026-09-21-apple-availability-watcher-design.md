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

### The store-availability endpoint (primary)

```
GET https://www.apple.com/shop/retail/pickup-message
      ?pl=true&mts.0=regular&location=<zip>
      &parts.0=<part>&parts.1=<part>...
```

Returns JSON with a `stores` array. Each store carries `storeName`,
`address`, `city`, `state`, `storeDistanceWithUnit`, `phoneNumber`, and a
`partsAvailability` map keyed by part number whose entries give
`pickupDisplay` (`available` / `unavailable`) and `pickupSearchQuote`
(e.g. `Available Today`).

Verified properties:

- **Batches parts.** All four watched parts plus the canary return in a
  single request, each store reporting per-part availability.
- **Needs no cookie or session.** A cold, cookieless request returns
  correct results; the `location` query parameter is honoured directly.
- **Gives per-store detail.** Store names, distances and pickup quotes come
  back in the same response, so the notification needs no second call.

For ZIP 33130 it returns 12 stores. At capture time the canary was
available at 9 of them and unavailable at 3, matching the count reported by
the other endpoint.

No browser automation is required. The wizard steps in the user's video
(trade-in, carrier, AppleCare) do not change the part number; unlocked with
no AppleCare is what these part numbers already mean.

### Rejected alternatives

`/shop/sba/availability-message` was the first endpoint found. It works but
is strictly worse here: it returns only the single nearest store, and it
requires a location cookie obtained by POSTing to
`/shop/address/location/update`. Without that cookie it returns `200 OK`
with zero stores for **every** part, including parts stocked at a dozen
stores — a broken session is indistinguishable from "no stock". That trap
cost real time during investigation (it reported a year-old iPhone 17 as
unavailable nationwide). Choosing `pickup-message` removes the cookie
dependency and therefore removes the trap entirely.

`/shop/sba/pickup-detail` returns an empty body under every parameter
combination tried, including with an in-stock part and a fully bootstrapped
session. Unused.

`/shop/fulfillment-messages` returns HTTP 541 (bot-block). Unused.

### Product discovery comes from the buy page, not an API

The buy page embeds a JSON array of every purchasable configuration:

```json
{"sku":"MJW44","partNumber":"MJW44LL/A","price":{"fullPrice":1299.00},
 "category":"iphone","name":"iPhone\u00a018 Pro\u00a0Max 256GB Black"}
```

32 entries, one per iPhone configuration, carrying the part number, the
full human-readable config name and the price. AppleCare SKUs are not in
this array, so they need no filtering.

### Non-breaking spaces in product names

**The `name` values use U+00A0 (non-breaking space), not ordinary spaces:**
`iPhone\u00a018 Pro\u00a0Max 256GB Black`.

A naive `"iPhone 18 Pro Max" in name` test therefore matches nothing and
yields an empty watch list — the exact "silently watching nothing" failure
this design is built to avoid. It was observed during investigation: the
first filter written returned zero parts against a page that plainly
contained all four.

All configuration matching MUST normalize with `unicodedata.normalize`
(NFKC) and collapse U+00A0 to a space before comparing. This applies to
any Apple-supplied label, not just this array.

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
check: fetch, compare, notify, persist, exit. There is no session or
cookie state to establish, because the primary endpoint needs none. A failed run is a
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

**`watcher/apple.py`** — the only module that knows apple.com exists. Owns
product discovery (buy-page parsing), the pickup-message request, label
normalization and response parsing. Exposes
`discover_products(html) -> list[Product]` and
`fetch_pickup(zip, parts) -> list[PartAvailability]`, raising
`TransientError` on network/bot-block failures and `ImplausibleResponse`
when the canary check fails. Returns dataclasses, never raw JSON. If Apple
changes anything, this is the file that changes.

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
class Product:
    part: str          # "MJW44LL/A"
    name: str          # "iPhone 18 Pro Max 256GB Black" (NBSP-normalized)
    price: float       # 1299.00

@dataclass(frozen=True)
class Store:
    store_id: str      # "R623"
    name: str          # "Brickell City Centre"
    street: str        # "701 S. Miami Avenue"
    city: str          # "Miami"
    state: str         # "FL"
    distance: str      # "0.63 mi"
    quote: str         # "Available Today"

@dataclass(frozen=True)
class PartAvailability:
    part: str
    name: str            # from the matching Product, NBSP-normalized
    available: bool      # any store with pickupDisplay == "available"
    stores: list[Store]  # only stores where it IS available

    @property
    def store_count(self) -> int:
        return len(self.stores)
```

Names come from the buy page's own product array, normalized for
non-breaking spaces, so labels never drift from what Apple publishes.

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
(default 24) or empty, the script fetches the buy page and parses its
embedded product array (see Key findings). Each entry's `name` is
NBSP-normalized and matched against the watch config: `model` as a prefix,
`capacity` as a substring, and `colors` as the trailing word unless `["*"]`.
The result — part number, name and price — is cached in `state.json`.

AppleCare SKUs are absent from this array and need no filtering.

If discovery finds **zero** matching parts, that is an error condition, not
an empty result: the script alerts once and leaves prior state untouched.
Silently watching nothing is the failure this whole section exists to
prevent.

## The canary

Choosing `pickup-message` eliminated the cookie-session trap, but not the
general class of failure it belongs to: an endpoint that answers `200 OK`
with a well-formed, entirely negative response. A `location` value silently
stopped being honoured, a regional block, or a change in how availability is
reported would all read as "no stock everywhere" and the watcher would wait
forever in cheerful silence.

So every request still includes one control part expected to be in stock.
It rides along in the same batched request and costs nothing. Config:

```toml
[canary]
part = "MJQ34LL/A"      # iPhone 18 Pro 256GB Black
```

Decision rule, applied before any comparison:

- Canary available at >0 stores → response is meaningful, trust the readings.
- Canary available at 0 stores → **do not trust the zeros.** Retry once
  after a short backoff. If the canary is still zero, raise
  `ImplausibleResponse`, leave state untouched, and count it as a failed
  run. Repeated failures trip the health alert.

An all-negative response is thus never silently accepted as truth. The
captured fixtures pin both sides: `pickup_message_watched_unavailable_canary_ok.json`
(canary available at 9 of 12 stores, watched parts at 0 — genuine scarcity)
and `availability_session_expired_all_zero.json` (everything 0 — a response
that must not be believed).

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
| Canary available at zero stores | Retry once, then `ImplausibleResponse` |
| Product name fails NBSP normalization | Normalize before compare; never match raw |
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

[telegram]
chat_id = "-5597962862"     # group chat; bot must be a member

[canary]
part = "MJQ34LL/A"

[polling]
jitter_seconds = 45
repeat_minutes = 30
discovery_ttl_hours = 24
failure_alert_threshold = 5
```

`TELEGRAM_BOT_TOKEN` comes from a `.env` file (mode 600, gitignored);
`TELEGRAM_CHAT_ID` may be set there too and overrides `config.toml`. The
token is a secret and never goes in `config.toml` or git. The chat ID is
not a secret and is kept in config for legibility.

The configured chat is a **group** (negative ID), so the bot must be added
to that group. If the bot has BotFather privacy mode enabled it must also
be promoted to admin, or it cannot post. Note that a group silently
becomes a supergroup when upgraded, which changes its ID; a send failing
with `chat not found` after previously working is the signature.

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
- Canary at zero stores → `ImplausibleResponse`, state untouched, no alert.
- Watched part 0 → 4 stores → exactly one alert, correct store list.
- Watched part stays available → repeat only after `repeat_minutes`.
- Watched part available → unavailable → no message, timer cleared.
- Discovery against the real buy-page product array: all 32 entries parse,
  and the NBSP-normalized filter yields exactly the four 256GB Pro Max
  parts. A regression test asserts that matching the *raw* (un-normalized)
  name yields zero parts, pinning the bug that was actually hit.
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
