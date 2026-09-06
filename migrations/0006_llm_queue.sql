-- 0006_llm_queue — les deux voies d'appel au LLM (WP07).

CREATE TABLE llm_queue (
  spec_hash    TEXT PRIMARY KEY REFERENCES spec_cache(spec_hash),
  lane         TEXT    NOT NULL,       -- 'urgent' | 'deferred'
  best_case    TEXT,                   -- €/Go du meilleur cas, sert au tri
  attempts     INTEGER NOT NULL DEFAULT 0,
  enqueued_at  TEXT    NOT NULL,
  last_try_at  TEXT
);

CREATE INDEX idx_queue_lane ON llm_queue(lane, best_case);
