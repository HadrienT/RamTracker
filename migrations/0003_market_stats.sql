-- 0003_market_stats — l'indice glissant (WP04).
-- `sample_size` pilote le mode observation : échantillon trop maigre =>
-- barrière relative ignorée, barrière absolue seule.

CREATE TABLE market_stats (
  computed_at     TEXT    NOT NULL,
  capacity_bucket INTEGER NOT NULL,     -- 8 | 16 | 32 | 64
  p25             TEXT    NOT NULL,
  p50             TEXT    NOT NULL,
  p75             TEXT    NOT NULL,
  sample_size     INTEGER NOT NULL,
  window_days     INTEGER NOT NULL,
  PRIMARY KEY (computed_at, capacity_bucket)
);

CREATE INDEX idx_market_bucket ON market_stats(capacity_bucket, computed_at);
