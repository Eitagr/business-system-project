# Booking rules. No SQL, no printing.
#
# Every appointment must survive several checks before it is stored: the
# business is open, the whole appointment fits inside opening hours, the
# customer is real and active, and it does not overlap another scheduled
# appointment.
#
# ponytail: check-then-insert below is not atomic. Two processes booking the
# same slot at the same instant could both pass the overlap check before
# either inserts. Harmless for a single-user CLI; a multi-user version needs
# this wrapped in a transaction (e.g. BEGIN IMMEDIATE) to close the race.
#
# ponytail: hours in config.yaml are assumed same-day (open before close).
# An overnight business (close time past midnight) is not supported.
#
# ponytail: one appointment at a time is assumed; there is no staff member
# or room dimension, so two different staff cannot be booked in parallel.

from datetime import datetime, timedelta

from Features import customers
from Features.customers import CustomerError

STATUSES = ("scheduled", "done", "cancelled")


class BookingError(Exception):
    """A booking or status change broke a business rule."""


def stamp(moment: datetime) -> str:
    """Format a datetime the way the database stores it."""
    return moment.isoformat(sep=" ", timespec="seconds")


def service_by_name(config, name):
    wanted = (name or "").strip().lower()
    for service in config["services"]:
        if service["name"].lower() == wanted:
            return service
    known = ", ".join(service["name"] for service in config["services"])
    raise BookingError(f"Unknown service '{name}'. Available: {known}.")


def opening_hours(config, when: datetime):
    """Opening and closing datetimes for the day `when` falls on.

    Returns None when the business is closed that day.
    """
    day = when.strftime("%A").lower()
    hours = config["hours"].get(day)
    if not hours:
        return None
    if len(hours) != 2:
        raise BookingError(f"config.yaml: hours for {day} must be [open, close].")
    opens, closes = (datetime.strptime(value, "%H:%M").time() for value in hours)
    return (
        datetime.combine(when.date(), opens),
        datetime.combine(when.date(), closes),
    )


def slot_minutes(config) -> int:
    raw = (config.get("booking") or {}).get("slot_minutes") or 15
    return max(1, int(raw))


def _overlapping(db, starts_at, ends_at, ignore_id=None):
    rows = db.overlapping_appointments(starts_at, ends_at)
    if ignore_id is None:
        return list(rows)
    return [row for row in rows if row["id"] != ignore_id]


def _raise_overlap(clashes):
    first = clashes[0]
    raise BookingError(
        f"Overlaps appointment #{first['id']} "
        f"({first['starts_at']} to {first['ends_at']})."
    )


def _fit(db, config, customer_id, service_name, starts_at: datetime, ignore_id=None):
    """Hours, active customer, and overlap — shared by book() and reschedule()."""
    service = service_by_name(config, service_name)
    ends_at = starts_at + timedelta(minutes=service["minutes"])

    hours = opening_hours(config, starts_at)
    if hours is None:
        raise BookingError(f"Closed on {starts_at:%A}.")
    opens, closes = hours
    if starts_at < opens or ends_at > closes:
        raise BookingError(
            f"{service['name']} runs {service['minutes']} min "
            f"({starts_at:%H:%M}-{ends_at:%H:%M}) but "
            f"{starts_at:%A} hours are {opens:%H:%M}-{closes:%H:%M}."
        )

    try:
        customers.require(db, customer_id, active_only=True)
    except CustomerError as exc:
        raise BookingError(str(exc)) from exc

    clashes = _overlapping(db, stamp(starts_at), stamp(ends_at), ignore_id)
    if clashes:
        _raise_overlap(clashes)
    return service, ends_at


def open_slots(db, config, day, service_name, now=None, ignore_id=None) -> list:
    """Start times on `day` (YYYY-MM-DD) that fit this service.

    A candidate is kept only if the whole interval is inside opening hours
    and does not overlap a scheduled appointment. Times that have already
    passed today are omitted. `now` is injectable so the check does not
    depend on the wall clock. `ignore_id` leaves that appointment out of
    the overlap check so a reschedule can keep its current start.
    """
    try:
        day_date = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError as exc:
        raise BookingError(f"'{day}' is not a date in YYYY-MM-DD form.") from exc

    service = service_by_name(config, service_name)
    duration = timedelta(minutes=service["minutes"])
    hours = opening_hours(config, datetime.combine(day_date, datetime.min.time()))
    if hours is None:
        return []
    opens, closes = hours
    step = timedelta(minutes=slot_minutes(config))
    now = now or datetime.now()

    starts = []
    start = opens
    while start + duration <= closes:
        if day_date == now.date() and start <= now:
            start += step
            continue
        if not _overlapping(db, stamp(start), stamp(start + duration), ignore_id):
            starts.append(start)
        start += step
    return starts


def book(db, config, customer_id, service_name, starts_at: datetime) -> int:
    service, ends_at = _fit(db, config, customer_id, service_name, starts_at)
    return db.add_appointment(customer_id, service["name"], stamp(starts_at), stamp(ends_at))


def reschedule(db, config, appointment_id, customer_id, service_name, starts_at: datetime) -> None:
    current = db.get_appointment(appointment_id)
    if current is None:
        raise BookingError(f"No appointment with id {appointment_id}.")
    if current["status"] == "cancelled":
        raise BookingError("Cancelled appointment cannot be moved; book a new one.")
    service, ends_at = _fit(
        db, config, customer_id, service_name, starts_at, ignore_id=appointment_id
    )
    if not db.update_appointment(
        appointment_id, customer_id, service["name"], stamp(starts_at), stamp(ends_at)
    ):
        raise BookingError(f"No appointment with id {appointment_id}.")


def set_status(db, appointment_id, status) -> None:
    if status not in STATUSES:
        raise BookingError(f"Status must be one of: {', '.join(STATUSES)}.")
    current = db.get_appointment(appointment_id)
    if current is None:
        raise BookingError(f"No appointment with id {appointment_id}.")
    if status == "scheduled" and current["starts_at"] and current["ends_at"]:
        clashes = _overlapping(
            db, current["starts_at"], current["ends_at"], ignore_id=appointment_id
        )
        if clashes:
            _raise_overlap(clashes)
    if not db.set_appointment_status(appointment_id, status):
        raise BookingError(f"No appointment with id {appointment_id}.")


def on_day(db, day: str) -> list:
    """Appointments starting on `day`, given as YYYY-MM-DD."""
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError as exc:
        raise BookingError(f"'{day}' is not a date in YYYY-MM-DD form.") from exc
    return db.appointments_on(day)


def open_for_customer(db, customer_id) -> list:
    """Scheduled appointments only — used after identity verification."""
    customers.require(db, customer_id)
    return [row for row in db.customer_appointments(customer_id) if row["status"] == "scheduled"]
