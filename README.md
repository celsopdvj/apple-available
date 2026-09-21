# Apple Availability Watcher

Polls Apple's store-pickup endpoint every 3 minutes and sends a Telegram
message the moment an **iPhone 18 Pro Max 256GB** (any color) becomes
available for in-store pickup near **ZIP 33130**.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Put it in `.env` (this file is gitignored and must stay that way):

   ```bash
   cp .env.example .env
   chmod 600 .env
   # edit .env and set TELEGRAM_BOT_TOKEN=<your token>
   ```

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
[watch]
model = "iPhone 18 Pro Max"   # exact model name as Apple writes it
capacity = "256GB"
colors = ["*"]                 # or ["Black", "Silver"]
```

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
