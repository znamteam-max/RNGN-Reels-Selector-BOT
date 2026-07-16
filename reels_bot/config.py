from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_SPREADSHEET_ID = "1CtaLj8F4L9TOmTBNj5RX8NYw9heWQYAA7o3gp6ZAK78"
DEFAULT_ALLOWED_USER_ID = "52203584"
DEFAULT_TIMEZONE = "Europe/Moscow"


@dataclass(frozen=True)
class Category:
    code: str
    project_name: str
    sheet_id: int


CATEGORIES: dict[str, Category] = {
    "Ф1": Category("Ф1", "Весь Спорт — Формула-1", 2107475345),
    "ФУТБОЛ": Category("Футбол", "Весь Спорт — Футбол", 785605706),
    "НБА": Category("НБА", "Баскетбол «Взял Мяч»", 294600800),
    "ММА": Category("ММА", "Весь Спорт — ММА", 1937499593),
    "МК": Category("МК", "Music Core", 2135464428),
    "СК": Category("СК", "Sport Core", 1404936508),
}

CATEGORY_ALIASES: dict[str, str] = {
    "F1": "Ф1",
    "Ф-1": "Ф1",
    "FORMULA1": "Ф1",
    "FORMULA-1": "Ф1",
    "ФОРМУЛА1": "Ф1",
    "ФОРМУЛА-1": "Ф1",
    "FOOTBALL": "ФУТБОЛ",
    "NBA": "НБА",
    "MMA": "ММА",
    "MC": "МК",
    "MUSICCORE": "МК",
    "MUSIC CORE": "МК",
    "SC": "СК",
    "SPORTCORE": "СК",
    "SPORT CORE": "СК",
}

UNCONNECTED_CATEGORIES = {
    "ТЕННИС": "Больше",
    "НХЛ": "Home of Hockey",
    "NHL": "Home of Hockey",
}


def normalize_category_code(value: str) -> str:
    normalized = " ".join(value.strip().upper().replace("Ё", "Е").split())
    compact = normalized.replace(" ", "")
    if normalized in CATEGORIES:
        return normalized
    if normalized in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[normalized]
    if compact in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[compact]
    return normalized


def spreadsheet_id() -> str:
    return os.getenv("SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID).strip()


def allowed_user_ids() -> set[int]:
    raw = os.getenv("ALLOWED_TELEGRAM_USER_IDS", DEFAULT_ALLOWED_USER_ID)
    result: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError as exc:
            raise RuntimeError(
                "ALLOWED_TELEGRAM_USER_IDS must contain comma-separated numeric IDs"
            ) from exc
    return result


def timezone_name() -> str:
    return os.getenv("TIMEZONE", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
