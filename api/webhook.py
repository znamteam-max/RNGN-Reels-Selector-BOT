from __future__ import annotations

import hmac
import json
import os
import time
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

from reels_bot.config import CATEGORIES, allowed_user_ids, required_env, timezone_name
from reels_bot.google_sheets import (
    append_idea,
    clear_pending_state,
    find_duplicate,
    get_pending_state,
    get_sheet_info,
    set_pending_state,
)
from reels_bot.parser import (
    ParseError,
    URL_RE,
    build_idea,
    extract_url,
    normalize_url,
    parse_details,
    parse_idea,
)
from reels_bot.telegram_api import send_message


DETAILS_MARKER = "ЗАЯВКА: "
URL_MARKER = "ССЫЛКА: "

HELP_TEXT = """Отправь идею любым способом:

1) Одним сообщением:
МК | Майкл Джексон выполняет трюки без страховки | 9 | https://ссылка

2) В одном сообщении, но ссылка с новой строки:
МК | Майкл Джексон выполняет трюки без страховки | 9
https://ссылка

3) Двумя отдельными сообщениями в любом порядке:
https://ссылка
МК | Название события | 9

Отвечать на сообщение бота теперь необязательно.

Подключены: Ф1, Футбол, НБА, ММА, МК, СК.
Оценка мощности: целое число от 1 до 10."""


def categories_text() -> str:
    lines = ["Подключённые категории:"]
    for category in CATEGORIES.values():
        lines.append(f"• {category.code} — {category.project_name}")
    lines.extend(["", "Пока не подключены:", "• Теннис — Больше", "• НХЛ — Home of Hockey"])
    return "\n".join(lines)


def current_date() -> str:
    return datetime.now(ZoneInfo(timezone_name())).strftime("%d.%m.%Y")


def state_timestamp() -> str:
    return datetime.now(ZoneInfo(timezone_name())).isoformat(timespec="seconds")


def duplicate_anywhere(normalized_url: str):
    for category in CATEGORIES.values():
        sheet_info = get_sheet_info(category.sheet_id)
        duplicate = find_duplicate(sheet_info.title, normalized_url)
        if duplicate:
            return category, duplicate
    return None


def save_idea(chat_id: int, user_id: int, idea) -> None:
    sheet_info = get_sheet_info(idea.category.sheet_id)
    duplicate = find_duplicate(sheet_info.title, idea.normalized_url)
    clear_pending_state(chat_id, user_id)
    if duplicate:
        send_message(
            chat_id,
            "⚠️ Эта ссылка уже есть в таблице.\n\n"
            f"Раздел: {idea.category.project_name}\n"
            f"Строка: {duplicate.row_number}",
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


def _read_state_with_short_retry(chat_id: int, user_id: int):
    # Telegram can deliver two rapidly sent messages to parallel Vercel invocations.
    # A short retry lets the first invocation finish writing its pending state.
    for attempt in range(3):
        state = get_pending_state(chat_id, user_id)
        if state:
            return state
        if attempt < 2:
            time.sleep(0.45)
    return None


def process_text(chat_id: int, user_id: int, text: str, reply_to_text: str = "") -> None:
    command = text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower()
    if command in {"/start", "/help"}:
        send_message(chat_id, HELP_TEXT)
        return
    if command == "/categories":
        send_message(chat_id, categories_text())
        return
    if command == "/cancel":
        clear_pending_state(chat_id, user_id)
        send_message(chat_id, "✅ Незавершённая заявка очищена.")
        return
    if command.startswith("/"):
        send_message(chat_id, "Неизвестная команда. Используй /start, /categories или /cancel.")
        return

    # Replies remain supported for compatibility.
    if DETAILS_MARKER in reply_to_text:
        raw_details = reply_to_text.split(DETAILS_MARKER, 1)[1].splitlines()[0].strip()
        try:
            idea = build_idea(parse_details(raw_details), text)
        except ParseError as exc:
            send_message(chat_id, f"❌ {exc}")
            return
        save_idea(chat_id, user_id, idea)
        return

    if URL_MARKER in reply_to_text:
        raw_url = reply_to_text.split(URL_MARKER, 1)[1].splitlines()[0].strip()
        try:
            idea = build_idea(parse_details(text), raw_url)
        except ParseError as exc:
            send_message(chat_id, f"❌ {exc}")
            return
        save_idea(chat_id, user_id, idea)
        return

    stripped = text.strip()
    has_url = bool(URL_RE.search(stripped))
    pipe_count = stripped.count("|")

    # Only a URL. If details are already pending, finish immediately.
    if has_url and pipe_count == 0:
        try:
            url = extract_url(stripped)
            normalized = normalize_url(url)
        except ParseError as exc:
            send_message(chat_id, f"❌ {exc}")
            return

        duplicate_result = duplicate_anywhere(normalized)
        if duplicate_result:
            clear_pending_state(chat_id, user_id)
            category, duplicate = duplicate_result
            send_message(
                chat_id,
                "⚠️ Такая ссылка уже есть.\n\n"
                f"Раздел: {category.project_name}\n"
                f"Строка: {duplicate.row_number}",
            )
            return

        state = _read_state_with_short_retry(chat_id, user_id)
        if state and state.pending_details:
            try:
                idea = build_idea(parse_details(state.pending_details), url)
            except ParseError as exc:
                clear_pending_state(chat_id, user_id)
                send_message(chat_id, f"❌ {exc}")
                return
            save_idea(chat_id, user_id, idea)
            return

        set_pending_state(
            chat_id,
            user_id,
            pending_url=url,
            updated_at=state_timestamp(),
        )
        send_message(
            chat_id,
            "✅ Такой ссылки ещё нет. Теперь отправь:\n"
            "ПРОЕКТ | название | оценка\n\n"
            f"{URL_MARKER}{url}",
            force_reply=True,
        )
        return

    # Three details fields. If URL is pending, finish immediately.
    if not has_url and pipe_count == 2:
        try:
            details = parse_details(stripped)
        except ParseError as exc:
            send_message(chat_id, f"❌ {exc}")
            return

        canonical_details = f"{details.category.code} | {details.title} | {details.rating}"
        state = _read_state_with_short_retry(chat_id, user_id)
        if state and state.pending_url:
            try:
                idea = build_idea(details, state.pending_url)
            except ParseError as exc:
                clear_pending_state(chat_id, user_id)
                send_message(chat_id, f"❌ {exc}")
                return
            save_idea(chat_id, user_id, idea)
            return

        set_pending_state(
            chat_id,
            user_id,
            pending_details=canonical_details,
            updated_at=state_timestamp(),
        )
        send_message(
            chat_id,
            "✅ Данные понял. Теперь отправь ссылку отдельным сообщением.\n\n"
            f"{DETAILS_MARKER}{canonical_details}",
            force_reply=True,
        )
        return

    try:
        idea = parse_idea(stripped)
    except ParseError as exc:
        send_message(
            chat_id,
            f"❌ {exc}\n\n"
            "Можно отправить так:\n"
            "МК | Название события | 9\n"
            "https://ссылка",
        )
        return

    save_idea(chat_id, user_id, idea)


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send_json(200, {
            "status": "ok",
            "service": "RNGN Reels Selector Bot",
            "categories": [category.code for category in CATEGORIES.values()],
            "telegram_token_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "google_credentials_configured": bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")),
            "webhook_secret_configured": bool(os.getenv("TELEGRAM_WEBHOOK_SECRET")),
        })

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

            reply_to_message = message.get("reply_to_message") or {}
            reply_to_text = reply_to_message.get("text")
            process_text(
                chat_id,
                user_id,
                text,
                reply_to_text if isinstance(reply_to_text, str) else "",
            )
            self._send_json(200, {"ok": True})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            try:
                update_message = locals().get("message") or {}
                error_chat_id = (update_message.get("chat") or {}).get("id")
                if isinstance(error_chat_id, int):
                    send_message(error_chat_id, "❌ Не удалось записать идею. Ошибка сохранена в логах Vercel.")
            except Exception:
                traceback.print_exc()
            self._send_json(200, {"ok": False, "error": type(exc).__name__})
