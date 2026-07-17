from __future__ import annotations

import requests

from reels_bot.config import required_env


def send_message(chat_id: int, text: str, *, force_reply: bool = False) -> None:
    token = required_env("TELEGRAM_BOT_TOKEN")
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if force_reply:
        payload["reply_markup"] = {
            "force_reply": True,
            "selective": True,
            "input_field_placeholder": "Ответь сюда",
        }

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
