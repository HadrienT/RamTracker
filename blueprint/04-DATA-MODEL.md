# 04 — Modèle de données

> Prérequis : [00-PRIMER.md](00-PRIMER.md) · [03-INTERFACES.md](03-INTERFACES.md)

**SQLite, mode WAL, un fichier.** Migrations en SQL brut versionné, appliquées dans
l'ordre, **forward-only**, idempotentes, table `schema_migrations`.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

---

## 1. Les trois identités

Le point le plus important de ce document. Il faut **trois** clés distinctes, et
celle qui économise le plus de travail n'est pas celle de l'annonce.

| Identité | Clé | Question posée | Étage |
|---|---|---|---|
| `external_id` | `(source, external_id)` | L'ai-je déjà vue ? | Collecte, avant tout le reste |
| `spec_hash` | `sha256(titre + description normalisés)` | Ai-je déjà **compris ce texte** ? | Cache d'extraction |
| `fingerprint` | `(vendeur, capacité, quantité, tranche de prix)` | Ai-je déjà **alerté** là-dessus ? | Notification |

L'identifiant d'annonce seul ne suffit pas : sur Leboncoin, les vendeurs suppriment
et republient pour remonter dans le fil, ce qui produit un nouveau `list_id` avec un
texte identique. En indexant l'extraction sur le **texte**, un repost coûte zéro
appel LLM. Idem pour une même barrette mise en vente sur deux sources à la fois.

---

## 2. Schéma

### `listings` — une ligne par annonce vue

```sql
CREATE TABLE listings (
  source       TEXT    NOT NULL,
  external_id  TEXT    NOT NULL,
  spec_hash    TEXT    NOT NULL REFERENCES spec_cache(spec_hash),
  url          TEXT    NOT NULL,
  title        TEXT    NOT NULL,
  description  TEXT,
  price        TEXT    NOT NULL,      -- Decimal sérialisé, JAMAIS de REAL (PRIMER §5.8)
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
  raw_payload  BLOB    NOT NULL,      -- zstd/gzip de la charge utile d'origine
  PRIMARY KEY (source, external_id)
);

CREATE INDEX idx_listings_spec     ON listings(spec_hash);
CREATE INDEX idx_listings_seen     ON listings(last_seen);
CREATE INDEX idx_listings_auction  ON listings(ends_at) WHERE sale_type = 'auction';
```

Les montants sont stockés en `TEXT` et relus en `Decimal`. Un `REAL` SQLite est un
flottant IEEE 754 : stocker de l'argent dedans introduit des erreurs d'arrondi qui se
propagent jusqu'au €/Go et donc jusqu'au seuil d'alerte.

### `spec_cache` — l'extraction, indexée sur le texte

```sql
CREATE TABLE spec_cache (
  spec_hash          TEXT PRIMARY KEY,
  module_capacity_gb INTEGER,
  module_count       INTEGER NOT NULL DEFAULT 1,
  total_gb           INTEGER,
  kind               TEXT    NOT NULL,
  speed_mts          INTEGER,
  ranks              TEXT,
  part_number        TEXT,
  price_basis        TEXT    NOT NULL,
  confidence         REAL    NOT NULL,
  method             TEXT    NOT NULL,   -- part_number | rules | llm
  reject_reason      TEXT,               -- NULL si qualifiée  ← cache NÉGATIF
  parser_version     INTEGER NOT NULL,   -- invalide le cache quand le parseur évolue
  created_at         TEXT    NOT NULL
);

CREATE INDEX idx_spec_reject ON spec_cache(reject_reason) WHERE reject_reason IS NOT NULL;
CREATE INDEX idx_spec_method ON spec_cache(method);
```

Deux champs méritent attention.

`reject_reason` met en cache les **rejets** : une annonce écartée n'est jamais
réévaluée. Comme le motif est conservé, corriger un bug du parseur permet de savoir
exactement quels rejets rejouer. Sans ce champ, un rejet est une décision définitive
et invisible.

`parser_version` est incrémenté à chaque changement de la cascade. Une entrée dont
la version est antérieure est recalculée à la demande — c'est ce qui évite de vider
tout le cache à chaque correction de regex.

### `market_stats` — l'indice glissant

```sql
CREATE TABLE market_stats (
  computed_at     TEXT    NOT NULL,
  capacity_bucket INTEGER NOT NULL,     -- 8 | 16 | 32 | 64
  p25             TEXT    NOT NULL,
  p50             TEXT    NOT NULL,     -- la référence utilisée par la barrière relative
  p75             TEXT    NOT NULL,
  sample_size     INTEGER NOT NULL,     -- < seuil ⇒ indice non fiable, mode observation
  window_days     INTEGER NOT NULL,
  PRIMARY KEY (computed_at, capacity_bucket)
);
```

`sample_size` est ce qui pilote le mode observation : tant que l'échantillon est trop
maigre, la barrière relative est ignorée et seule la barrière absolue s'applique.

### `alerts` — ce qui est réellement parti

```sql
CREATE TABLE alerts (
  id           INTEGER PRIMARY KEY,
  fingerprint  TEXT NOT NULL,
  source       TEXT NOT NULL,
  external_id  TEXT NOT NULL,
  eur_per_gb   TEXT NOT NULL,
  discount     REAL NOT NULL,
  urgency      TEXT NOT NULL,
  sent_at      TEXT NOT NULL,
  outcome      TEXT,                    -- NULL | 'ignored' | 'bought' — alimenté par WP09
  FOREIGN KEY (source, external_id) REFERENCES listings(source, external_id)
);

CREATE INDEX idx_alerts_fp   ON alerts(fingerprint, sent_at);
CREATE INDEX idx_alerts_sent ON alerts(sent_at);
```

### `source_runs` — le socle du chien de garde

```sql
CREATE TABLE source_runs (
  run_id       TEXT    PRIMARY KEY,
  source       TEXT    NOT NULL,
  started_at   TEXT    NOT NULL,
  duration_ms  INTEGER NOT NULL,
  raw_count    INTEGER NOT NULL,       -- annonces vues, avant dédoublonnage
  new_count    INTEGER NOT NULL,       -- jamais vues
  qualified    INTEGER NOT NULL,       -- ayant passé compat.yaml
  alerted      INTEGER NOT NULL,
  challenged   INTEGER NOT NULL DEFAULT 0,
  error        TEXT
);

CREATE INDEX idx_runs_source ON source_runs(source, started_at);
```

**C'est la table la plus importante pour l'exploitation.** Sans elle, une source qui
tombe est indiscernable d'un marché calme.

### `llm_queue` — les deux voies (WP07)

```sql
CREATE TABLE llm_queue (
  spec_hash    TEXT PRIMARY KEY REFERENCES spec_cache(spec_hash),
  lane         TEXT    NOT NULL,       -- 'urgent' | 'deferred'
  best_case    TEXT,                   -- €/Go du meilleur cas, sert au tri
  attempts     INTEGER NOT NULL DEFAULT 0,
  enqueued_at  TEXT    NOT NULL,
  last_try_at  TEXT
);

CREATE INDEX idx_queue_lane ON llm_queue(lane, best_case);
```

### `account_deletion_events` — trace de conformité RGPD/CCPA (WP10)

```sql
CREATE TABLE account_deletion_events (
  notification_id  TEXT    PRIMARY KEY,   -- notification.notificationId eBay, dédoublonnage
  received_at      TEXT    NOT NULL,
  scrubbed_rows    INTEGER NOT NULL       -- lignes `listings` anonymisées
);
```

eBay réémet la même notification jusqu'à ~24 h : la clé primaire rend le
traitement idempotent. Le `username` reçu n'est **jamais** persisté — l'effacer
est justement l'objet de la notification.

---

## 3. Rétention

| Table | Conservation | Motif |
|---|---|---|
| `listings` | 90 jours, puis purge de `description` et `seller_id` ; anonymisation immédiate sur notification eBay (WP10) | Données personnelles minimisées ; `raw_payload` et le reste sont conservés pour le rejeu |
| `spec_cache` | indéfinie | Ne contient aucune donnée personnelle et vaut son poids en appels LLM économisés |
| `market_stats` | indéfinie | Volume négligeable, valeur historique |
| `alerts` | indéfinie | Base de la boucle d'amélioration |
| `source_runs` | 180 jours | Diagnostic |
| `llm_queue` | vidée au traitement | File de travail |
| `account_deletion_events` | indéfinie | Trace de conformité, sans donnée personnelle |

La purge est une tâche du planificateur, pas un script manuel.

---

## 4. Sauvegarde

`sqlite3 ramtracker.db ".backup backups/ramtracker-<date>.db"`, quotidienne,
sept jours de rétention glissante. Une copie `cp` d'une base en WAL pendant une
écriture produit un fichier incohérent — utiliser `.backup`, jamais `cp`.
