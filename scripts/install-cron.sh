#!/usr/bin/env bash
# Installs the every-3-minutes cron entry, idempotently.
#
# Cron triggers the GitHub Action rather than running the check locally, so
# every run shares one cached state: one heartbeat message, no duplicate
# alerts. GitHub's own */15 schedule covers the hours this machine is off.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINE="*/3 * * * * $ROOT/scripts/dispatch.sh"
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v -F "apple-available/scripts/dispatch.sh" \
                       | grep -v -F "python -m watcher" > "$TMP" || true
echo "$LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "installed:"
crontab -l | grep dispatch.sh
