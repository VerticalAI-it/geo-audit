CREATE TABLE IF NOT EXISTS offers (
  id            SERIAL PRIMARY KEY,
  code          VARCHAR(50) UNIQUE NOT NULL,
  description   TEXT NOT NULL,
  amount        DECIMAL(10, 2) NOT NULL,
  currency      VARCHAR(3) NOT NULL DEFAULT 'EUR',
  billing_cycle VARCHAR(30) NOT NULL CHECK (billing_cycle IN ('one_time', 'recurring_monthly')),
  is_active     BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
  id                     SERIAL PRIMARY KEY,
  offer_id               INTEGER REFERENCES offers(id),
  stripe_session_id      VARCHAR(255) UNIQUE NOT NULL,
  stripe_subscription_id VARCHAR(255),
  customer_email         VARCHAR(255),
  status                 VARCHAR(50) NOT NULL DEFAULT 'pending',
  amount_paid            DECIMAL(10, 2),
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_offers_code       ON offers (UPPER(code));
CREATE INDEX IF NOT EXISTS idx_orders_session_id ON orders (stripe_session_id);
CREATE INDEX IF NOT EXISTS idx_orders_sub_id     ON orders (stripe_subscription_id);
