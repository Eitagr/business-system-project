# Every SQL statement in the project runs through this module.
#
# Each table lives in its own database file, so there are no foreign keys
# between them and no transaction can span two of them. Callers are
# responsible for keeping related rows consistent.

import re
import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).parent
SCHEMA_FILE = DB_DIR / "schema.sql"

DB_FILES = {
    "customers": "customers.db",
    "leads": "leads.db",
    "appointments": "appointments.db",
    "receipts": "receipts.db",
}


class Database:
    # `directory` is only overridden by the check script, which runs against
    # a throwaway copy of the schema.
    def __init__(self, directory: Path = DB_DIR) -> None:
        self.conns = {}
        for table, filename in DB_FILES.items():
            conn = sqlite3.connect(directory / filename)
            conn.row_factory = sqlite3.Row
            self.conns[table] = conn
        self._migrate()

    # sqlite3.connect() happily creates an empty file, so a missing database
    # would otherwise surface as "no such table" much later. Beyond
    # creating missing tables, this also adds any column schema.sql has
    # gained since a database file was first created, so existing rows are
    # never dropped to pick up a new column.
    def _migrate(self) -> None:
        schema = SCHEMA_FILE.read_text()
        scratch = sqlite3.connect(":memory:")
        scratch.row_factory = sqlite3.Row
        for match in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)[\s\S]*?\);", schema):
            table, create_sql = match.group(1), match.group(0)
            conn = self.conns[table]
            conn.execute(create_sql)

            # Let SQLite parse its own DDL for the expected columns rather
            # than hand-parsing the CREATE TABLE text.
            scratch.execute(f"DROP TABLE IF EXISTS {table}")
            scratch.execute(create_sql)
            expected = {row[1]: row for row in scratch.execute(f"PRAGMA table_info({table})")}
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

            for name, col in expected.items():
                if name in existing:
                    continue
                # ponytail: ADD COLUMN only accepts a constant default, so a
                # column whose schema.sql default calls datetime('now')
                # cannot be auto-migrated this way. None of the current
                # additions do; a future one that needs it must be a
                # hand-written migration instead.
                col_type, default = col["type"], col["dflt_value"]
                clause = f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"
                if default is not None:
                    clause += f" DEFAULT {default}"
                conn.execute(clause)
            conn.commit()
        scratch.close()

    def close(self) -> None:
        for conn in self.conns.values():
            conn.close()

    def _write(self, table: str, sql: str, params: tuple) -> sqlite3.Cursor:
        conn = self.conns[table]
        with conn:
            return conn.execute(sql, params)

    def _rows(self, table: str, sql: str, params: tuple = ()) -> list:
        return self.conns[table].execute(sql, params).fetchall()

    def _one(self, table: str, sql: str, params: tuple):
        rows = self._rows(table, sql, params)
        return rows[0] if rows else None

    # --- customers ----------------------------------------------------------

    def add_customer(self, name, phone, email, address, age) -> int:
        return self._write(
            "customers",
            "INSERT INTO customers (name, phone, email, address, age) VALUES (?, ?, ?, ?, ?)",
            (name, phone, email, address, age),
        ).lastrowid

    def get_customer(self, customer_id):
        """Returns the customer regardless of active state, so historical
        appointments and receipts can still resolve a name."""
        return self._one("customers", "SELECT * FROM customers WHERE id = ?", (customer_id,))

    def list_customers(self, active=True) -> list:
        if active is True:
            where = "WHERE active = 1 "
        elif active is False:
            where = "WHERE active = 0 "
        else:
            where = ""
        return self._rows("customers", f"SELECT * FROM customers {where}ORDER BY name")

    def find_customers(self, term) -> list:
        like = f"%{term}%"
        return self._rows(
            "customers",
            "SELECT * FROM customers WHERE active = 1 AND (name LIKE ? OR phone LIKE ?) "
            "ORDER BY name",
            (like, like),
        )

    def update_customer(self, customer_id, name, phone, email, address, age) -> bool:
        return self._write(
            "customers",
            "UPDATE customers SET name = ?, phone = ?, email = ?, address = ?, age = ? "
            "WHERE id = ?",
            (name, phone, email, address, age, customer_id),
        ).rowcount > 0

    def set_customer_active(self, customer_id, active: bool) -> bool:
        return self._write(
            "customers",
            "UPDATE customers SET active = ? WHERE id = ?",
            (1 if active else 0, customer_id),
        ).rowcount > 0

    # --- appointments -------------------------------------------------------

    def add_appointment(self, customer_id, service, starts_at, ends_at) -> int:
        return self._write(
            "appointments",
            "INSERT INTO appointments (customer_id, service, starts_at, ends_at) "
            "VALUES (?, ?, ?, ?)",
            (customer_id, service, starts_at, ends_at),
        ).lastrowid

    def get_appointment(self, appointment_id):
        return self._one(
            "appointments", "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
        )

    # Timestamps are fixed-width ISO text, so string order is chronological
    # order and no date functions are needed. Only `scheduled` rows block a
    # slot; a cancelled appointment frees its time.
    def overlapping_appointments(self, starts_at, ends_at) -> list:
        return self._rows(
            "appointments",
            "SELECT * FROM appointments "
            "WHERE status = 'scheduled' AND starts_at < ? AND ends_at > ? "
            "ORDER BY starts_at",
            (ends_at, starts_at),
        )

    def appointments_on(self, day) -> list:
        return self._rows(
            "appointments",
            "SELECT * FROM appointments WHERE starts_at LIKE ? ORDER BY starts_at",
            (f"{day}%",),
        )

    def list_appointments(self) -> list:
        return self._rows("appointments", "SELECT * FROM appointments ORDER BY starts_at")

    def customer_appointments(self, customer_id) -> list:
        return self._rows(
            "appointments",
            "SELECT * FROM appointments WHERE customer_id = ? ORDER BY starts_at",
            (customer_id,),
        )

    def set_appointment_status(self, appointment_id, status) -> bool:
        return self._write(
            "appointments",
            "UPDATE appointments SET status = ? WHERE id = ?",
            (status, appointment_id),
        ).rowcount > 0

    # --- leads --------------------------------------------------------------

    def add_lead(self, name, phone, email, source, address, notes) -> int:
        return self._write(
            "leads",
            "INSERT INTO leads (name, phone, email, source, address, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, phone, email, source, address, notes),
        ).lastrowid

    def get_lead(self, lead_id):
        return self._one("leads", "SELECT * FROM leads WHERE id = ?", (lead_id,))

    def list_leads(self) -> list:
        return self._rows("leads", "SELECT * FROM leads ORDER BY created_at DESC")

    def set_lead_status(self, lead_id, status) -> bool:
        return self._write(
            "leads", "UPDATE leads SET status = ? WHERE id = ?", (status, lead_id)
        ).rowcount > 0

    def mark_lead_won(self, lead_id, customer_id) -> bool:
        return self._write(
            "leads",
            "UPDATE leads SET status = 'won', customer_id = ? WHERE id = ?",
            (customer_id, lead_id),
        ).rowcount > 0

    # --- receipts -----------------------------------------------------------

    def add_receipt(
        self,
        customer_id,
        appointment_id,
        number,
        amount,
        customer_name,
        customer_phone,
        customer_email,
        customer_address,
        service,
        service_minutes,
        appointment_starts_at,
    ) -> int:
        return self._write(
            "receipts",
            "INSERT INTO receipts ("
            "customer_id, appointment_id, number, amount, customer_name, customer_phone, "
            "customer_email, customer_address, service, service_minutes, appointment_starts_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                customer_id,
                appointment_id,
                number,
                amount,
                customer_name,
                customer_phone,
                customer_email,
                customer_address,
                service,
                service_minutes,
                appointment_starts_at,
            ),
        ).lastrowid

    def get_receipt(self, receipt_id):
        return self._one("receipts", "SELECT * FROM receipts WHERE id = ?", (receipt_id,))

    def get_receipt_by_appointment(self, appointment_id):
        return self._one(
            "receipts", "SELECT * FROM receipts WHERE appointment_id = ?", (appointment_id,)
        )

    def list_receipts(self) -> list:
        return self._rows("receipts", "SELECT * FROM receipts ORDER BY issued_at DESC")

    def last_receipt_number(self, prefix):
        row = self._one(
            "receipts",
            "SELECT MAX(number) AS number FROM receipts WHERE number LIKE ?",
            (f"{prefix}%",),
        )
        return row["number"] if row else None

    def set_receipt_pdf_path(self, receipt_id, pdf_path) -> bool:
        return self._write(
            "receipts",
            "UPDATE receipts SET pdf_path = ? WHERE id = ?",
            (pdf_path, receipt_id),
        ).rowcount > 0
