#!/usr/bin/env bash
# Triggers the availability check in GitHub Actions.
#
# The check deliberately does NOT run locally: keeping every run inside
# Actions means they all share one cached state, so there is a single
# heartbeat message and no duplicate alerts. This script is just a trigger.
set -uo pipefail

REPO="celsopdvj/apple-available"
GH="${GH:-/usr/bin/gh}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/logs/dispatch.log"
mkdir -p "$(dirname "$LOG")"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

if ! out=$("$GH" workflow run watch.yml --repo "$REPO" 2>&1); then
  echo "$(ts) ERROR dispatch failed: ${out//$'\n'/ }" >> "$LOG"
  exit 1
fi
echo "$(ts) dispatched" >> "$LOG"
