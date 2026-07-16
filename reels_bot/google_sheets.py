from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from reels_bot.config import required_env, spreadsheet_id
from reels_bot.parser import Idea, normalize_url


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


@dataclass(frozen=True)
class DuplicateMatch:
    row_number: int
    original_url: str


@dataclass(frozen=True)
class SheetInfo:
    title: str
    row_count: int


def _escape_sheet_title(value: str) -> str:
    return value.replace("'", "''")


@lru_cache(maxsize=1)
def _service():
    raw = required_env("GOOGLE_SERVICE_ACCOUNT_JSON")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON. Paste the whole key as one value."
        ) from exc

    if isinstance(info.get("private_key"), str):
        info["private_key"] = info["private_key"].replace("\\n", "\n")

    credentials = Credentials.from_service_account_info(info, scopes=[SHEETS_SCOPE])
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


@lru_cache(maxsize=32)
def get_sheet_info(sheet_id: int) -> SheetInfo:
    response = (
        _service()
        .spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id(),
            fields="sheets(properties(sheetId,title,gridProperties(rowCount)))",
        )
        .execute(num_retries=2)
    )
    for sheet in response.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("sheetId") == sheet_id:
            return SheetInfo(
                title=properties["title"],
                row_count=int(properties.get("gridProperties", {}).get("rowCount", 1000)),
            )
    raise RuntimeError(f"Google Sheets tab with sheetId={sheet_id} was not found")


def ensure_date_header(sheet_title: str) -> None:
    escaped = _escape_sheet_title(sheet_title)
    (
        _service()
        .spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id(),
            range=f"'{escaped}'!F1",
            valueInputOption="RAW",
            body={"values": [["Когда добавлено"]]},
        )
        .execute(num_retries=2)
    )


def find_duplicate(sheet_title: str, normalized_url: str) -> DuplicateMatch | None:
    escaped = _escape_sheet_title(sheet_title)
    response = (
        _service()
        .spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id(),
            range=f"'{escaped}'!B2:B",
            majorDimension="COLUMNS",
        )
        .execute(num_retries=2)
    )
    columns = response.get("values", [])
    existing_urls = columns[0] if columns else []

    for row_number, original_url in enumerate(existing_urls, start=2):
        if not isinstance(original_url, str) or not original_url.strip():
            continue
        try:
            existing_normalized = normalize_url(original_url)
        except ValueError:
            continue
        if existing_normalized == normalized_url:
            return DuplicateMatch(row_number=row_number, original_url=original_url)
    return None


def append_idea(idea: Idea, date_value: str) -> None:
    info = get_sheet_info(idea.category.sheet_id)
    ensure_date_header(info.title)
    escaped = _escape_sheet_title(info.title)

    (
        _service()
        .spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id(),
            range=f"'{escaped}'!A:F",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={
                "values": [
                    [idea.title, idea.url, idea.rating, "", "нет", date_value]
                ]
            },
        )
        .execute(num_retries=2)
    )

    (
        _service()
        .spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id(),
            body={
                "requests": [
                    {
                        "sortRange": {
                            "range": {
                                "sheetId": idea.category.sheet_id,
                                "startRowIndex": 1,
                                "endRowIndex": info.row_count,
                                "startColumnIndex": 0,
                                "endColumnIndex": 6,
                            },
                            "sortSpecs": [
                                {
                                    "dimensionIndex": 2,
                                    "sortOrder": "DESCENDING",
                                }
                            ],
                        }
                    }
                ]
            },
        )
        .execute(num_retries=2)
    )
