# 03 — Interfaces

> Prérequis : [00-PRIMER.md](00-PRIMER.md) · [01-ARCHITECTURE.md](01-ARCHITECTURE.md)
>
> **Signatures uniquement, aucun corps.** Ce fichier est le contrat entre packages.
> Une modification ici est une modification d'API : elle se propage aux WP concernés.

---

## 1. `core.models` — les trois DTO

Tous en `pydantic.BaseModel`, immuables (`model_config = ConfigDict(frozen=True)`).

```python
class SaleType(StrEnum):
    BUY_NOW    = "buy_now"
    AUCTION    = "auction"
    BEST_OFFER = "best_offer"

class Kind(StrEnum):
    RDIMM     = "rdimm"
    LRDIMM    = "lrdimm"
    UDIMM_ECC = "udimm_ecc"
    UNKNOWN   = "unknown"

class PriceBasis(StrEnum):
    LOT     = "lot"       # le prix affiché couvre tous les modules
    UNIT    = "unit"      # le prix affiché couvre UN module
    UNKNOWN = "unknown"   # interdit d'alerter en l'état — voir PRIMER §5.5

class Method(StrEnum):
    PART_NUMBER = "part_number"
    RULES       = "rules"
    LLM         = "llm"

class Urgency(StrEnum):
    IMMEDIATE = "immediate"   # achat immédiat sous les deux barrières
    QUIET     = "quiet"       # enchère en fin de course
    WATCH     = "watch"       # enchère en veille, aucune notification
    NONE      = "none"


class RawListing(BaseModel):
    source:       str                    # clé de sources.yaml
    external_id:  str                    # identifiant natif de la source
    spec_hash:    str                    # sha256(titre + description normalisés)
    url:          str
    title:        str
    description:  str | None
    price:        Decimal
    currency:     str                    # ISO 4217
    shipping:     Decimal | None         # None = INCONNU, 0 = gratuit. Jamais confondre.
    sale_type:    SaleType
    current_bid:  Decimal | None
    ends_at:      datetime | None        # aware UTC, enchères uniquement
    seller_id:    str | None
    country:      str                    # ISO 3166-1 alpha-2
    posted_at:    datetime               # aware UTC
    raw_payload:  bytes                  # charge utile d'origine, compressée (PRIMER §5.10)


class MemorySpec(BaseModel):
    module_capacity_gb: int | None
    module_count:       int = 1
    total_gb:           int | None       # dérivé, ou annoncé puis vérifié
    kind:               Kind
    speed_mts:          int | None       # 2133 | 2400 | 2666 …
    ranks:              str | None       # "2Rx4"
    part_number:        str | None
    price_basis:        PriceBasis
    confidence:         float            # 0.0 → 1.0
    method:             Method
    reject_reason:      str | None       # None si qualifiée


class Deal(BaseModel):
    listing:     RawListing
    spec:        MemorySpec
    total_cost:  Decimal                 # price + shipping (estimé si None)
    eur_per_gb:  Decimal
    market_ref:  Decimal                 # indice glissant pour ce compartiment
    discount:    float                   # 1 − (eur_per_gb / market_ref)
    urgency:     Urgency
    max_bid:     Decimal | None          # enchères : plafond à ne pas dépasser
    fingerprint: str
```

---

## 2. `core` — services transverses

```python
# core.config
def get_settings() -> Settings: ...                    # singleton, lève ConfigError
def load_yaml(name: str, model: type[T]) -> T: ...     # configs/<name>.yaml, validé

# core.clock — injectable, jamais datetime.now() (PRIMER §7)
def utc_now() -> datetime: ...

# core.hashing
def spec_hash(title: str, description: str | None) -> str: ...
def fingerprint(seller_id: str | None, capacity_gb: int | None,
                count: int, price: Decimal) -> str: ...

# core.money
def to_eur(amount: Decimal, currency: str, rates: Mapping[str, Decimal]) -> Decimal: ...
def eur_per_gb(total_cost: Decimal, total_gb: int) -> Decimal: ...   # quantize 4 décimales

# core.db
@contextmanager
def session_scope() -> Iterator[Connection]: ...       # commit / rollback / close garantis
def apply_migrations() -> int: ...                     # forward-only, idempotent
def check_health() -> HealthReport: ...
```

`get_settings()` **lève** si une variable requise manque. Aucune valeur de secours
silencieuse. Les secrets sont des `SecretStr` et ne sont jamais sérialisés.

---

## 3. `collect` — un contrat de trois lignes

```python
class CollectResult(BaseModel):
    source:      str
    listings:    list[RawListing]
    raw_count:   int          # avant dédoublonnage — alimente le chien de garde
    duration_ms: int
    challenged:  bool = False # défi anti-bot détecté (Leboncoin)

class Collector(Protocol):
    name: str
    def fetch_recent(self, since: datetime) -> CollectResult: ...
```

Règles pour toute implémentation :

- Elle **détecte** un blocage et le signale via `challenged` ou en levant
  `SourceBlocked`. Elle ne **décide** jamais de réessayer — c'est `runtime.breaker`.
- Elle remplit `raw_count` même quand `listings` est vide. C'est ce compteur qui
  distingue « la source répond mais n'a rien de nouveau » de « la source est cassée ».
- Elle ne parallélise jamais ses requêtes (PRIMER §5.13).
- `shipping` reste `None` si la source ne le donne pas. Ne jamais mettre `0`.

### 3.1 eBay — `[À CONFIRMER]` au spike WP00

```
POST  /identity/v1/oauth2/token        grant_type=client_credentials
      scope=https://api.ebay.com/oauth/api_scope        → jeton 2 h, en cache disque

GET   /buy/browse/v1/item_summary/search
      ?q=…&category_ids=170083                          [À CONFIRMER] id de catégorie
      &filter=buyingOptions:{FIXED_PRICE|BEST_OFFER},price:[15..3000],priceCurrency:EUR
      &sort=newlyListed&limit=200
      X-EBAY-C-MARKETPLACE-ID: EBAY_FR | EBAY_DE
      X-EBAY-C-ENDUSERCTX: contextualLocation=country=FR,zip=…   ← sinon port faux
```

Sans `X-EBAY-C-ENDUSERCTX`, les frais de port renvoyés sont ceux du marché par
défaut et le €/Go calculé est faux. Ce n'est pas cosmétique.

### 3.2 Leboncoin — `[À CONFIRMER]` au spike WP00

```
GET   /recherche?text=…&category=17&sort=time     via curl_cffi, impersonate="chrome"
      → <script id="__NEXT_DATA__">
        props.pageProps.searchData.ads                       chemin courant
        props.pageProps.initialProps.searchData.ads          repli
      → list_id · subject · body · price[0] · url · location · owner · index_date
```

### 3.3 Reddit

```
POST  /api/v1/access_token           application « script »
GET   /r/homelabsales/new?limit=100  User-Agent descriptif obligatoire
      → titres au format [Pays] [H] … [W] …
```

Reddit est traité en priorité comme **capteur de prix** alimentant l'indice de
marché ; seules les annonces expédiables depuis l'Europe remontent à l'alerte.

---

## 4. `extract` — la cascade

```python
# extract.partnum — étage 1, déterministe, confiance 1.0
def decode(text: str) -> MemorySpec | None: ...

# extract.grammar — étage 2
def parse(text: str) -> MemorySpec: ...                # confiance 0.60 → 0.95

# extract.coherence — étage 3, ajuste la confiance, ne rejette pas
def check(spec: MemorySpec, text: str) -> MemorySpec: ...

# extract.prefilter — étage 4 (WP07)
def optimistic_total_gb(text: str) -> int | None: ...  # MAJORANT de la capacité
def best_case_eur_per_gb(listing: RawListing, text: str) -> Decimal | None: ...

# extract.llm — étage 5 (WP07) — SEULE I/O du package (contrat D8)
def extract_batch(listings: Sequence[RawListing]) -> list[MemorySpec]: ...

# extract.qualify — application de compat.yaml
def qualify(spec: MemorySpec, matrix: CompatMatrix) -> MemorySpec: ...  # remplit reject_reason

# extract.cascade — orchestration
def run(listing: RawListing, matrix: CompatMatrix,
        llm: Callable[[Sequence[RawListing]], list[MemorySpec]] | None) -> MemorySpec: ...
```

`optimistic_total_gb` porte l'invariant central du préfiltre :

> Pour toute annonce, `optimistic_total_gb(texte) >= capacité réelle`.

Donc `best_case_eur_per_gb <= €/Go réel`. Si même le meilleur cas dépasse la barrière
absolue, l'annonce ne peut être une affaire sous **aucun** parsing possible : elle est
écartée sans appel LLM, **sans faux négatif par construction**. La fonction retourne
`None` quand elle ne peut rien borner — dans ce cas on ne préfiltre pas.

`cascade.run` reçoit le LLM en paramètre (`None` = désactivé). C'est ce qui permet à
WP02 d'être complet et testable avant que WP07 n'existe.

---

## 5. `decide`

```python
# decide.dedupe
def is_new(listing: RawListing, conn: Connection) -> bool: ...
def price_dropped(listing: RawListing, conn: Connection, min_pct: float) -> bool: ...

# decide.market
def refresh_index(conn: Connection, window_days: int) -> dict[int, Decimal]: ...
def reference_for(capacity_gb: int, index: Mapping[int, Decimal]) -> Decimal | None: ...

# decide.thresholds
def evaluate(listing: RawListing, spec: MemorySpec,
             index: Mapping[int, Decimal], policy: ThresholdPolicy,
             now: datetime) -> Deal | None: ...

# decide.auction
def gate(listing: RawListing, now: datetime, policy: AuctionPolicy) -> Urgency: ...
def max_bid(total_gb: int, hard_ceiling: Decimal, shipping: Decimal) -> Decimal: ...
```

`evaluate` retourne `None` quand il ne faut pas alerter. Les règles, dans l'ordre où
elles doivent être appliquées :

1. `spec.reject_reason is not None` → `None`.
2. `spec.price_basis is UNKNOWN` et `spec.method is not LLM` → `None` (PRIMER §5.5).
3. `eur_per_gb < plancher_plausibilite` (défaut 0,50 €/Go) → `None`, renvoi au LLM.
   Un prix aussi bas est un bug de parsing, pas une aubaine.
4. `total_gb < volume_minimal` (défaut 32) → `None`.
5. **Barrière absolue** : `eur_per_gb < hard_ceiling`.
6. **Barrière relative** : `discount > min_discount`. Ignorée pendant le mode
   observation des premiers jours, quand l'indice n'est pas encore fiable.
7. Enchère → `auction.gate` décide entre `WATCH` et `QUIET`.

`max_bid` inverse la formule : `(hard_ceiling × total_gb) − port_estimé`.

---

## 6. `notify`

```python
class Notification(BaseModel):
    title:    str
    body:     str
    priority: int              # 5 = achat immédiat, 2 = enchère (muette)
    tags:     list[str]
    click:    str              # URL de l'annonce
    actions:  list[Action]

class Notifier(Protocol):
    def send(self, n: Notification) -> None: ...       # lève NotifyError

# notify.templates
def render(deal: Deal) -> Notification: ...

# notify.ratelimit — décide du DROIT d'envoyer, pas de la pertinence
def allow(deal: Deal, conn: Connection, policy: SpamPolicy, now: datetime) -> bool: ...
```

`allow` applique quatre règles :

| Règle | Effet |
|---|---|
| Une alerte par `fingerprint` | Survit à une republication sous un nouvel identifiant |
| Re-alerte à la baisse seulement | Prix en baisse de plus de 10 % |
| Plafond quotidien (défaut 6) | Au-delà, bascule en récapitulatif — six affaires par jour signalent un seuil mal réglé, pas un marché qui s'écroule |
| Silence nocturne 23 h → 7 h | Priorité 5 ramenée à 3 |

Une enchère entrée dans la fenêtre de fin n'est notifiée **qu'une fois**, sinon
l'alerte se répète à chaque cycle pendant une heure et demie. Une enchère en veille
dont le prix monte au-dessus du seuil sort de la liste **silencieusement** : on ne
notifie jamais une non-affaire.

---

## 7. `runtime`

```python
# runtime.pipeline
def run_source(name: str, deps: Deps, now: datetime) -> RunReport: ...

# runtime.breaker
class Breaker:
    def allow(self, source: str, now: datetime) -> bool: ...
    def record_success(self, source: str) -> None: ...
    def record_failure(self, source: str, now: datetime) -> None: ...   # 15 min → 1 h → 4 h → 12 h

# runtime.watchdog — le chien de garde INVERSÉ
def check(conn: Connection, policy: WatchdogPolicy, now: datetime) -> list[Anomaly]: ...

# runtime.llm_queue (WP07)
def enqueue(spec_hash: str, lane: Lane, best_case: Decimal | None) -> None: ...
def drain(lane: Lane, budget: int, server_busy: Callable[[], bool]) -> int: ...

# runtime.cli
#   ramtracker run-once  --source ebay
#   ramtracker backfill  --days 30
#   ramtracker replay    --since 2026-08-01   # rejoue le parseur sur l'archive brute
#   ramtracker report    --weekly
```

`replay` est la contrepartie de l'archivage brut : il rejoue la cascade sur
l'historique et affiche le différentiel de qualification. C'est ce qui rend une
amélioration du parseur **mesurable** plutôt que devinée.
