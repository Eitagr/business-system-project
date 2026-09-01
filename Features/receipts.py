# Receipt rules. Renders a PDF file, which is not terminal I/O, so it stays
# here rather than in main.py.
#
# A receipt is a snapshot, not a pointer: the customer, appointment, and
# service price it was issued for can all change afterwards (a customer can
# be renamed or deactivated, config.yaml prices can be edited), but an
# issued receipt must keep reading back exactly as it was on the day it was
# printed. Every field the PDF needs is copied onto the receipt row at
# issue time instead of being looked up again later.

from datetime import date, datetime
from pathlib import Path

from fpdf import FPDF

from Features import customers
from Features.appointments import service_by_name

OUTPUT_DIR = Path(__file__).parent.parent / "receipts_out"


class ReceiptError(Exception):
    """A receipt could not be issued."""


def next_number(db, today=None) -> str:
    """Next receipt number for the current year, e.g. RCP-2026-013."""
    prefix = f"RCP-{(today or date.today()).year}-"
    last = db.last_receipt_number(prefix)
    # ponytail: sequence is derived from MAX(number), which relies on the
    # zero-padded suffix sorting lexicographically. That holds up to 999
    # receipts per year. Upgrade path: widen the padding or keep a counter row.
    sequence = int(last.removeprefix(prefix)) + 1 if last else 1
    return f"{prefix}{sequence:03d}"


def issue(db, config, appointment_id, amount=None, today=None) -> str:
    appointment = db.get_appointment(appointment_id)
    if appointment is None:
        raise ReceiptError(f"No appointment with id {appointment_id}.")
    if appointment["status"] == "cancelled":
        raise ReceiptError(f"Appointment #{appointment_id} was cancelled.")
    if db.get_receipt_by_appointment(appointment_id) is not None:
        raise ReceiptError(f"Appointment #{appointment_id} already has a receipt.")

    try:
        customer = customers.require(db, appointment["customer_id"], active_only=True)
    except customers.CustomerError as exc:
        raise ReceiptError(str(exc)) from exc

    service_name = appointment["service"] or appointment["title"]
    if amount is None:
        if not service_name:
            raise ReceiptError(
                f"Appointment #{appointment_id} has no service on record; "
                "specify an amount explicitly."
            )
        try:
            amount = service_by_name(config, service_name)["price"]
        except Exception as exc:  # BookingError: service not in config.yaml
            raise ReceiptError(
                f"'{service_name}' is not priced in config.yaml; specify an amount explicitly."
            ) from exc
    else:
        try:
            amount = float(amount)
        except (TypeError, ValueError) as exc:
            raise ReceiptError(f"'{amount}' is not an amount.") from exc
    if amount <= 0:
        raise ReceiptError("Amount must be greater than zero.")

    number = next_number(db, today)
    # service_minutes isn't on the appointment row; compute it from the
    # timestamps so it survives even if the service is later removed from
    # config.yaml.
    minutes = _minutes_between(appointment["starts_at"], appointment["ends_at"])
    receipt_id = db.add_receipt(
        customer["id"],
        appointment_id,
        number,
        round(amount, 2),
        customer["name"],
        customer["phone"],
        customer["email"],
        customer["address"],
        service_name,
        minutes,
        appointment["starts_at"],
    )

    # The row is written before the PDF is rendered, so a rendering failure
    # leaves a recoverable record rather than a consumed number with nothing
    # saved.
    receipt = db.get_receipt(receipt_id)
    pdf_path = render_pdf(receipt, config["business"])
    db.set_receipt_pdf_path(receipt_id, str(pdf_path))
    return number


def _minutes_between(starts_at, ends_at) -> int:
    if not (starts_at and ends_at):
        return None
    fmt = "%Y-%m-%d %H:%M:%S"
    delta = datetime.strptime(ends_at, fmt) - datetime.strptime(starts_at, fmt)
    return int(delta.total_seconds() // 60)


def render_pdf(receipt, business) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, business["name"], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for line in (business.get("address") or business.get("location"), business.get("phone")):
        if line:
            pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, f"Receipt {receipt['number']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Issued: {receipt['issued_at']}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Bill to", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for line in (
        receipt["customer_name"],
        receipt["customer_phone"],
        receipt["customer_email"],
        receipt["customer_address"],
    ):
        if line:
            pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Service", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    detail = receipt["service"] or "Appointment"
    if receipt["appointment_starts_at"]:
        detail += f"  ({receipt['appointment_starts_at']}"
        detail += f", {receipt['service_minutes']} min)" if receipt["service_minutes"] else ")"
    pdf.cell(0, 6, detail, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 13)
    currency = business.get("currency", "")
    pdf.cell(0, 8, f"Total: {receipt['amount']:.2f} {currency}", new_x="LMARGIN", new_y="NEXT")

    path = OUTPUT_DIR / f"{receipt['number']}.pdf"
    pdf.output(str(path))
    return path


def reprint(db, config, receipt_id) -> Path:
    """Re-render the PDF for an already-issued receipt from its stored
    snapshot, without touching the customer, appointment, or price again."""
    receipt = db.get_receipt(receipt_id)
    if receipt is None:
        raise ReceiptError(f"No receipt with id {receipt_id}.")
    path = render_pdf(receipt, config["business"])
    db.set_receipt_pdf_path(receipt_id, str(path))
    return path
