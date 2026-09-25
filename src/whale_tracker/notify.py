"""Push notifications via ntfy (https://ntfy.sh) -- the "rapor gönderir"
half of Aşama 1, which until now only ever wrote to data/observer.log.

ntfy needs no account: the phone app subscribes to a topic name and
anything POSTed to that topic arrives as a notification. The topic name
IS the access control -- anyone who knows it can read (and post to) it --
so it's a long random name kept in a gitignored local file
(data/notify-config.json), never committed. Reports carry only market
data and system health, nothing secret.

Nothing here ever raises into the observer: callers catch NotifyError and
log it. A failed notification must never fail a data-collection cycle."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path
from typing import Any

import requests

CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "notify-config.json"
TOPIC_ENV = "WHALE_TRACKER_NTFY_TOPIC"
DEFAULT_SERVER = "https://ntfy.sh"
DEFAULT_DIGEST_HOUR = 9
_TIMEOUT_S = 15


class NotifyError(RuntimeError):
    """Sending a notification failed."""


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Topic from the environment, else the local config file. An empty
    dict (no topic) means notifications are simply off."""
    config: dict[str, Any] = {}
    if path.is_file():
        config = json.loads(path.read_text(encoding="utf-8"))
    topic = os.environ.get(TOPIC_ENV) or config.get("ntfy_topic")
    if not topic:
        return {}
    return {
        "ntfy_topic": topic,
        "ntfy_server": config.get("ntfy_server", DEFAULT_SERVER),
        "daily_digest_hour": int(config.get("daily_digest_hour", DEFAULT_DIGEST_HOUR)),
    }


def send(config: dict[str, Any], title: str, message: str, *, priority: int = 3, tags: list[str] | None = None) -> None:
    """Publish one notification. JSON publishing (POST to the server root)
    rather than header-based, because ntfy's Title header can't carry
    Turkish characters without RFC 2047 encoding."""
    payload = {
        "topic": config["ntfy_topic"], "title": title, "message": message,
        "priority": priority, "tags": tags or [],
    }
    try:
        response = requests.post(config["ntfy_server"], json=payload, timeout=_TIMEOUT_S)
    except requests.RequestException as error:
        raise NotifyError(f"ntfy isteği başarısız: {type(error).__name__}") from None
    if not response.ok:
        raise NotifyError(f"ntfy HTTP {response.status_code}: {response.text[:200]}")


def init_config(path: Path = CONFIG_PATH) -> str:
    """Create the local config with a fresh random topic if none exists;
    return the topic either way."""
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8")).get("ntfy_topic")
        if existing:
            return existing
    topic = f"whale-tracker-{secrets.token_hex(12)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "ntfy_topic": topic, "ntfy_server": DEFAULT_SERVER, "daily_digest_hour": DEFAULT_DIGEST_HOUR,
    }, indent=2), encoding="utf-8")
    return topic


def main() -> int:
    parser = argparse.ArgumentParser(description="whale-tracker bildirimleri (ntfy)")
    parser.add_argument("--init", action="store_true", help="Rastgele bir ntfy konusu oluştur (yoksa)")
    parser.add_argument("--test", action="store_true", help="Kısa bir deneme bildirimi gönder")
    args = parser.parse_args()
    if args.init:
        topic = init_config()
        print(f"ntfy konusu: {topic}\nTelefonda ntfy uygulamasını aç, '+' ile bu konuya abone ol.")
    if args.test:
        config = load_config()
        if not config:
            print("Bildirim yapılandırılmamış -- önce --init.")
            return 1
        send(config, "whale-tracker deneme", "Bu bir deneme bildirimi. Günlük özet her sabah 09:00'dan sonra gelecek.")
        print("Deneme bildirimi gönderildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
