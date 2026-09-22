# Apple Availability Watcher

Polls Apple's store-pickup endpoint every 3 minutes and sends a Telegram
message the moment an **iPhone 18 Pro Max 256GB** (any color) becomes
available for in-store pickup near **ZIP 33130**.

## Where it runs

Every check runs inside GitHub Actions (`.github/workflows/watch.yml`).
There are two triggers:

| Trigger | Interval | Role |
|---|---|---|
| `scripts/dispatch.sh` from local cron | 3 min | Primary, while the machine is awake |
| The workflow's own `schedule` | 15 min | Fallback, for when it is not |

The local cron entry **triggers** the Action; it does not run the check
itself. That is the whole point: because every run happens inside Actions,
they all share one `actions/cache` state, so there is a single heartbeat
message and no duplicate alerts. Running the checker locally *and* in the
cloud would give each copy its own `state.json` and double everything.

The workflow's `concurrency` group serialises runs, so a dispatch landing on
top of a scheduled run queues rather than racing on that state.

State lives in `actions/cache`. If it is ever lost, the worst case is one
duplicate alert and a fresh heartbeat message -- noisy, never silent.

`*/15` is deliberate: `*/5` is the most contended cron expression on GitHub
and is routinely delayed or dropped. Scheduled workflows are best-effort in
general, and GitHub disables them after 60 days of repository inactivity. A
frozen "Last checked" timestamp on the heartbeat is how you would notice.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Put it in `.env` (this file is gitignored and must stay that way):

   ```bash
   cp .env.example .env
   chmod 600 .env
   # edit .env: TELEGRAM_BOT_TOKEN=<your token>
   #            TELEGRAM_CHAT_ID=<your group id>
   ```

   For the GitHub Action, set the same two values as repository secrets
   (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). The chat id is kept out of
   `config.toml` because this repository is public.

3. **Add the bot to your Telegram group.** The configured chat
   (`-1004333816460`) is a supergroup, so the bot must be a member. If the bot has
   BotFather privacy mode enabled, promote it to admin or it cannot post.

4. Verify:

   ```bash
   .venv/bin/python -m watcher --check-telegram
   ```

5. Install the cron entry:

   ```bash
   ./scripts/install-cron.sh
   ```

## Usage

```bash
.venv/bin/python -m watcher                  # one check (what cron runs)
.venv/bin/python -m watcher --dry-run        # print messages, send nothing, save nothing
.venv/bin/python -m watcher --status         # current state, no network
.venv/bin/python -m watcher --check-telegram # verify token and chat access
.venv/bin/python -m watcher --verbose        # debug logging
```

Logs land in `logs/watcher.log`.

## Changing what is watched

Edit `config.toml`:

```toml
[[watch]]
model = "iPhone 18 Pro Max"   # exact model name as Apple writes it
capacity = "256GB"
colors = ["*"]                 # or ["Black", "Silver"]

[[watch]]
model = "iPhone 18 Pro"        # a second target, if you want one
capacity = "512GB"
colors = ["Black"]
```

Repeat the `[[watch]]` block for as many model/capacity combinations as you
want; they are all fetched in a single request. Editing this file takes
effect on the very next run — the part cache is keyed to the watch
configuration, so it is discarded whenever you change a target.

`model` and `capacity` are matched as a single prefix against Apple's own
product names, so `"iPhone 18 Pro"` will **not** match `"iPhone 18 Pro Max"`.
The part list is rediscovered from the buy page once a day; part numbers are
never hardcoded.

## How it decides

Each run fetches per-store availability for the watched parts **plus a
canary part** known to be in stock (`MJQ34LL/A`, iPhone 18 Pro 256GB Black).

The endpoint can return a perfectly well-formed `200 OK` reporting zero
stores for everything — that looks identical to "nothing is in stock". The
canary discriminates: if the canary reads zero, the response is not believed,
state is left untouched, and the run counts as a failure. Five consecutive
failures send one "watcher is unhealthy" message, then silence until it
recovers.

State is **never written on a failed run**, so a network blip can neither
fabricate an alert nor erase a real one.

You get a message when a watched part goes unavailable → available, and a
reminder every 30 minutes while it stays available.

## Liveness heartbeat

The watcher keeps a single "Watcher is live" message in the group and
**edits it in place** on every run, so you can see the last-checked time
without getting a notification every three minutes. It lists each watched
color and the canary's store count.

Its message id is stored in `state.json` as `heartbeat_message_id`. If you
delete the message, the next run notices the edit was rejected and posts a
fresh one. When a real availability alert fires, the heartbeat is deleted
and re-sent so it stays the newest message rather than being buried above
the alert.

The timestamp is what makes consecutive heartbeats differ — Telegram
rejects an edit whose text is byte-identical to what is already there.

## Telegram chat IDs

A Telegram group silently becomes a *supergroup* when it is upgraded, and
its chat ID changes. `getChat` keeps accepting the old ID while
`sendMessage` rejects it, so a stale ID looks fine until an alert is
actually sent. `send()` therefore follows Telegram's `migrate_to_chat_id`
and resends rather than dropping the message, logging the new ID so
`config.toml` can be corrected.

## Limitation

On WSL this runs only while Windows is awake and the distro is up. Stock
appearing overnight with the laptop closed will be missed. Nothing in the
code assumes WSL — moving it to a VPS or GitHub Actions is a deployment
change, not a rewrite.
