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
STATE_SHEET_TITLE = "BOT_STATE"


@dataclass(frozen=True)
class DuplicateMatch:
    row_number: int
    original_url: str


@dataclass(frozen=True)
class SheetInfo:
    title: str
    row_count: int


@dataclass(frozen=True)
class PendingState:
    row_number: int
    pending_url: str
    pending_details: str


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


def _ensure_state_sheet() -> None:
    response = (
        _service()
        .spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id(),
            fields="sheets(properties(sheetId,title))",
        )
        .execute(num_retries=2)
    )
    for sheet in response.get("sheets", []):
        if sheet.get("properties", {}).get("title") == STATE_SHEET_TITLE:
            return

    created = (
        _service()
        .spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id(),
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": STATE_SHEET_TITLE,
                                "hidden": True,
                                "gridProperties": {"rowCount": 100, "columnCount": 6},
                            }
                        }
                    }
                ]
            },
        )
        .execute(num_retries=2)
    )
    _service().spreadsheets().values().update(
        spreadsheetId=spreadsheet_id(),
        range=f"'{STATE_SHEET_TITLE}'!A1:F1",
        valueInputOption="RAW",
        body={
            "values": [[
                "chat_id",
                "user_id",
                "pending_url",
                "pending_details",
                "updated_at",
                "version",
            ]]
        },
    ).execute(num_retries=2)


def get_pending_state(chat_id: int, user_id: int) -> PendingState | None:
    _ensure_state_sheet()
    response = (
        _service()
        .spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id(),
            range=f"'{STATE_SHEET_TITLE}'!A2:F",
        )
        .execute(num_retries=2)
    )
    for row_number, row in enumerate(response.get("values", []), start=2):
        row_chat = str(row[0]).strip() if len(row) > 0 else ""
        row_user = str(row[1]).strip() if len(row) > 1 else ""
        if row_chat == str(chat_id) and row_user == str(user_id):
            return PendingState(
                row_number=row_number,
                pending_url=str(row[2]).strip() if len(row) > 2 else "",
                pending_details=str(row[3]).strip() if len(row) > 3 else "",
            )
    return None


def set_pending_state(
    chat_id: int,
    user_id: int,
    *,
    pending_url: str = "",
    pending_details: str = "",
    updated_at: str = "",
) -> None:
    current = get_pending_state(chat_id, user_id)
    values = [[
        str(chat_id),
        str(user_id),
        pending_url,
        pending_details,
        updated_at,
        "1",
    ]]
    if current:
        target = f"'{STATE_SHEET_TITLE}'!A{current.row_number}:F{current.row_number}"
        _service().spreadsheets().values().update(
            spreadsheetId=spreadsheet_id(),
            range=target,
            valueInputOption="RAW",
            body={"values": values},
        ).execute(num_retries=2)
        return

    _service().spreadsheets().values().append(
        spreadsheetId=spreadsheet_id(),
        range=f"'{STATE_SHEET_TITLE}'!A:F",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute(num_retries=2)


def clear_pending_state(chat_id: int, user_id: int) -> None:
    current = get_pending_state(chat_id, user_id)
    if not current:
        return
    _service().spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id(),
        range=f"'{STATE_SHEET_TITLE}'!A{current.row_number}:F{current.row_number}",
        body={},
    ).execute(num_retries=2)


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


def _find_template_rows(sheet_title: str, rating: int) -> tuple[int | None, int | None]:
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
    rating_row: int | None = None
    validation_row: int | None = None

    for row_number, row in enumerate(rows, start=2):
        current_rating = row[0] if len(row) > 0 else ""
        posted_status = row[2] if len(row) > 2 else ""
        if str(posted_status).strip().casefold() != "нет":
            continue
        if validation_row is None:
            validation_row = row_number
        try:
            rating_matches = int(float(str(current_rating).replace(",", "."))) == rating
        except (TypeError, ValueError):
            rating_matches = False
        if rating_matches:
            rating_row = row_number
            break
    return rating_row, validation_row


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
    rating_row, validation_row = _find_template_rows(info.title, idea.rating)

    append_response = (
        _service()
        .spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id(),
            range=f"'{escaped}'!A:F",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [[idea.title, idea.url, idea.rating, "", "нет", date_value]]},
        )
        .execute(num_retries=2)
    )

    updated_range = append_response.get("updates", {}).get("updatedRange", "")
    appended_row = _row_number_from_updated_range(updated_range)
    requests: list[dict] = []

    if appended_row is not None:
        if rating_row is not None and rating_row != appended_row:
            requests.append({"copyPaste": {
                "source": {"sheetId": idea.category.sheet_id, "startRowIndex": rating_row - 1, "endRowIndex": rating_row, "startColumnIndex": 2, "endColumnIndex": 3},
                "destination": {"sheetId": idea.category.sheet_id, "startRowIndex": appended_row - 1, "endRowIndex": appended_row, "startColumnIndex": 2, "endColumnIndex": 3},
                "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL",
            }})

        if validation_row is not None and validation_row != appended_row:
            requests.append({"copyPaste": {
                "source": {"sheetId": idea.category.sheet_id, "startRowIndex": validation_row - 1, "endRowIndex": validation_row, "startColumnIndex": 3, "endColumnIndex": 5},
                "destination": {"sheetId": idea.category.sheet_id, "startRowIndex": appended_row - 1, "endRowIndex": appended_row, "startColumnIndex": 3, "endColumnIndex": 5},
                "pasteType": "PASTE_DATA_VALIDATION", "pasteOrientation": "NORMAL",
            }})

        white_centered_format = {
            "backgroundColor": {"red": 1, "green": 1, "blue": 1},
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        }
        for start_column, end_column in ((0, 2), (3, 6)):
            requests.append({"repeatCell": {
                "range": {"sheetId": idea.category.sheet_id, "startRowIndex": appended_row - 1, "endRowIndex": appended_row, "startColumnIndex": start_column, "endColumnIndex": end_column},
                "cell": {"userEnteredFormat": white_centered_format},
                "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment",
            }})
        requests.append({"repeatCell": {
            "range": {"sheetId": idea.category.sheet_id, "startRowIndex": appended_row - 1, "endRowIndex": appended_row, "startColumnIndex": 2, "endColumnIndex": 3},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}},
            "fields": "userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment",
        }})

    requests.append({"repeatCell": {
        "range": {"sheetId": idea.category.sheet_id, "startRowIndex": 1, "endRowIndex": info.row_count, "startColumnIndex": 5, "endColumnIndex": 6},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd.mm.yyyy"}, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}},
        "fields": "userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment",
    }})
    requests.append({"sortRange": {
        "range": {"sheetId": idea.category.sheet_id, "startRowIndex": 1, "endRowIndex": info.row_count, "startColumnIndex": 0, "endColumnIndex": 6},
        "sortSpecs": [{"dimensionIndex": 2, "sortOrder": "DESCENDING"}],
    }})

    _service().spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id(), body={"requests": requests}
    ).execute(num_retries=2)
