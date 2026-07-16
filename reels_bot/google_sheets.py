from __future__ import annotations

import json
import re
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


def _find_template_row(sheet_title: str, rating: int) -> int | None:
    """Find a formatted existing row with the same rating and status 'нет'."""
    escaped = _escape_sheet_title(sheet_title)
    response = (
        _service()
        .spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id(),
            range=f"'{escaped}'!C2:E",
        )
        .execute(num_retries=2)
    )
    rows = response.get("values", [])
    fallback_row: int | None = None

    for row_number, row in enumerate(rows, start=2):
        current_rating = row[0] if len(row) > 0 else ""
        posted_status = row[2] if len(row) > 2 else ""
        is_not_posted = str(posted_status).strip().casefold() == "нет"
        if not is_not_posted:
            continue

        if fallback_row is None:
            fallback_row = row_number

        try:
            rating_matches = int(float(str(current_rating).replace(",", "."))) == rating
        except (TypeError, ValueError):
            rating_matches = False

        if rating_matches:
            return row_number

    return fallback_row


def _row_number_from_updated_range(updated_range: str) -> int | None:
    match = re.search(r"!A(\d+):F(\d+)$", updated_range)
    if not match:
        return None
    first_row = int(match.group(1))
    last_row = int(match.group(2))
    return first_row if first_row == last_row else None


def append_idea(idea: Idea, date_value: str) -> None:
    info = get_sheet_info(idea.category.sheet_id)
    ensure_date_header(info.title)
    escaped = _escape_sheet_title(info.title)
    template_row = _find_template_row(info.title, idea.rating)

    append_response = (
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

    updated_range = append_response.get("updates", {}).get("updatedRange", "")
    appended_row = _row_number_from_updated_range(updated_range)
    requests: list[dict] = []

    if template_row is not None and appended_row is not None and template_row != appended_row:
        source = {
            "sheetId": idea.category.sheet_id,
            "startRowIndex": template_row - 1,
            "endRowIndex": template_row,
            "startColumnIndex": 0,
            "endColumnIndex": 6,
        }
        destination = {
            "sheetId": idea.category.sheet_id,
            "startRowIndex": appended_row - 1,
            "endRowIndex": appended_row,
            "startColumnIndex": 0,
            "endColumnIndex": 6,
        }
        requests.extend(
            [
                {
                    "copyPaste": {
                        "source": source,
                        "destination": destination,
                        "pasteType": "PASTE_FORMAT",
                        "pasteOrientation": "NORMAL",
                    }
                },
                {
                    "copyPaste": {
                        "source": source,
                        "destination": destination,
                        "pasteType": "PASTE_DATA_VALIDATION",
                        "pasteOrientation": "NORMAL",
                    }
                },
            ]
        )

    requests.append(
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
    )

    (
        _service()
        .spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id(),
            body={"requests": requests},
        )
        .execute(num_retries=2)
    )
