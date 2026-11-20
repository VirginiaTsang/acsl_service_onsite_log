from contextlib import asynccontextmanager
from datetime import date
import html
import json
from pathlib import Path
from .parser import parse_whatsapp_to_json
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import (
    get_all_mappings,
    get_all_messages_ordered,
    get_distinct_senders,
    get_messages_for_filter,
    get_recent_messages,
    init_db,
    resolve_and_store_messages,
    update_day_selection,
    update_sender_mappings,
)
from .utils import (
    format_filtered_rows,
    group_messages_by_day,
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


def build_home_context(status_banner: str = "") -> dict:
    return {
        "status_banner": status_banner,
        "mappings": get_all_mappings(),
        "msg_json_preview": json.dumps(get_recent_messages(100), ensure_ascii=False, indent=2),
    }

def build_review_context(day_index: int = 0) -> dict:
    days = group_messages_by_day(get_all_messages_ordered())
    total_days = len(days)

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
    }

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_home_context(),
    )

@app.get("/review", response_class=HTMLResponse)
async def review_page(request: Request, day_index: int = Query(default=0)):
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context=build_review_context(day_index=day_index),
    )

@app.post("/review")
async def save_and_navigate_day(
    current_day_index: int = Form(default=0),
    target_day_index: int = Form(default=0),
    day_msg_ids: list[int] = Form(default=[]),
    selected_ids: list[int] = Form(default=[]),
):
    update_day_selection(day_msg_ids, selected_ids)
    next_index = max(0, target_day_index)
    return RedirectResponse(url=f"/review?day_index={next_index}", status_code=303)

@app.post("/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    saved_path = await save_upload_file(file)
    parsed = parse_whatsapp_to_json(saved_path)
    count = resolve_and_store_messages(parsed)

    banner = (
        f"Saved <strong>{html.escape(saved_path.name)}</strong> to "
        f"<code>uploads/</code> and stored {count} messages."
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_home_context(status_banner=banner),
    )

@app.post("/mappings")
async def update_mappings(
    raw_senders: list[str] = Form(default=[]),
    matched_names: list[str] = Form(default=[]),
):
    update_sender_mappings(raw_senders, matched_names)
    return RedirectResponse(url="/", status_code=303)


@app.get("/messages", response_class=HTMLResponse)
async def view_messages(
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
        name="messages.html",
        context={
            "rows": rows,
            "sender_options": get_distinct_senders(),
            "selected_sender": selected_sender,
            "start_date": start_date.isoformat() if start_date else "",
            "end_date": end_date.isoformat() if end_date else "",
            "error_message": error_message,
        },
    )