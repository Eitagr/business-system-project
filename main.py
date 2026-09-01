# Command line interface. This is the only file that prints or reads input,
# which is what lets the same Features modules back a web UI later.

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import PromptSession, choice
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from DB.db_adapter import Database
from Features import appointments, customers, leads, receipts

CONFIG_FILE = Path(__file__).parent / "config.yaml"
console = Console()
INTERACTIVE = sys.stdin.isatty() and sys.stdout.isatty()
SESSION = PromptSession() if INTERACTIVE else None
HEADER = None

STATUS_STYLE = {
    "scheduled": "cyan",
    "done": "green",
    "cancelled": "dim red",
    "new": "cyan",
    "contacted": "yellow",
    "won": "green",
    "lost": "dim red",
}


class Cancelled(Exception):
    """The user pressed enter on a required prompt to back out."""


RULE_ERRORS = (
    appointments.BookingError,
    customers.CustomerError,
    leads.LeadError,
    receipts.ReceiptError,
    Cancelled,
)


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise SystemExit(f"Missing {CONFIG_FILE.name}. Copy the sample and fill it in.")
    config = yaml.safe_load(CONFIG_FILE.read_text()) or {}
    missing = {"business", "hours", "services"} - config.keys()
    if missing:
        raise SystemExit(f"{CONFIG_FILE.name} is missing: {', '.join(sorted(missing))}.")
    if not config["services"]:
        raise SystemExit(f"{CONFIG_FILE.name} lists no services.")
    return config


# --- prompting --------------------------------------------------------------


def fresh(notice=None) -> None:
    """Wipe the terminal so only this step is on screen."""
    if INTERACTIVE:
        console.clear()
        if HEADER is not None:
            console.print(HEADER)
    if notice:
        console.print(notice)


def pause() -> None:
    """Wait without clearing, so the current table or message stays visible."""
    if not INTERACTIVE:
        return
    try:
        SESSION.prompt("Enter to continue: ")
    except EOFError:
        pass


def ask(prompt, required=False, notice=None) -> str:
    fresh(notice)
    try:
        value = (
            SESSION.prompt(f"{prompt}: ").strip()
            if INTERACTIVE
            else input(f"{prompt}: ").strip()
        )
    except EOFError:
        raise Cancelled() from None
    if required and not value:
        raise Cancelled()
    return value


def ask_valid(prompt, parse, required=False, notice=None):
    while True:
        value = ask(prompt, required, notice=notice)
        if not value:
            return None
        try:
            return parse(value)
        except ValueError as error:
            notice = f"[dim]{error} Try again, or leave blank to cancel.[/dim]"


def _as_int(value) -> int:
    if not value.lstrip("-").isdigit():
        raise ValueError(f"'{value}' is not a whole number.")
    return int(value)


def _as_age(value) -> int:
    age = _as_int(value)
    if not 0 < age < 130:
        raise ValueError("Age must be between 1 and 129.")
    return age


def _as_amount(value) -> float:
    try:
        amount = float(value)
    except ValueError:
        raise ValueError(f"'{value}' is not an amount.") from None
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    return amount


def _as_date(value) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"'{value}' is not a date like 2026-09-01.") from None
    return value


def _as_email(value) -> str:
    if not customers.EMAIL.match(value):
        raise ValueError(f"'{value}' is not a valid email address.")
    return value


def ask_int(prompt, required=False, notice=None):
    return ask_valid(prompt, _as_int, required, notice=notice)


def ask_age(prompt, required=False, notice=None):
    return ask_valid(prompt, _as_age, required, notice=notice)


def ask_amount(prompt, required=False, notice=None):
    return ask_valid(prompt, _as_amount, required, notice=notice)


def ask_date(prompt, required=False, notice=None):
    return ask_valid(prompt, _as_date, required, notice=notice)


def ask_email(prompt, required=False, notice=None):
    return ask_valid(prompt, _as_email, required, notice=notice)


def choose(title, labels, exit_label, notice=None):
    """Return the chosen index, or None for the back/quit option."""
    if not labels:
        fresh(notice or "[dim]  none[/dim]")
        pause()
        return None
    if INTERACTIVE:
        return _choose_keys(title, labels, exit_label, notice)
    return _choose_numbered(title, labels, exit_label, notice)


def _choose_numbered(title, labels, exit_label, notice=None):
    while True:
        fresh(notice)
        console.print(f"\n[bold]{title}[/bold]")
        for number, text in enumerate(labels, start=1):
            console.print(f"  {number:>2}. {text}")
        console.print(f"   0. {exit_label}")
        choice_text = input("\nChoice: ").strip()
        if choice_text == "0":
            return None
        if choice_text.isdigit() and 1 <= int(choice_text) <= len(labels):
            return int(choice_text) - 1
        notice = "[dim]Pick a number from the menu.[/dim]"


def _choose_keys(title, labels, exit_label, notice=None):
    bindings = KeyBindings()

    @bindings.add("escape")
    @bindings.add("q")
    def _back(event):
        event.app.exit(result=None)

    options = [(index, label) for index, label in enumerate(labels)]
    options.append((None, exit_label))
    try:
        fresh(notice)
        return choice(
            message=title,
            options=options,
            key_bindings=bindings,
            bottom_toolbar="Up/Down  Enter  Esc back",
        )
    except KeyboardInterrupt:
        raise Cancelled() from None


def ask_choice(prompt, options, required=False):
    index = choose(prompt, list(options), "Cancel")
    if index is None:
        if required:
            raise Cancelled()
        return None
    return list(options)[index]


def pick_row(title, rows, format_row):
    if not rows:
        fresh("[dim]  none[/dim]")
        pause()
        raise Cancelled()
    index = choose(title, [format_row(row) for row in rows], "Cancel")
    if index is None:
        raise Cancelled()
    return rows[index]


def ask_customer_id(db, active_only=False):
    rows = db.list_customers(active=True if active_only else None)
    row = pick_row(
        "Customer",
        rows,
        lambda r: f"#{r['id']}  {r['name']}  {r['phone']}"
        + ("" if r["active"] else "  [inactive]"),
    )
    if active_only:
        customers.require(db, row["id"], active_only=True)
    return row["id"]


def ask_appointment_id(db):
    row = pick_row(
        "Appointment",
        db.list_appointments(),
        lambda r: (
            f"#{r['id']}  {r['starts_at']}  {label(r)}  "
            f"{customer_name(db, r['customer_id'])}  {r['status']}"
        ),
    )
    return row["id"]


def ask_lead_id(db):
    row = pick_row(
        "Lead",
        db.list_leads(),
        lambda r: f"#{r['id']}  {r['name']}  {r['phone'] or ''}  {r['status']}",
    )
    return row["id"]


def ask_receipt_id(db):
    row = pick_row(
        "Receipt",
        db.list_receipts(),
        lambda r: f"{r['number']}  {r['amount']:.2f}  {r['customer_name'] or customer_name(db, r['customer_id'])}",
    )
    return row["id"]


# --- display ----------------------------------------------------------------


def label(row) -> str:
    return row["service"] or row["title"] or "Appointment"


def customer_name(db, customer_id) -> str:
    customer = db.get_customer(customer_id)
    return customer["name"] if customer else f"unknown customer {customer_id}"


def styled_status(status) -> str:
    return f"[{STATUS_STYLE.get(status, 'white')}]{status}[/]"


def show_table(headers, rows, notice=None) -> None:
    fresh(notice)
    if not rows:
        console.print("[dim]  none[/dim]")
        pause()
        return
    table = Table(show_header=True, header_style="bold")
    for header in headers:
        table.add_column(header)
    for row in rows:
        table.add_row(*row)
    console.print(table)
    pause()


def show_appointments(db, rows, notice=None) -> None:
    show_table(
        ["Id", "Start", "End", "Service", "Customer", "Status"],
        [
            [
                str(row["id"]),
                row["starts_at"],
                (row["ends_at"] or "")[11:16],
                label(row),
                customer_name(db, row["customer_id"]),
                styled_status(row["status"]),
            ]
            for row in rows
        ],
        notice=notice,
    )


def ok(message) -> None:
    fresh(f"[green]{message}[/green]")
    pause()


def fail(message) -> None:
    fresh(f"[red]{message}[/red]")
    pause()


# --- customer commands ------------------------------------------------------


def add_customer(db, config) -> None:
    customer_id = customers.add(
        db,
        ask("Name", required=True),
        ask("Phone", required=True),
        ask_email("Email (optional)"),
        ask("Address (optional)"),
        ask_age("Age (optional)"),
    )
    ok(f"Added customer #{customer_id}.")


def list_customers(db, config) -> None:
    rows = customers.find(db, ask("Search name or phone (blank for all)"))
    show_table(
        ["Id", "Name", "Phone", "Email"],
        [[str(row["id"]), row["name"], row["phone"], row["email"] or ""] for row in rows],
    )


def edit_customer(db, config) -> None:
    customer_id = ask_customer_id(db)
    current = db.get_customer(customer_id)
    hint = f"Editing {current['name']} - leave a field blank to keep it as is."
    name = ask("Name", notice=hint) or current["name"]
    phone = ask("Phone", notice=hint) or current["phone"]
    email = ask_email("Email", notice=hint)
    if email is None:
        email = current["email"]
    address = ask("Address", notice=hint) or current["address"]
    age = ask_age("Age", notice=hint)
    if age is None:
        age = current["age"]
    customers.update(db, customer_id, name, phone, email, address, age)
    ok(f"Updated customer #{customer_id}.")


def deactivate_customer(db, config) -> None:
    customer_id = ask_customer_id(db, active_only=True)
    customers.deactivate(db, customer_id)
    ok(f"Customer #{customer_id} deactivated.")


def reactivate_customer(db, config) -> None:
    row = pick_row(
        "Inactive customer",
        db.list_customers(active=False),
        lambda r: f"#{r['id']}  {r['name']}  {r['phone']}",
    )
    customers.reactivate(db, row["id"])
    ok(f"Customer #{row['id']} reactivated.")


# --- appointment commands ---------------------------------------------------


def book_appointment(db, config) -> None:
    names = [service["name"] for service in config["services"]]
    customer_id = ask_customer_id(db, active_only=True)
    service_name = ask_choice("Service", names, required=True)
    service = appointments.service_by_name(config, service_name)
    duration = timedelta(minutes=service["minutes"])

    date_notice = None
    while True:
        day = ask_date(
            f"Date (YYYY-MM-DD, today is {date.today().isoformat()})",
            required=True,
            notice=date_notice,
        )
        slot_notice = None
        while True:
            slots = appointments.open_slots(db, config, day, service_name)
            if not slots:
                date_notice = "[dim]No free times that day. Pick another date.[/dim]"
                break
            labels = [f"{start:%H:%M} – {(start + duration):%H:%M}" for start in slots]
            index = choose(f"Free times on {day}", labels, "Other date", notice=slot_notice)
            if index is None:
                date_notice = None
                break
            try:
                appointment_id = appointments.book(
                    db, config, customer_id, service_name, slots[index]
                )
                ok(f"Booked appointment #{appointment_id}.")
                return
            except appointments.BookingError as error:
                slot_notice = f"[red]{error}[/red]"


def day_schedule(db, config) -> None:
    day = ask_date("Date (YYYY-MM-DD, blank for today)") or date.today().isoformat()
    show_appointments(db, appointments.on_day(db, day), notice=f"[bold]{day}[/bold]")


def all_appointments(db, config) -> None:
    show_appointments(db, db.list_appointments())


def change_appointment_status(db, config) -> None:
    appointment_id = ask_appointment_id(db)
    status = ask_choice("New status", list(appointments.STATUSES), required=True)
    appointments.set_status(db, appointment_id, status)
    ok(f"Appointment #{appointment_id} is now {status}.")


# --- lead commands ----------------------------------------------------------


def add_lead(db, config) -> None:
    lead_id = leads.add(
        db,
        ask("Name", required=True),
        ask("Phone"),
        ask_email("Email"),
        ask("Source (website / referral / walk-in)"),
        ask("Address"),
        ask("Notes"),
    )
    ok(f"Added lead #{lead_id}.")


def list_leads(db, config) -> None:
    show_table(
        ["Id", "Name", "Phone", "Source", "Status"],
        [
            [
                str(row["id"]),
                row["name"],
                row["phone"] or "",
                row["source"] or "",
                styled_status(row["status"]),
            ]
            for row in db.list_leads()
        ],
    )


def convert_lead(db, config) -> None:
    lead_id = ask_lead_id(db)
    customer_id = leads.convert(db, lead_id)
    ok(f"Lead #{lead_id} converted to customer #{customer_id}.")


# --- receipt commands -------------------------------------------------------


def issue_receipt(db, config) -> None:
    appointment_id = ask_appointment_id(db)
    amount = ask_amount("Amount (blank to use the service price from config.yaml)")
    number = receipts.issue(db, config, appointment_id, amount)
    receipt = db.get_receipt_by_appointment(appointment_id)
    ok(f"Issued receipt {number} -> {receipt['pdf_path']}")


def list_receipts(db, config) -> None:
    currency = config["business"].get("currency", "")
    show_table(
        ["Id", "Number", "Amount", "Customer", "Issued"],
        [
            [
                str(row["id"]),
                row["number"],
                f"{row['amount']:.2f} {currency}",
                row["customer_name"] or customer_name(db, row["customer_id"]),
                str(row["issued_at"]),
            ]
            for row in db.list_receipts()
        ],
    )


def reprint_receipt(db, config) -> None:
    receipt_id = ask_receipt_id(db)
    path = receipts.reprint(db, config, receipt_id)
    ok(f"Re-printed to {path}")


# --- menus ------------------------------------------------------------------

SECTIONS = [
    (
        "Customers",
        [
            ("Add customer", add_customer),
            ("List / search customers", list_customers),
            ("Edit customer", edit_customer),
            ("Deactivate customer", deactivate_customer),
            ("Reactivate customer", reactivate_customer),
        ],
    ),
    (
        "Appointments",
        [
            ("Book appointment", book_appointment),
            ("Day schedule", day_schedule),
            ("All appointments", all_appointments),
            ("Change appointment status", change_appointment_status),
        ],
    ),
    (
        "Leads",
        [
            ("Add lead", add_lead),
            ("List leads", list_leads),
            ("Convert lead to customer", convert_lead),
        ],
    ),
    (
        "Receipts",
        [
            ("Issue receipt", issue_receipt),
            ("List receipts", list_receipts),
            ("Re-print receipt PDF", reprint_receipt),
        ],
    ),
]


def run_section(db, config, title, commands) -> None:
    while True:
        index = choose(title, [text for text, _ in commands], "Back")
        if index is None:
            return
        try:
            commands[index][1](db, config)
        except RULE_ERRORS as error:
            fail(str(error) or "Cancelled.")


def main() -> None:
    global HEADER
    config = load_config()
    db = Database()
    HEADER = Panel(config["business"]["name"], subtitle="appointment management")
    try:
        while True:
            index = choose("Main menu", [title for title, _ in SECTIONS], "Quit")
            if index is None:
                return
            run_section(db, config, *SECTIONS[index])
    except (KeyboardInterrupt, EOFError, Cancelled):
        console.print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
