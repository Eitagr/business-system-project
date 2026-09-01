-- =============================================================================
-- CUSTOMERS  ->  customers.db
-- =============================================================================

CREATE TABLE IF NOT EXISTS customers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    phone         TEXT NOT NULL,
    email         TEXT UNIQUE,
    address       TEXT,
    age           INTEGER,
    active        INTEGER NOT NULL DEFAULT 1,  -- 1 = active, 0 = soft-deleted
    created_at    DATETIME DEFAULT (datetime('now'))
);

-- =============================================================================
-- LEADS  ->  leads.db
-- =============================================================================

CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id   INTEGER,           -- customers.id in customers.db (no FK)
    name          TEXT NOT NULL,
    phone         TEXT,
    email         TEXT,
    source        TEXT, 
    address       TEXT,             -- e.g. website / referral / walk-in
    status        TEXT NOT NULL DEFAULT 'new',  -- new / contacted / won / lost
    notes         TEXT,
    created_at    DATETIME DEFAULT (datetime('now'))
);

-- =============================================================================
-- APPOINTMENTS  ->  appointments.db
-- =============================================================================

CREATE TABLE IF NOT EXISTS appointments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id   INTEGER,           -- customers.id in customers.db (no FK)
    title         TEXT,              -- free text; superseded by `service` for new bookings
    service       TEXT,              -- must match a service name in config.yaml
    starts_at     TEXT NOT NULL,     -- ISO datetime: 'YYYY-MM-DD HH:MM:SS'
    ends_at       TEXT,
    status        TEXT NOT NULL DEFAULT 'scheduled'  -- scheduled / done / cancelled
);


-- =============================================================================
-- RECEIPTS  ->  receipts.db
-- =============================================================================
-- A receipt is a snapshot, not a pointer: the customer and appointment rows
-- it was issued for can change or be soft-deleted later, but the receipt
-- must keep reading back exactly as it was issued.

CREATE TABLE IF NOT EXISTS receipts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id            INTEGER,           -- customers.id in customers.db (no FK)
    appointment_id         INTEGER,           -- appointments.id in appointments.db (no FK)
    number                 TEXT UNIQUE,       -- receipt / invoice number
    amount                 REAL NOT NULL,
    customer_name          TEXT,
    customer_phone         TEXT,
    customer_email         TEXT,
    customer_address       TEXT,
    service                TEXT,
    service_minutes        INTEGER,
    appointment_starts_at  TEXT,
    pdf_path               TEXT,
    issued_at              DATETIME DEFAULT (datetime('now'))
);
