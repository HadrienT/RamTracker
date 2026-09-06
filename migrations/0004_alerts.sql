-- 0004_alerts — ce qui est réellement parti (WP05). `outcome` est alimenté par WP09.

CREATE TABLE alerts (
  id           INTEGER PRIMARY KEY,
  fingerprint  TEXT NOT NULL,
  source       TEXT NOT NULL,
  external_id  TEXT NOT NULL,
  eur_per_gb   TEXT NOT NULL,
  discount     REAL NOT NULL,
  urgency      TEXT NOT NULL,
  price        TEXT NOT NULL,          -- prix total au moment de l'alerte (re-alerte à la baisse)
  sent_at      TEXT NOT NULL,
  outcome      TEXT,                   -- NULL | 'ignored' | 'bought'
  muted_until  TEXT,                   -- cooldown "Ignorer 24 h" (WP09)
  FOREIGN KEY (source, external_id) REFERENCES listings(source, external_id)
);

CREATE INDEX idx_alerts_fp   ON alerts(fingerprint, sent_at);
CREATE INDEX idx_alerts_sent ON alerts(sent_at);
