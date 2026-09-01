"""Run: python3 check_booking.py

Exercises the booking rules against a real, throwaway Database rather than a
mock, so the actual SQL is what gets checked. Plain asserts, stdlib only.
"""

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from DB.db_adapter import Database
from Features import appointments, customers
from Features.appointments import BookingError

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def next_weekday(anchor: date, name: str) -> date:
    target = WEEKDAYS.index(name)
    return anchor + timedelta(days=(target - anchor.weekday()) % 7)


def expect_error(fn, *args):
    try:
        fn(*args)
    except BookingError:
        return
    raise AssertionError(f"expected BookingError from {fn.__name__}{args}")


def main() -> None:
    config = {
        "services": [
            {"name": "Consultation", "minutes": 60, "price": 250.0},
            {"name": "Full session", "minutes": 90, "price": 400.0},
        ],
        "hours": {"monday": ["09:00", "17:00"], "saturday": None},
    }

    anchor = date(2026, 1, 1)
    monday = next_weekday(anchor, "monday")
    saturday = next_weekday(anchor, "saturday")

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(directory=Path(tmp))
        alice = customers.add(db, "Alice", "050-0000001")
        bob = customers.add(db, "Bob", "050-0000002")

        # A normal booking succeeds.
        ten = datetime.combine(monday, datetime.min.time().replace(hour=10))
        first_id = appointments.book(db, config, alice, "Consultation", ten)
        assert isinstance(first_id, int)

        config["booking"] = {"slot_minutes": 15}
        midnight = datetime.combine(monday, datetime.min.time())
        free = [
            slot.strftime("%H:%M")
            for slot in appointments.open_slots(
                db, config, monday.isoformat(), "Consultation", now=midnight
            )
        ]
        assert "09:00" in free
        assert "11:00" in free
        assert "10:00" not in free
        assert "10:30" not in free
        assert appointments.open_slots(db, config, saturday.isoformat(), "Consultation") == []

        # A real overlap (10:30, inside the 10:00-11:00 slot) is rejected.
        expect_error(appointments.book, db, config, bob, "Consultation", ten.replace(minute=30))

        # A booking that only touches the boundary (starts exactly when the
        # first appointment ends) is allowed.
        eleven = ten.replace(hour=11)
        second_id = appointments.book(db, config, bob, "Consultation", eleven)
        assert second_id != first_id

        # Closed day is rejected.
        sat_ten = datetime.combine(saturday, datetime.min.time().replace(hour=10))
        expect_error(appointments.book, db, config, alice, "Consultation", sat_ten)

        # A service that would run past closing time is rejected.
        expect_error(
            appointments.book, db, config, alice, "Full session", ten.replace(hour=16, minute=30)
        )

        # Cancelling frees the slot for rebooking.
        appointments.set_status(db, first_id, "cancelled")
        rebooked_id = appointments.book(db, config, bob, "Consultation", ten)
        assert rebooked_id != first_id

        # Booking against an unknown customer id is rejected.
        expect_error(
            appointments.book, db, config, 9999, "Consultation", ten.replace(hour=13)
        )

        # Booking against a deactivated customer is rejected.
        customers.deactivate(db, alice)
        expect_error(
            appointments.book, db, config, alice, "Consultation", ten.replace(hour=14)
        )

        # Receipt numbering is sequential and year-scoped.
        prefix = "RCP-2026-"
        assert db.last_receipt_number(prefix) is None
        db.add_receipt(bob, None, f"{prefix}001", 250.0, "Bob", None, None, None, None, None, None)
        assert db.last_receipt_number(prefix) == f"{prefix}001"
        db.add_receipt(bob, None, f"{prefix}002", 250.0, "Bob", None, None, None, None, None, None)
        assert db.last_receipt_number(prefix) == f"{prefix}002"

        db.close()

    print("check_booking: all assertions passed")


if __name__ == "__main__":
    main()
