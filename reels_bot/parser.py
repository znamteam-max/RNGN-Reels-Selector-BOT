from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from reels_bot.config import CATEGORIES, UNCONNECTED_CATEGORIES, Category, normalize_category_code


URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "igsh",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "si",
}
SOCIAL_HOSTS_WITH_PATH_IDS = {
    "instagram.com",
    "m.instagram.com",
    "tiktok.com",
    "vm.tiktok.com",
    "x.com",
    "twitter.com",
    "threads.net",
    "facebook.com",
    "m.facebook.com",
    "fb.watch",
}


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class IdeaDetails:
    category: Category
    title: str
    rating: int


@dataclass(frozen=True)
class Idea:
    category: Category
    title: str
    rating: int
    url: str
    normalized_url: str


def extract_url(value: str) -> str:
    match = URL_RE.search(value.strip())
    if not match:
        raise ParseError("Не нашёл ссылку, начинающуюся с http:// или https://.")
    return match.group(0).rstrip(".,;:!?)>]}")


def normalize_url(value: str) -> str:
    raw = extract_url(value)
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    port = parts.port
    netloc = host if not port else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")

    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    if host in SOCIAL_HOSTS_WITH_PATH_IDS:
        query_pairs = []
    elif host in {"youtu.be"}:
        query_pairs = []
    elif host in {"youtube.com", "m.youtube.com"} and path == "/watch":
        query_pairs = [(key, val) for key, val in query_pairs if key == "v"]
    else:
        query_pairs = [
            (key, val)
            for key, val in query_pairs
            if key.lower() not in TRACKING_KEYS and not key.lower().startswith("utm_")
        ]

    query = urlencode(query_pairs, doseq=True)
    return urlunsplit(("https", netloc, path, query, ""))


def parse_details(text: str) -> IdeaDetails:
    parts = [part.strip() for part in text.strip().split("|")]
    if len(parts) != 3:
        raise ParseError(
            "Нужны три части через |:\n"
            "МК | Название события | 9"
        )

    raw_category, title, raw_rating = parts
    category_code = normalize_category_code(raw_category)

    if category_code in UNCONNECTED_CATEGORIES:
        project = UNCONNECTED_CATEGORIES[category_code]
        raise ParseError(
            f"Категория «{raw_category}» пока не подключена. Нужна ссылка на вкладку проекта «{project}»."
        )

    category = CATEGORIES.get(category_code)
    if category is None:
        available = ", ".join(item.code for item in CATEGORIES.values())
        raise ParseError(
            f"Неизвестная категория «{raw_category}». Подключены: {available}."
        )

    if not title:
        raise ParseError("Название события не может быть пустым.")

    try:
        rating = int(raw_rating)
    except ValueError as exc:
        raise ParseError("Оценка мощности должна быть целым числом от 1 до 10.") from exc
    if not 1 <= rating <= 10:
        raise ParseError("Оценка мощности должна быть от 1 до 10.")

    return IdeaDetails(category=category, title=title, rating=rating)


def build_idea(details: IdeaDetails, raw_url: str) -> Idea:
    url = extract_url(raw_url)
    return Idea(
        category=details.category,
        title=details.title,
        rating=details.rating,
        url=url,
        normalized_url=normalize_url(url),
    )


def parse_idea(text: str) -> Idea:
    url = extract_url(text)
    text_without_url = URL_RE.sub("", text, count=1).strip()
    text_without_url = text_without_url.strip("| \n\t")
    details = parse_details(text_without_url)
    return build_idea(details, url)
