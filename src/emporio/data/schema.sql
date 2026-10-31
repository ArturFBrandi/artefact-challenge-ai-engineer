CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    search_text TEXT NOT NULL
);

CREATE TABLE products (
    product_id     INTEGER PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    category_id    INTEGER NOT NULL REFERENCES categories (category_id),
    price_cents    INTEGER NOT NULL CHECK (price_cents > 0),
    description    TEXT NOT NULL,
    stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0),
    status         TEXT NOT NULL CHECK (status IN ('active', 'discontinued', 'coming_soon')),
    specs          TEXT NOT NULL,
    strings_type   TEXT,
    electronics    INTEGER,
    search_name    TEXT NOT NULL,
    search_text    TEXT NOT NULL
);
CREATE INDEX idx_products_category ON products (category_id);

CREATE TABLE customers (
    customer_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    phone_digits TEXT NOT NULL UNIQUE,
    email        TEXT NOT NULL,
    city         TEXT NOT NULL
);
CREATE INDEX idx_customers_email ON customers (email);

CREATE TABLE orders (
    order_id           INTEGER PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers (customer_id),
    order_date         TEXT NOT NULL,
    status             TEXT NOT NULL
        CHECK (status IN ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')),
    total_cents        INTEGER NOT NULL CHECK (total_cents > 0),
    payment_method     TEXT NOT NULL,
    tracking_code      TEXT,
    estimated_delivery TEXT,
    notes              TEXT
);
CREATE INDEX idx_orders_customer ON orders (customer_id);

CREATE TABLE order_items (
    order_id   INTEGER NOT NULL REFERENCES orders (order_id),
    product_id INTEGER NOT NULL REFERENCES products (product_id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (order_id, product_id)
);

CREATE TABLE promotions (
    promotion_id     INTEGER PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products (product_id),
    discount_percent INTEGER NOT NULL CHECK (discount_percent BETWEEN 1 AND 99),
    description      TEXT NOT NULL,
    is_active        INTEGER NOT NULL CHECK (is_active IN (0, 1))
);
CREATE INDEX idx_promotions_product ON promotions (product_id, is_active);

CREATE TABLE policy_sections (
    section_id TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL
);

CREATE TABLE sessions (
    session_id           TEXT PRIMARY KEY,
    created_at           TEXT NOT NULL,
    last_seen_at         TEXT NOT NULL,
    verified_customer_id INTEGER REFERENCES customers (customer_id),
    verified_at          TEXT,
    failed_verifications INTEGER NOT NULL DEFAULT 0,
    evidence             TEXT NOT NULL DEFAULT ''
);

CREATE TABLE turns (
    session_id TEXT NOT NULL REFERENCES sessions (session_id),
    turn       INTEGER NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, turn, role)
);

CREATE TABLE handoffs (
    protocol   TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (session_id),
    kind       TEXT NOT NULL,
    summary    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, kind)
);
