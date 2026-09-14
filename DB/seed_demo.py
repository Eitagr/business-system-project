# Idempotent demo rows for the final-project chatbot.
# Rotem Miron's 19:00 slot is outside config hours; insert, don't book().

from datetime import datetime, timedelta

from Features import appointments, customers, leads

ROTEM_MIRON = {
    "name": "רותם מירון",
    "phone": "050-1112233",
    "email": "rotem.miron@example.co.il",
    "address": "הרצל 12, תל אביב",
    "age": 29,
    "national_id": "123456789",
}
ROTEM_LEVI = {
    "name": "רותם לוי",
    "phone": "050-4445566",
    "email": "rotem.levi@example.co.il",
    "address": "אלנבי 8, תל אביב",
    "age": 34,
    "national_id": "987654321",
}
DEMO_START = datetime(2027, 1, 19, 19, 0, 0)

EXTRA_CUSTOMERS = (
    ("נועה כהן", "052-1234567", "noa.cohen@example.co.il", "דיזנגוף 40, תל אביב", 27, "111222333"),
    ("יואב ברק", "054-7654321", "yoav.barak@example.co.il", "בן יהודה 15, חיפה", 41, "222333444"),
    ("מיכל אדרי", "053-9988776", "michal.edri@example.co.il", "הנשיא 3, ירושלים", 36, "333444555"),
)

EXTRA_LEADS = (
    ("דנה שמש", "050-2003004", "dana.shemesh@example.co.il", "website"),
    ("אורי מזרחי", "052-3004005", "uri.mizrahi@example.co.il", "referral"),
    ("טל אברהם", "053-4005006", None, "walk-in"),
    ("הילה רוזן", "054-5006007", "hila.rosen@example.co.il", "website"),
    ("גיא פרץ", "055-6007008", None, "walk-in"),
)


def _by_name(db, name):
    for row in db.list_customers(active=None):
        if row["name"] == name:
            return row
    return None


def _ensure_customer(db, fields) -> int:
    existing = _by_name(db, fields["name"])
    if existing:
        customers.update(
            db,
            existing["id"],
            fields["name"],
            fields["phone"],
            fields["email"],
            fields["address"],
            fields["age"],
            fields["national_id"],
        )
        return existing["id"]
    return customers.add(
        db,
        fields["name"],
        fields["phone"],
        fields["email"],
        fields["address"],
        fields["age"],
        fields["national_id"],
    )


def _has_demo_appointment(db, customer_id) -> bool:
    stamp = appointments.stamp(DEMO_START)
    for row in db.customer_appointments(customer_id):
        if row["starts_at"] == stamp and row["status"] == "scheduled":
            return True
    return False


def _pad_customers(db) -> None:
    for name, phone, email, address, age, nid in EXTRA_CUSTOMERS:
        if len(db.list_customers(active=None)) >= 5:
            return
        if _by_name(db, name):
            continue
        customers.add(db, name, phone, email, address, age, nid)


def _pad_leads(db) -> None:
    for name, phone, email, source in EXTRA_LEADS:
        if len(db.list_leads()) >= 5:
            return
        if any(row["name"] == name for row in db.list_leads()):
            continue
        leads.add(db, name, phone, email, source)


def _pad_appointments(db, config) -> None:
    if len(db.list_appointments()) >= 5:
        return
    host = {
        "name": EXTRA_CUSTOMERS[0][0],
        "phone": EXTRA_CUSTOMERS[0][1],
        "email": EXTRA_CUSTOMERS[0][2],
        "address": EXTRA_CUSTOMERS[0][3],
        "age": EXTRA_CUSTOMERS[0][4],
        "national_id": EXTRA_CUSTOMERS[0][5],
    }
    customer_id = _ensure_customer(db, host)
    service = config["services"][0]["name"]
    starts = [
        datetime(2026, 11, 2, 10, 0, 0),
        datetime(2026, 11, 3, 11, 0, 0),
        datetime(2026, 11, 4, 9, 30, 0),
        datetime(2026, 11, 5, 14, 0, 0),
    ]
    for when in starts:
        if len(db.list_appointments()) >= 5:
            return
        try:
            appointments.book(db, config, customer_id, service, when)
        except appointments.BookingError:
            continue


def _pad_receipts(db, config) -> None:
    if len(db.list_receipts()) >= 5:
        return
    service = config["services"][0]
    people = db.list_customers(active=True)
    appts = db.list_appointments()
    if not people:
        return
    i = 0
    while len(db.list_receipts()) < 5 and i < 8:
        person = people[i % len(people)]
        appt = appts[i % len(appts)] if appts else None
        db.add_receipt(
            person["id"],
            appt["id"] if appt else None,
            f"RCP-SEED-{i:03d}",
            service["price"],
            person["name"],
            person["phone"],
            person["email"],
            person["address"],
            service["name"],
            service["minutes"],
            appt["starts_at"] if appt else "2026-11-02 10:00:00",
        )
        i += 1


def ensure(db, config) -> None:
    miron_id = _ensure_customer(db, ROTEM_MIRON)
    _ensure_customer(db, ROTEM_LEVI)

    if not _has_demo_appointment(db, miron_id):
        service = next(item for item in config["services"] if item["name"] == "Consultation")
        ends = DEMO_START + timedelta(minutes=service["minutes"])
        # ponytail: 19:00 is outside Sunday hours in config.yaml. book() would
        # reject it; the course demo requires this row. Upgrade path: widen
        # sunday hours if the calendar should treat 19:00 as a legal booking.
        db.add_appointment(
            miron_id,
            service["name"],
            appointments.stamp(DEMO_START),
            appointments.stamp(ends),
        )

    _pad_customers(db)
    _pad_leads(db)
    _pad_appointments(db, config)
    _pad_receipts(db, config)
