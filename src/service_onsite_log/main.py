from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from .parser import parse_whatsapp_to_json
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import (
    get_all_mappings,
    get_all_messages_ordered,
    get_distinct_senders,
    get_messages_for_filter,
    get_latest_day_index,
    init_db,
    resolve_and_store_messages,
    update_day_selection,
    update_message_bodies,
    update_sender_mappings,
)
from .utils import (
    format_filtered_rows,
    group_messages_by_day,
    parse_stored_timestamp,
    save_upload_file,
    validate_date_range,
)

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
static_dir = PACKAGE_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def build_statistics() -> dict:
    selected = [msg for msg in get_all_messages_ordered() if msg["is_selected"]]
    names = sorted({msg["matched_name"] for msg in selected})
    dates = [
        dt.date().isoformat()
        for msg in selected
        if (dt := parse_stored_timestamp(msg["timestamp"])) is not None
    ]
    return {
        "names": names,
        "min_date": min(dates) if dates else "",
        "max_date": max(dates) if dates else "",
        "months": [
            {"value": f"{month:02d}", "label": label}
            for month, label in enumerate(
                ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
                start=1,
            )
        ],
        "default_month": max(dates)[5:7] if dates else "01",
    }

def build_review_context(day_index: int = 0) -> dict:
    days = group_messages_by_day(get_all_messages_ordered())
    total_days = len(days)
    dated_days = [day for day in days if day["iso_date"] != "undated"]

    if total_days > 0:
        safe_index = max(0, min(day_index, total_days - 1))
        current_day = days[safe_index]
    else:
        safe_index = 0
        current_day = None

    return {
        "total_days": total_days,
        "day_index": safe_index,
        "current_day": current_day,
        "day_options": [
            {"index": index, "display_date": day["display_date"], "iso_date": day["iso_date"]}
            for index, day in enumerate(days)
        ],
        "first_review_date": dated_days[0]["iso_date"] if dated_days else "",
        "last_review_date": dated_days[-1]["iso_date"] if dated_days else "",
    }

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"dashboard": build_statistics()},
    )


@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse(request=request, name="upload.html", context={})


@app.get("/statistics")
async def statistics_page_alias():
    return RedirectResponse(url="/", status_code=303)

@app.get("/review", response_class=HTMLResponse)
async def review_page(request: Request, day_index: int | None = Query(default=None)):
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context=build_review_context(day_index=day_index if day_index is not None else get_latest_day_index()),
    )

@app.post("/review")
async def save_and_navigate_day(
    current_day_index: int = Form(default=0),
    target_day_index: int = Form(default=0),
    day_msg_ids: list[int] = Form(default=[]),
    selected_ids: list[int] = Form(default=[]),
    message_ids: list[int] = Form(default=[]),
    message_bodies: list[str] = Form(default=[]),
):
    update_day_selection(day_msg_ids, selected_ids)
    update_message_bodies(message_ids, message_bodies)
    next_index = max(0, target_day_index)
    return RedirectResponse(url=f"/review?day_index={next_index}", status_code=303)

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    saved_path = await save_upload_file(file)
    parsed = parse_whatsapp_to_json(saved_path)
    resolve_and_store_messages(parsed)

    return RedirectResponse(url="/mappings", status_code=303)


@app.get("/mappings", response_class=HTMLResponse)
async def mappings_page(request: Request):
    return templates.TemplateResponse(request=request, name="mappings.html", context={"mappings": get_all_mappings()})

@app.post("/mappings")
async def update_mappings(
    raw_senders: list[str] = Form(default=[]),
    matched_names: list[str] = Form(default=[]),
):
    update_sender_mappings(raw_senders, matched_names)
    return RedirectResponse(url=f"/review?day_index={get_latest_day_index()}", status_code=303)


@app.get("/statistics/data")
async def statistics_data(
    names: list[str] = Query(default=[]),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    payload = build_statistics()
    selected = set(names)
    # Preserve per-day filtering by recalculating from the selected messages.
    filtered = []
    for msg in get_all_messages_ordered():
        dt = parse_stored_timestamp(msg["timestamp"])
        if not msg["is_selected"] or dt is None or (selected and msg["matched_name"] not in selected):
            continue
        if start_date and dt.date() < start_date:
            continue
        if end_date and dt.date() > end_date:
            continue
        filtered.append({"name": msg["matched_name"], "timestamp": msg["timestamp"], "message": msg["message"]})
    payload["messages"] = filtered
    payload["selected_names"] = sorted(selected)
    payload["start_date"] = start_date.isoformat() if start_date else ""
    payload["end_date"] = end_date.isoformat() if end_date else ""
    return JSONResponse(payload)


@app.get("/messages", response_class=HTMLResponse)
async def view_messages():
    return RedirectResponse(
        url="/review/selected",
        status_code=303,
    )


@app.get("/review/selected", response_class=HTMLResponse)
async def selected_messages_page(
    request: Request,
    sender: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    error_message, apply_dates = validate_date_range(start_date, end_date)
    selected_sender = (sender or "").strip()
    raw_msgs = get_messages_for_filter(selected_sender or None)
    rows = format_filtered_rows(raw_msgs, start_date, end_date, apply_dates)

    return templates.TemplateResponse(
        request=request,
        name="selected_messages.html",
        context={
            "rows": rows,
            "sender_options": get_distinct_senders(),
            "selected_sender": selected_sender,
            "start_date": start_date.isoformat() if start_date else "",
            "end_date": end_date.isoformat() if end_date else "",
            "error_message": error_message,
        },
    )
