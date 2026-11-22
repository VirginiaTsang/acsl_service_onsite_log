from datetime import date, datetime
from pathlib import Path
import re

from fastapi import UploadFile

# utils.py -> service_onsite_log -> src -> <project root: service_onsite_log>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = PROJECT_ROOT / "uploads"


def sanitize_filename(filename: str | None) -> str:
    name = Path(filename or "uploaded_chat.txt").name
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    return safe or "uploaded_chat.txt"


async def save_upload_file(file: UploadFile) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(file.filename)
    saved_path = UPLOAD_DIR / safe_name

    if saved_path.exists():
        stem = saved_path.stem
        suffix = saved_path.suffix or ".txt"
        counter = 1
        while (UPLOAD_DIR / f"{stem}_{counter}{suffix}").exists():
            counter += 1
        saved_path = UPLOAD_DIR / f"{stem}_{counter}{suffix}"

    saved_path.write_bytes(await file.read())
    return saved_path


def parse_stored_timestamp(ts_str: str) -> datetime | None:
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(ts_str.strip(), fmt)
        except ValueError:
            continue
    return None


def validate_date_range(start_date: date | None, end_date: date | None) -> tuple[str | None, bool]:
    if not start_date and not end_date:
        return None, False
    if not start_date or not end_date:
        return "Please select both a Start Date and an End Date.", False
    if end_date < start_date:
        return "End Date must be the same as or later than Start Date.", False
    return None, True


def format_filtered_rows(
    raw_msgs: list[dict],
    start_date: date | None,
    end_date: date | None,
    apply_dates: bool,
) -> list[dict]:
    rows = []
    for r in raw_msgs:
        dt = parse_stored_timestamp(r["timestamp"])
        if apply_dates:
            if dt is None or start_date is None or end_date is None:
                continue
            if not (start_date <= dt.date() <= end_date):
                continue

        if dt is not None:
            display_date = f"{dt.day}/{dt.month}/{dt.strftime('%Y')}"
            display_time = dt.strftime("%H:%M:%S")
        else:
            parts = r["timestamp"].split(" ", 1)
            display_date = parts[0]
            display_time = parts[1] if len(parts) > 1 else ""

        rows.append(
            {
                "name": r["matched_name"],
                "date": display_date,
                "time": display_time,
                "message": r["message"],
            }
        )
    return rows

def group_messages_by_day(all_messages: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    undated_messages: list[dict] = []

    for msg in all_messages:
        dt = parse_stored_timestamp(msg["timestamp"])
        item = {
            "id": msg["id"],
            "time": dt.strftime("%H:%M:%S") if dt is not None else msg["timestamp"],
            "sender": msg["matched_name"],
            "message": msg["message"],
            "is_selected": bool(msg.get("is_selected", 1)),
        }

        if dt is None:
            undated_messages.append(item)
            continue

        iso_key = dt.date().isoformat()
        if iso_key not in grouped:
            grouped[iso_key] = {
                "iso_date": iso_key,
                "display_date": f"{dt.day}/{dt.month}/{dt.strftime('%Y')}",
                "messages": [],
            }

        grouped[iso_key]["messages"].append(item)

    days = [grouped[k] for k in sorted(grouped.keys())]
    if undated_messages:
        days.append(
            {
                "iso_date": "undated",
                "display_date": "Unparsed Timestamp",
                "messages": undated_messages,
            }
        )
    return days
