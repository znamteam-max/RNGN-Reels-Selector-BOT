from __future__ import annotations

import requests

from reels_bot.config import required_env


def send_message(chat_id: int, text: str) -> None:
    token = required_env("TELEGRAM_BOT_TOKEN")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    response.raise_for_status()
