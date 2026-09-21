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
