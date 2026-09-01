# Lead rules. No SQL, no printing.

from Features import customers

STATUSES = ("new", "contacted", "won", "lost")


class LeadError(Exception):
    """A lead could not be created, updated or converted."""


def add(db, name, phone=None, email=None, source=None, address=None, notes=None) -> int:
    name = (name or "").strip()
    if not name:
        raise LeadError("Name is required.")
    return db.add_lead(
        name,
        (phone or "").strip() or None,
        (email or "").strip() or None,
        (source or "").strip() or None,
        (address or "").strip() or None,
        (notes or "").strip() or None,
    )


def set_status(db, lead_id, status) -> None:
    if status not in STATUSES:
        raise LeadError(f"Status must be one of: {', '.join(STATUSES)}.")
    if status == "won":
        raise LeadError("Use convert() so the lead is linked to a customer.")
    if not db.set_lead_status(lead_id, status):
        raise LeadError(f"No lead with id {lead_id}.")


def convert(db, lead_id) -> int:
    """Create a customer from a lead and mark the lead won."""
    lead = db.get_lead(lead_id)
    if lead is None:
        raise LeadError(f"No lead with id {lead_id}.")
    if lead["status"] == "won":
        raise LeadError(
            f"Lead {lead_id} was already converted to customer {lead['customer_id']}."
        )
    if not lead["phone"]:
        raise LeadError(f"Lead {lead_id} has no phone number, which a customer requires.")

    # ponytail: leads and customers are separate database files, so these two
    # writes cannot share a transaction. The customer is created first on
    # purpose: a crash between them leaves an unlinked customer, which is
    # visible and harmless, rather than a lead marked won pointing at a
    # customer that does not exist. Upgrade path: move both tables into one
    # database file and wrap this in a single transaction.
    try:
        customer_id = customers.add(
            db, lead["name"], lead["phone"], lead["email"], lead["address"]
        )
    except customers.CustomerError as exc:
        raise LeadError(str(exc)) from exc
    db.mark_lead_won(lead_id, customer_id)
    return customer_id
