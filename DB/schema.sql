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
    title         TEXT,
    starts_at     TEXT NOT NULL,     -- ISO datetime: 'YYYY-MM-DD HH:MM:SS'
    ends_at       TEXT,
    status        TEXT NOT NULL DEFAULT 'scheduled'  -- scheduled / done / cancelled
);


-- =============================================================================
-- RECEIPTS  ->  recipts.db
-- =============================================================================

CREATE TABLE IF NOT EXISTS receipts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id   INTEGER,           -- customers.id in customers.db (no FK)
    number        TEXT UNIQUE,       -- receipt / invoice number
    amount        REAL NOT NULL,
    issued_at     DATETIME DEFAULT (datetime('now'))
);