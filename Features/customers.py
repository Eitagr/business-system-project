# Customer rules. No SQL, no printing: the CLI passes values in and shows
# whatever comes back.

import hmac
import re
import sqlite3

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DIGITS = re.compile(r"\d+")


class CustomerError(Exception):
    """A customer could not be created, updated, or found."""


def _national_id(raw, required=False):
    text = (raw or "").strip()
    if not text:
        if required:
            raise CustomerError("National ID is required.")
        return None
    digits = "".join(DIGITS.findall(text))
    # No Israeli checksum: the course demo ID 123456789 fails it.
    if len(digits) != 9:
        raise CustomerError("National ID must be 9 digits.")
    return digits


def _validate(name, phone, email, age) -> tuple:
    name = (name or "").strip()
    phone = (phone or "").strip()
    email = (email or "").strip() or None

    if not name:
        raise CustomerError("Name is required.")
    if not phone:
        raise CustomerError("Phone is required.")
    if email and not EMAIL.match(email):
        raise CustomerError(f"'{email}' is not a valid email address.")
    if age is not None and not 0 < age < 130:
        raise CustomerError("Age must be between 1 and 129.")
    return name, phone, email


def _integrity(exc, email):
    detail = str(exc).lower()
    if "national_id" in detail:
        raise CustomerError("A customer with this national ID already exists.") from exc
    raise CustomerError(f"A customer with the email {email} already exists.") from exc


def _public(row):
    data = dict(row)
    data.pop("national_id", None)
    return data


def add(db, name, phone, email=None, address=None, age=None, national_id=None) -> int:
    name, phone, email = _validate(name, phone, email, age)
    address = (address or "").strip() or None
    try:
        return db.add_customer(name, phone, email, address, age, _national_id(national_id))
    except sqlite3.IntegrityError as exc:
        _integrity(exc, email)


def update(db, customer_id, name, phone, email=None, address=None, age=None, national_id=None) -> None:
    current = require(db, customer_id)
    name, phone, email = _validate(name, phone, email, age)
    address = (address or "").strip() or None
    parsed = _national_id(national_id)
    if parsed is None:
        parsed = current["national_id"]
    try:
        db.update_customer(customer_id, name, phone, email, address, age, parsed)
    except sqlite3.IntegrityError as exc:
        _integrity(exc, email)


def require(db, customer_id, active_only=False):
    """Return the customer, or raise if that id does not exist.

    Appointments and receipts live in other database files and cannot use a
    foreign key, so every reference to a customer is checked here instead.
    """
    customer = db.get_customer(customer_id)
    if customer is None:
        raise CustomerError(f"No customer with id {customer_id}.")
    if active_only and not customer["active"]:
        raise CustomerError(f"Customer #{customer_id} ({customer['name']}) is deactivated.")
    return customer


def deactivate(db, customer_id) -> None:
    require(db, customer_id)
    db.set_customer_active(customer_id, False)


def reactivate(db, customer_id) -> None:
    require(db, customer_id)
    db.set_customer_active(customer_id, True)


def find(db, term):
    term = (term or "").strip()
    return db.find_customers(term) if term else db.list_customers()


def find_by_name(db, term) -> list:
    term = (term or "").strip()
    if not term:
        return []
    return [_public(row) for row in db.find_customers_by_name(term)]


def has_national_id(db, customer_id) -> bool:
    return bool(require(db, customer_id)["national_id"])


def verify_id(db, customer_id, national_id) -> bool:
    stored = require(db, customer_id)["national_id"]
    offered = _national_id(national_id)
    if not stored or not offered:
        return False
    return hmac.compare_digest(stored, offered)
