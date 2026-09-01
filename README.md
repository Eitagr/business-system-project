# Appointment management system

A small-business CLI for customers, appointments, leads, and receipts,
personalized entirely through `config.yaml` (no code changes needed to run
it for a different business).

## Setup

```
pip install -r requirements.txt
python3 main.py
```

Edit `config.yaml` first: business name/contact, weekly opening hours, and
the list of services (each with a duration and a price).

On a real terminal, menus are arrow-key lists (Up/Down, Enter, Esc). Piped
input still uses numbered menus.

## Structure

```
main.py            - CLI: the only file that prints or reads input
Features/          - business rules; no SQL, no print(), no input()
DB/db_adapter.py   - every SQL statement in the project
DB/schema.sql      - table definitions (source of truth for the adapter)
config.yaml        - business identity, hours, services
receipts_out/      - generated receipt PDFs (not committed)
```

Each of `customers`, `leads`, `appointments`, `receipts` lives in its own  
SQLite file under `DB/`. There are no foreign keys between them; the  
`Features` modules check cross-references (e.g. that a customer exists)  
in Python instead.

## Known limits

- Booking is check-then-insert, not atomic — fine for one user, needs a
transaction if this becomes multi-user.
- Lead-to-customer conversion writes to two separate database files and
cannot be a single transaction; see the comment in `Features/leads.py`.
- Receipt PDFs use core Helvetica, which is Latin-1 only — a Hebrew
customer name will not render correctly.
- `DB/*.db` files are currently tracked in git. Once real customer data is
in them, consider `git rm --cached` on those files so personal data
stops going into git history.

