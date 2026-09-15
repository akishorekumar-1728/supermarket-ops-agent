-- ============================================================
--  database/schema.sql  –  Supermarket Ops Agent  (SQLite)
-- ============================================================
-- Foreign-key enforcement is enabled at connection time via
--   PRAGMA foreign_keys = ON;
-- WAL mode is enabled at connection time via
--   PRAGMA journal_mode = WAL;
-- ============================================================

-- ----------------------------------------------------------------
-- 1. products
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sku           TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    unit          TEXT    NOT NULL,                     -- e.g. kg, pcs, litre
    cost_price    REAL    NOT NULL CHECK (cost_price >= 0),
    selling_price REAL    NOT NULL CHECK (selling_price >= 0),
    mrp           REAL    NOT NULL CHECK (mrp >= 0),
    gst_rate      REAL    NOT NULL DEFAULT 0 CHECK (gst_rate >= 0 AND gst_rate <= 100),
    hsn_code      TEXT    NOT NULL DEFAULT '',
    reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ----------------------------------------------------------------
-- 2. stock  (one row per product; quantity is floating for loose items)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock (
    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    quantity   REAL    NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    updated_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ----------------------------------------------------------------
-- 3. bills
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bills (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number    TEXT    NOT NULL UNIQUE,
    status            TEXT    NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft', 'finalized', 'void')),
    payment_mode      TEXT             DEFAULT NULL,   -- cash / upi / card / credit
    payment_reference TEXT             DEFAULT NULL,
    subtotal          REAL    NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    cgst_total        REAL    NOT NULL DEFAULT 0 CHECK (cgst_total >= 0),
    sgst_total        REAL    NOT NULL DEFAULT 0 CHECK (sgst_total >= 0),
    gst_total         REAL    NOT NULL DEFAULT 0 CHECK (gst_total >= 0),
    grand_total       REAL    NOT NULL DEFAULT 0 CHECK (grand_total >= 0),
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    finalized_at      TEXT             DEFAULT NULL,
    idempotency_key   TEXT    NOT NULL UNIQUE
);

-- ----------------------------------------------------------------
-- 4. bill_items
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bill_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id        INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    product_id     INTEGER NOT NULL REFERENCES products(id),
    quantity       REAL    NOT NULL CHECK (quantity > 0),
    unit_price     REAL    NOT NULL CHECK (unit_price >= 0),
    cost_price     REAL    NOT NULL CHECK (cost_price >= 0),
    taxable_amount REAL    NOT NULL CHECK (taxable_amount >= 0),
    gst_rate       REAL    NOT NULL DEFAULT 0,
    hsn_code       TEXT    NOT NULL DEFAULT '',
    cgst_amount    REAL    NOT NULL DEFAULT 0,
    sgst_amount    REAL    NOT NULL DEFAULT 0,
    total          REAL    NOT NULL CHECK (total >= 0)
);

CREATE INDEX IF NOT EXISTS idx_bill_items_bill_id    ON bill_items(bill_id);
CREATE INDEX IF NOT EXISTS idx_bill_items_product_id ON bill_items(product_id);

-- ----------------------------------------------------------------
-- 5. khata_customers  (credit-book customers)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS khata_customers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ----------------------------------------------------------------
-- 6. khata_transactions
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS khata_transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES khata_customers(id) ON DELETE CASCADE,
    type        TEXT    NOT NULL CHECK (type IN ('credit', 'payment')),
    amount      REAL    NOT NULL CHECK (amount > 0),
    reference   TEXT             DEFAULT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_khata_txn_customer ON khata_transactions(customer_id);

-- ----------------------------------------------------------------
-- 7. preferences  (key-value store for app settings)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS preferences (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
