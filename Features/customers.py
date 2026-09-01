# Customer rules. No SQL, no printing: the CLI passes values in and shows
# whatever comes back.

import re
import sqlite3

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CustomerError(Exception):
    """A customer could not be created, updated, or found."""


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


def add(db, name, phone, email=None, address=None, age=None) -> int:
    name, phone, email = _validate(name, phone, email, age)
    address = (address or "").strip() or None
    try:
        return db.add_customer(name, phone, email, address, age)
    except sqlite3.IntegrityError as exc:
        raise CustomerError(f"A customer with the email {email} already exists.") from exc


def update(db, customer_id, name, phone, email=None, address=None, age=None) -> None:
    require(db, customer_id)
    name, phone, email = _validate(name, phone, email, age)
    address = (address or "").strip() or None
    try:
        db.update_customer(customer_id, name, phone, email, address, age)
    except sqlite3.IntegrityError as exc:
        raise CustomerError(f"A customer with the email {email} already exists.") from exc


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
