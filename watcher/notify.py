from __future__ import annotations
import logging

import requests

log = logging.getLogger(__name__)

BUY_URL = "https://www.apple.com/shop/buy-iphone/iphone-18-pro"
MAX_STORES_LISTED = 10


def format_available(res, zip_code: str, repeat: bool = False) -> str:
    head = "🔔 Still available (reminder)" if repeat else "🟢 Available for pickup"
    noun = "store" if res.store_count == 1 else "stores"
    lines = [head, f"*{res.name}*", "", f"{res.store_count} {noun} near {zip_code}:"]
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
