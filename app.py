# Web shell over Features/. Forms POST into the same functions the CLI uses.
# No extra service layer.

import os
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from urllib.parse import quote

import yaml
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import chat as chat_engine
import nlu
from DB.db_adapter import Database
from DB.seed_demo import ensure as ensure_demo
from Features import appointments, customers, leads, receipts
from Features.receipts import OUTPUT_DIR

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())

STATUS_HE = {
    "scheduled": "מתוזמן",
    "done": "הושלם",
    "cancelled": "בוטל",
    "new": "חדש",
    "contacted": "נוצר קשר",
    "won": "הומר",
    "lost": "אבוד",
}

DAY_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
VIEWS = ("week", "day", "list")

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "atlas-local-dev"),
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.globals["business"] = CONFIG["business"]
templates.env.globals["status_he"] = lambda s: STATUS_HE.get(s or "", s or "")
templates.env.globals["currency"] = CONFIG["business"].get("currency", "")


def get_db():
    db = Database()
    try:
        yield db
    finally:
        db.close()


def _as_dicts(rows):
    return [dict(row) for row in rows]


def _names(db) -> dict:
    return {row["id"]: row["name"] for row in db.list_customers(active=None)}


def _age(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise customers.CustomerError("Age must be between 1 and 129.") from exc


def _amount(raw):
    raw = (raw or "").strip()
    return float(raw) if raw else None


def _when(starts_at, starts_date="", starts_time=""):
    raw = (starts_at or "").strip()
    if not raw and starts_date and starts_time:
        clock = starts_time.strip()
        if len(clock) == 5:
            clock += ":00"
        raw = f"{starts_date.strip()} {clock}"
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")


def _view(raw):
    return raw if raw in VIEWS else "week"


def _parse_day(raw, fallback=None):
    raw = (raw or "").strip()
    if not raw:
        return fallback
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _sunday(day):
    return day - timedelta(days=(day.weekday() + 1) % 7)


def _grid_bounds(config):
    starts, ends = [], []
    for hours in config["hours"].values():
        if not hours:
            continue
        open_at, close_at = (datetime.strptime(value, "%H:%M").time() for value in hours)
        starts.append(open_at.hour * 60 + open_at.minute)
        ends.append(close_at.hour * 60 + close_at.minute)
    return (min(starts), max(ends)) if starts else (9 * 60, 17 * 60)


def _clock_minutes(stamp):
    moment = datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S")
    return moment.hour * 60 + moment.minute


_HE_EXACT = {
    "Name is required.": "שם חובה.",
    "Phone is required.": "טלפון חובה.",
    "Age must be between 1 and 129.": "הגיל חייב להיות בין 1 ל-129.",
    "Cancelled appointment cannot be moved; book a new one.": "אי אפשר להזיז תור מבוטל; קבעו תור חדש.",
    "Amount must be greater than zero.": "הסכום חייב להיות גדול מאפס.",
    "Use convert() so the lead is linked to a customer.": "יש להמיר את הליד ללקוח.",
    "PDF path is not inside receipts_out.": "נתיב ה-PDF אינו בתיקיית הקבלות.",
    "National ID must be 9 digits.": "תעודת זהות חייבת להכיל 9 ספרות.",
    "National ID is required.": "תעודת זהות חובה.",
    "A customer with this national ID already exists.": "כבר קיים לקוח עם תעודת הזהות הזו.",
}

_HE_PREFIX = (
    ("Overlaps appointment", "המשבצת חופפת לתור קיים."),
    ("Closed on", "העסק סגור ביום הזה."),
    ("Unknown service", "שירות לא מוכר."),
    ("A customer with the email", "כבר קיים לקוח עם כתובת הדוא״ל הזו."),
    ("A customer with this national ID already exists.", "כבר קיים לקוח עם תעודת הזהות הזו."),
    ("No customer with id", "לקוח לא נמצא."),
    ("is deactivated.", "הלקוח מושבת."),
    ("is not a valid email address", "כתובת דוא״ל לא תקינה."),
    ("is not a date in YYYY-MM-DD form", "התאריך אינו בפורמט תקין."),
    ("No appointment with id", "תור לא נמצא."),
    ("No lead with id", "ליד לא נמצא."),
    ("No receipt with id", "קבלה לא נמצאה."),
    ("already has a receipt", "לתור הזה כבר הונפקה קבלה."),
    ("was cancelled.", "התור בוטל."),
    ("has no phone number", "לליד אין מספר טלפון, שנדרש ללקוח."),
    ("was already converted", "הליד כבר הומר ללקוח."),
    ("is not priced in config.yaml", "השירות אינו מתומחר בהגדרות."),
    ("is not an amount", "זה אינו סכום תקין."),
    ("Status must be one of", "סטטוס לא חוקי."),
    ("has no service on record", "לתור אין שירות רשום."),
    ("runs ", "השירות לא נכנס בשעות הפעילות."),
)


def _he(msg):
    text = str(msg)
    if text in _HE_EXACT:
        return _HE_EXACT[text]
    for needle, hebrew in _HE_PREFIX:
        if needle in text:
            return hebrew
    return text


def _assert_slot(when):
    step = appointments.slot_minutes(CONFIG)
    if when.second or when.minute % step:
        raise ValueError(f"השעה חייבת להתחלק ל-{step} דקות.")


def _assert_web_when(when):
    _assert_slot(when)
    now = datetime.now()
    if when.date() < now.date() or (when.date() == now.date() and when <= now):
        raise ValueError("אי אפשר לקבוע תור בעבר.")


def _slot_open(day, when, hours, now, scheduled_ranges, allowed_starts=None):
    if hours is None:
        return False
    opens, closes = hours
    if when < opens or when >= closes:
        return False
    if day < now.date() or (day == now.date() and when <= now):
        return False
    for start, end in scheduled_ranges:
        if start <= when < end:
            return False
    if allowed_starts is not None and when not in allowed_starts:
        return False
    return True


def _offset_scheduled(events):
    scheduled = [item for item in events if item["status"] == "scheduled"]
    scheduled.sort(key=lambda item: (item["slot_top"], -item["slot_span"]))
    for i, current in enumerate(scheduled):
        current["offset"] = 0
        for other in scheduled[:i]:
            a0, a1 = current["slot_top"], current["slot_top"] + current["slot_span"]
            b0, b1 = other["slot_top"], other["slot_top"] + other["slot_span"]
            if a0 < b1 and a1 > b0:
                current["offset"] = 50 if not other.get("offset") else 0
                break
    return events


def _appt_path(view, day, **extra):
    view = _view(view)
    if view != "list" and not day:
        day = date.today().isoformat()
    parts = [f"view={view}"]
    if day:
        parts.append(f"day={day}")
    for key, value in extra.items():
        if value not in (None, ""):
            parts.append(f"{key}={quote(str(value))}")
    return "/appointments?" + "&".join(parts)


def _decorate(row, names, grid_start, step):
    item = dict(row)
    item["customer_name"] = names.get(row["customer_id"], f"#{row['customer_id']}")
    start_m = _clock_minutes(row["starts_at"])
    end_m = _clock_minutes(row["ends_at"]) if row["ends_at"] else start_m + step
    item["slot_top"] = (start_m - grid_start) / step
    item["slot_span"] = max((end_m - start_m) / step, 1)
    start_hh = row["starts_at"][11:16]
    end_hh = row["ends_at"][11:16] if row["ends_at"] else ""
    item["when"] = f"{start_hh}–{end_hh}" if end_hh else start_hh
    item["offset"] = 0
    return item


def _ranges(events):
    out = []
    for item in events:
        if item["status"] != "scheduled" or not item.get("starts_at"):
            continue
        start = datetime.strptime(item["starts_at"][:19], "%Y-%m-%d %H:%M:%S")
        end = (
            datetime.strptime(item["ends_at"][:19], "%Y-%m-%d %H:%M:%S")
            if item.get("ends_at")
            else start + timedelta(minutes=30)
        )
        out.append((start, end))
    return out


def _calendar(db, view, focus, names, now=None, service_name=""):
    now = now or datetime.now()
    grid_start, grid_end = _grid_bounds(CONFIG)
    step = appointments.slot_minutes(CONFIG)
    dates = [focus] if view == "day" else [_sunday(focus) + timedelta(days=i) for i in range(7)]
    day_rows = [_as_dicts(appointments.on_day(db, day.isoformat())) for day in dates]
    for rows in day_rows:
        for row in rows:
            if row.get("starts_at"):
                grid_end = max(grid_end, _clock_minutes(row["starts_at"]))
            if row.get("ends_at"):
                grid_end = max(grid_end, _clock_minutes(row["ends_at"]))
    leftover = (grid_end - grid_start) % step
    if leftover:
        grid_end += step - leftover
    ticks = list(range(grid_start, grid_end, step))
    labels = []
    for minute in ticks:
        hour, mins = divmod(minute, 60)
        labels.append(f"{hour:02d}:{mins:02d}" if mins % 30 == 0 else "")

    extra = {"cal_service": service_name} if service_name else {}
    days = []
    for day, rows in zip(dates, day_rows):
        iso = day.isoformat()
        hours = appointments.opening_hours(CONFIG, datetime.combine(day, dtime.min))
        closed = hours is None
        events = _offset_scheduled(
            [_decorate(row, names, grid_start, step) for row in rows]
        )
        allowed = None
        if service_name:
            try:
                allowed = set(appointments.open_slots(db, CONFIG, iso, service_name, now=now))
            except appointments.BookingError:
                allowed = set()
        busy = _ranges(events)
        slots = []
        for minute in ticks:
            hour, mins = divmod(minute, 60)
            clock = f"{hour:02d}:{mins:02d}"
            when = datetime.combine(day, dtime(hour, mins))
            live = _slot_open(day, when, hours, now, busy, allowed)
            href = (
                _appt_path(view, focus.isoformat(), book_date=iso, book_time=clock, **extra)
                if live
                else None
            )
            slots.append({"time": clock, "href": href})
        days.append(
            {
                "iso": iso,
                "label": DAY_HE[day.weekday()],
                "num": day.strftime("%d/%m"),
                "closed": closed,
                "today": day == now.date(),
                "events": events,
                "slots": slots,
            }
        )
    return {"days": days, "labels": labels, "rows": len(ticks)}


def _go(path, ok=None, error=None):
    parts = []
    if ok:
        parts.append(f"ok={quote(ok)}")
    if error:
        parts.append(f"error={quote(_he(error))}")
    if not parts:
        return RedirectResponse(path, status_code=303)
    sep = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{sep}{'&'.join(parts)}", status_code=303)


def _page(request, name, extra):
    extra.setdefault("ok", request.query_params.get("ok", ""))
    extra.setdefault("error", request.query_params.get("error", ""))
    extra.setdefault("nav", name)
    return templates.TemplateResponse(request, f"{name}.html", extra)


@app.on_event("startup")
def _startup():
    db = Database()
    try:
        ensure_demo(db, CONFIG)
    finally:
        db.close()


# --- home / chat ------------------------------------------------------------


@app.api_route("/", methods=["GET", "HEAD"])
def home(request: Request):
    return templates.TemplateResponse(
        request, "chat.html", {"nav": "chat", "gemini": nlu.configured()}
    )


@app.post("/chat/message")
def chat_message(payload: dict, request: Request, db: Database = Depends(get_db)):
    text = (payload.get("text") or "").strip() if isinstance(payload, dict) else ""
    state = dict(request.session.get("chat") or chat_engine.new_session())
    reply, state = chat_engine.handle(db, state, text)
    request.session["chat"] = state
    return {
        "reply": reply,
        "kind": chat_engine.kind_of(reply, state),
        "nlu": nlu.source(),
    }


@app.post("/chat/reset")
def chat_reset(request: Request):
    request.session["chat"] = chat_engine.new_session()
    return {
        "reply": "שיחה חדשה. איך קוראים לך, ומתי התור?",
        "kind": "plain",
        "nlu": nlu.source(),
    }


# --- customers --------------------------------------------------------------


@app.get("/customers")
def customers_get(
    request: Request,
    q: str = "",
    inactive: str = "",
    edit: str = "",
    db: Database = Depends(get_db),
):
    show_inactive = inactive == "1"
    if show_inactive:
        rows = db.list_customers(active=False)
    else:
        rows = customers.find(db, q)
    editing = db.get_customer(int(edit)) if edit.isdigit() else None
    return _page(
        request,
        "customers",
        {
            "rows": _as_dicts(rows),
            "q": q,
            "inactive": show_inactive,
            "editing": dict(editing) if editing else None,
        },
    )


@app.post("/customers/add")
def customers_add(
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    age: str = Form(""),
    national_id: str = Form(""),
    db: Database = Depends(get_db),
):
    try:
        if not (national_id or "").strip():
            raise customers.CustomerError("National ID is required.")
        cid = customers.add(db, name, phone, email, address, _age(age), national_id)
    except customers.CustomerError as exc:
        return _go("/customers", error=str(exc))
    return _go("/customers", ok=f"נוסף לקוח #{cid}")


@app.post("/customers/{customer_id}/update")
def customers_update(
    customer_id: int,
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    age: str = Form(""),
    national_id: str = Form(""),
    db: Database = Depends(get_db),
):
    try:
        customers.update(db, customer_id, name, phone, email, address, _age(age), national_id)
    except customers.CustomerError as exc:
        return _go(f"/customers?edit={customer_id}", error=str(exc))
    return _go("/customers", ok=f"עודכן לקוח #{customer_id}")


@app.post("/customers/{customer_id}/deactivate")
def customers_deactivate(customer_id: int, db: Database = Depends(get_db)):
    try:
        customers.deactivate(db, customer_id)
    except customers.CustomerError as exc:
        return _go("/customers", error=str(exc))
    return _go("/customers", ok=f"לקוח #{customer_id} הושבת")


@app.post("/customers/{customer_id}/reactivate")
def customers_reactivate(customer_id: int, db: Database = Depends(get_db)):
    try:
        customers.reactivate(db, customer_id)
    except customers.CustomerError as exc:
        return _go("/customers?inactive=1", error=str(exc))
    return _go("/customers", ok=f"לקוח #{customer_id} הופעל מחדש")


# --- appointments -----------------------------------------------------------


@app.get("/appointments")
def appointments_get(
    request: Request,
    view: str = "week",
    day: str = "",
    edit: str = "",
    book_customer: str = "",
    book_service: str = "",
    book_date: str = "",
    book_time: str = "",
    cal_service: str = "",
    db: Database = Depends(get_db),
):
    view = _view(view)
    error = request.query_params.get("error", "")
    parsed = _parse_day(day)
    if day and parsed is None:
        error = error or _he(f"'{day}' is not a date in YYYY-MM-DD form.")
    focus = parsed or date.today()
    day = focus.isoformat()
    names = _names(db)
    known = {service["name"] for service in CONFIG["services"]}
    if cal_service not in known:
        cal_service = ""

    slots, slot_error = [], ""
    ignore = int(edit) if edit.isdigit() else None
    if book_date and book_service and not book_time:
        try:
            slots = appointments.open_slots(
                db, CONFIG, book_date, book_service, ignore_id=ignore
            )
        except appointments.BookingError as exc:
            slot_error = _he(exc)

    extra = {"cal_service": cal_service} if cal_service else {}
    if view == "list":
        if parsed:
            try:
                rows = _as_dicts(appointments.on_day(db, parsed.isoformat()))
            except appointments.BookingError as exc:
                rows, error = [], error or _he(exc)
        else:
            rows = _as_dicts(db.list_appointments())
        cal = None
        prev_day = next_day = ""
    else:
        rows = []
        cal = _calendar(db, view, focus, names, service_name=cal_service)
        step = timedelta(days=1 if view == "day" else 7)
        prev_day = (focus - step).isoformat()
        next_day = (focus + step).isoformat()

    editing = db.get_appointment(int(edit)) if edit.isdigit() else None
    editing = dict(editing) if editing else None
    if editing:
        editing["date"] = editing["starts_at"][:10]
        editing["time"] = editing["starts_at"][11:16]
        editing["customer_name"] = names.get(editing["customer_id"], f"#{editing['customer_id']}")

    stay_day = "" if view == "list" else day
    return _page(
        request,
        "appointments",
        {
            "error": error,
            "rows": rows,
            "names": names,
            "view": view,
            "day": day if parsed or view != "list" else "",
            "focus": day,
            "prev_day": prev_day,
            "next_day": next_day,
            "cal": cal,
            "cal_service": cal_service,
            "slot_step": appointments.slot_minutes(CONFIG) * 60,
            "services": CONFIG["services"],
            "active_customers": _as_dicts(db.list_customers(active=True)),
            "book_customer": book_customer,
            "book_service": book_service or cal_service,
            "book_date": book_date,
            "book_time": book_time,
            "slots": slots,
            "slot_error": slot_error,
            "statuses": appointments.STATUSES,
            "editing": editing,
            "stay": _appt_path(view, stay_day, **extra),
        },
    )


@app.post("/appointments/book")
def appointments_book(
    customer_id: int = Form(...),
    service: str = Form(...),
    starts_at: str = Form(""),
    starts_date: str = Form(""),
    starts_time: str = Form(""),
    view: str = Form("week"),
    day: str = Form(""),
    cal_service: str = Form(""),
    db: Database = Depends(get_db),
):
    dest = _appt_path(view, day, **({"cal_service": cal_service} if cal_service else {}))
    try:
        when = _when(starts_at, starts_date, starts_time)
        _assert_web_when(when)
        aid = appointments.book(db, CONFIG, customer_id, service, when)
    except (ValueError, appointments.BookingError) as exc:
        return _go(dest, error=str(exc))
    return _go(dest, ok=f"נקבע תור #{aid}")


@app.post("/appointments/{appointment_id}/status")
def appointments_status(
    appointment_id: int,
    status: str = Form(...),
    view: str = Form("week"),
    day: str = Form(""),
    cal_service: str = Form(""),
    db: Database = Depends(get_db),
):
    dest = _appt_path(view, day, **({"cal_service": cal_service} if cal_service else {}))
    try:
        appointments.set_status(db, appointment_id, status)
    except appointments.BookingError as exc:
        return _go(dest, error=str(exc))
    return _go(dest, ok=f"תור #{appointment_id} → {STATUS_HE.get(status, status)}")


@app.post("/appointments/{appointment_id}/reschedule")
def appointments_reschedule(
    appointment_id: int,
    customer_id: int = Form(...),
    service: str = Form(...),
    starts_at: str = Form(""),
    starts_date: str = Form(""),
    starts_time: str = Form(""),
    view: str = Form("week"),
    day: str = Form(""),
    cal_service: str = Form(""),
    db: Database = Depends(get_db),
):
    extra = {"cal_service": cal_service} if cal_service else {}
    dest = _appt_path(view, day, **extra)
    try:
        when = _when(starts_at, starts_date, starts_time)
        _assert_slot(when)
        appointments.reschedule(db, CONFIG, appointment_id, customer_id, service, when)
    except (ValueError, appointments.BookingError) as exc:
        return _go(_appt_path(view, day, edit=appointment_id, **extra), error=str(exc))
    return _go(dest, ok=f"עודכן תור #{appointment_id}")


# --- leads ------------------------------------------------------------------


@app.get("/leads")
def leads_get(request: Request, db: Database = Depends(get_db)):
    return _page(
        request,
        "leads",
        {"rows": _as_dicts(db.list_leads()), "names": _names(db)},
    )


@app.post("/leads/add")
def leads_add(
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    source: str = Form(""),
    address: str = Form(""),
    notes: str = Form(""),
    db: Database = Depends(get_db),
):
    try:
        lid = leads.add(db, name, phone, email, source, address, notes)
    except leads.LeadError as exc:
        return _go("/leads", error=str(exc))
    return _go("/leads", ok=f"נוסף ליד #{lid}")


@app.post("/leads/{lead_id}/convert")
def leads_convert(lead_id: int, db: Database = Depends(get_db)):
    try:
        cid = leads.convert(db, lead_id)
    except leads.LeadError as exc:
        return _go("/leads", error=str(exc))
    return _go("/leads", ok=f"ליד #{lead_id} הומר ללקוח #{cid}")


# --- receipts ---------------------------------------------------------------


def _eligible_appointments(db):
    taken = {row["appointment_id"] for row in db.list_receipts() if row["appointment_id"]}
    names = _names(db)
    out = []
    for row in db.list_appointments():
        if row["status"] == "cancelled" or row["id"] in taken:
            continue
        item = dict(row)
        item["customer_name"] = names.get(row["customer_id"], f"#{row['customer_id']}")
        out.append(item)
    return out


@app.get("/receipts")
def receipts_get(request: Request, db: Database = Depends(get_db)):
    return _page(
        request,
        "receipts",
        {
            "rows": _as_dicts(db.list_receipts()),
            "eligible": _eligible_appointments(db),
        },
    )


@app.post("/receipts/issue")
def receipts_issue(
    appointment_id: int = Form(...),
    amount: str = Form(""),
    db: Database = Depends(get_db),
):
    try:
        number = receipts.issue(db, CONFIG, appointment_id, _amount(amount))
    except (receipts.ReceiptError, ValueError) as exc:
        return _go("/receipts", error=str(exc))
    return _go("/receipts", ok=f"הונפקה קבלה {number}")


def _pdf(db, receipt_id, regenerate=False):
    receipt = db.get_receipt(receipt_id)
    if receipt is None:
        return _go("/receipts", error=f"No receipt with id {receipt_id}.")
    path = Path(receipt["pdf_path"]) if receipt["pdf_path"] else None
    if regenerate or path is None or not path.is_file():
        try:
            path = receipts.reprint(db, CONFIG, receipt_id)
        except receipts.ReceiptError as exc:
            return _go("/receipts", error=str(exc))
    resolved = Path(path).resolve()
    if OUTPUT_DIR.resolve() not in resolved.parents:
        return _go("/receipts", error="PDF path is not inside receipts_out.")
    return FileResponse(resolved, filename=f"{receipt['number']}.pdf", media_type="application/pdf")


@app.post("/receipts/{receipt_id}/reprint")
def receipts_reprint(receipt_id: int, db: Database = Depends(get_db)):
    return _pdf(db, receipt_id, regenerate=True)


@app.get("/receipts/{receipt_id}/pdf")
def receipts_pdf(receipt_id: int, db: Database = Depends(get_db)):
    return _pdf(db, receipt_id)
