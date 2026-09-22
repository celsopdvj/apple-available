#!/usr/bin/env bash
# Installs the every-minute cron entry, idempotently.
#
# flock keeps a slow run (retries and backoff can exceed 60s) from being
# overlapped by the next tick, which would race two processes on state.json.
# -n means the overlapping tick is skipped rather than queued.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINE="* * * * * cd $ROOT && mkdir -p logs && /usr/bin/flock -n logs/.lock .venv/bin/python -m watcher --no-jitter >> logs/watcher.log 2>&1"
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v -F "apple-available" > "$TMP" || true
echo "$LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "installed:"
crontab -l | grep watcher
