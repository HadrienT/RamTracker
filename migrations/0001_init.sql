-- 0001_init — listings.
-- La table `schema_migrations` est gérée par core.db (créée avant la première
-- migration). Les PRAGMA de connexion (WAL, foreign_keys, busy_timeout) sont
-- posés par core.db à chaque ouverture : un PRAGMA dans une migration ne
-- survit pas à la reconnexion.

CREATE TABLE listings (
  source       TEXT    NOT NULL,
  external_id  TEXT    NOT NULL,
  spec_hash    TEXT    NOT NULL,
  url          TEXT    NOT NULL,
  title        TEXT    NOT NULL,
  description  TEXT,
  price        TEXT    NOT NULL,      -- Decimal sérialisé, JAMAIS de REAL
  currency     TEXT    NOT NULL,
  shipping     TEXT,                  -- NULL = inconnu ; '0' = gratuit
  sale_type    TEXT    NOT NULL,
  current_bid  TEXT,
  ends_at      TEXT,                  -- ISO 8601 UTC
  seller_id    TEXT,
  country      TEXT    NOT NULL,
  posted_at    TEXT    NOT NULL,
  first_seen   TEXT    NOT NULL,
  last_seen    TEXT    NOT NULL,
  raw_payload  BLOB    NOT NULL,      -- charge utile d'origine, compressée
  PRIMARY KEY (source, external_id)
);

CREATE INDEX idx_listings_spec    ON listings(spec_hash);
CREATE INDEX idx_listings_seen    ON listings(last_seen);
CREATE INDEX idx_listings_auction ON listings(ends_at) WHERE sale_type = 'auction';
