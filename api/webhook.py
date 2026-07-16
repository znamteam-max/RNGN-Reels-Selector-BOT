from __future__ import annotations

import hmac
import json
import os
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

from reels_bot.config import CATEGORIES, allowed_user_ids, required_env, timezone_name
from reels_bot.google_sheets import append_idea, find_duplicate, get_sheet_info
from reels_bot.parser import ParseError, parse_idea
from reels_bot.telegram_api import send_message


HELP_TEXT = """Отправь идею в формате:

МК | Майкл Джексон выполняет трюки без страховки | 9 | https://ссылка

Подключены: Ф1, Футбол, НБА, ММА, МК, СК.
Оценка мощности: целое число от 1 до 10.

Бот запишет идею в нужную вкладку, поставит «нет» в колонке «Выложено?», добавит дату и пересортирует таблицу по мощности."""


def categories_text() -> str:
    lines = ["Подключённые категории:"]
    for category in CATEGORIES.values():
        lines.append(f"• {category.code} — {category.project_name}")
    lines.extend(
        [
            "",
            "Пока не подключены:",
            "• Теннис — Больше",
            "• НХЛ — Home of Hockey",
        ]
    )
    return "\n".join(lines)


def current_date() -> str:
    return datetime.now(ZoneInfo(timezone_name())).strftime("%d.%m.%Y")


def process_text(chat_id: int, text: str) -> None:
    command = text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower()
    if command in {"/start", "/help"}:
        send_message(chat_id, HELP_TEXT)
        return
    if command == "/categories":
        send_message(chat_id, categories_text())
        return
    if command.startswith("/"):
        send_message(chat_id, "Неизвестная команда. Используй /start или /categories.")
        return

    try:
        idea = parse_idea(text)
    except ParseError as exc:
        send_message(chat_id, f"❌ {exc}")
        return

    sheet_info = get_sheet_info(idea.category.sheet_id)
    duplicate = find_duplicate(sheet_info.title, idea.normalized_url)
    if duplicate:
        send_message(
            chat_id,
            "⚠️ Эта ссылка уже есть в таблице.\n\n"
            f"Раздел: {idea.category.project_name}\n"
            f"Строка до сортировки/текущая строка: {duplicate.row_number}",
        )
        return

    date_value = current_date()
    append_idea(idea, date_value)
    send_message(
        chat_id,
        "✅ Добавлено\n\n"
        f"Раздел: {idea.category.project_name}\n"
        f"Событие: {idea.title}\n"
        f"Мощь: {idea.rating}\n"
        f"Дата: {date_value}",
    )


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send_json(
            200,
            {
                "status": "ok",
                "service": "RNGN Reels Selector Bot",
                "categories": [category.code for category in CATEGORIES.values()],
                "telegram_token_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
                "google_credentials_configured": bool(
                    os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
                ),
                "webhook_secret_configured": bool(os.getenv("TELEGRAM_WEBHOOK_SECRET")),
            },
        )

    def do_POST(self) -> None:
        try:
            expected_secret = required_env("TELEGRAM_WEBHOOK_SECRET")
        except RuntimeError as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})
            return

        received_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(received_secret, expected_secret):
            self._send_json(403, {"ok": False, "error": "invalid webhook secret"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 1_000_000:
                self._send_json(400, {"ok": False, "error": "invalid body size"})
                return

            update = json.loads(self.rfile.read(content_length).decode("utf-8"))
            message = update.get("message")
            if not isinstance(message, dict):
                self._send_json(200, {"ok": True, "ignored": True})
                return

            text = message.get("text")
            chat = message.get("chat") or {}
            sender = message.get("from") or {}
            chat_id = chat.get("id")
            user_id = sender.get("id")

            if not isinstance(chat_id, int) or not isinstance(user_id, int):
                self._send_json(200, {"ok": True, "ignored": True})
                return

            if user_id not in allowed_user_ids():
                send_message(chat_id, "⛔ У тебя нет доступа к этому боту.")
                self._send_json(200, {"ok": True, "authorized": False})
                return

            if not isinstance(text, str) or not text.strip():
                send_message(chat_id, "Отправь текстовое сообщение. Формат есть в /start.")
                self._send_json(200, {"ok": True, "ignored": True})
                return

            process_text(chat_id, text)
            self._send_json(200, {"ok": True})
        except Exception as exc:  # noqa: BLE001 - webhook must return a controlled response
            traceback.print_exc()
            try:
                update_message = locals().get("message") or {}
                error_chat_id = (update_message.get("chat") or {}).get("id")
                if isinstance(error_chat_id, int):
                    send_message(
                        error_chat_id,
                        "❌ Не удалось записать идею. Ошибка сохранена в логах Vercel.",
                    )
            except Exception:
                traceback.print_exc()
            self._send_json(200, {"ok": False, "error": type(exc).__name__})
