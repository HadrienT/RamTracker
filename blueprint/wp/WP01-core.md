# WP01 — `core` (noyau partagé)

> **Contexte** : RamTracker est un agent de veille sur les annonces de mémoire
> serveur d'occasion. Monorepo Python 3.13 géré par `uv`, base **SQLite** en WAL,
> un seul processus. Cinq packages métier (`collect`, `extract`, `decide`, `notify`,
> `runtime`) s'appuient sur `core`.
>
> `core` est le **seul** package qui lit la configuration, ouvre la base, définit les
> erreurs, la journalisation et les DTO. Il **ne dépend d'aucun autre package du
> dépôt** (contrat D1).

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[03-INTERFACES.md](../03-INTERFACES.md) §1–2 · [04-DATA-MODEL.md](../04-DATA-MODEL.md) ·
[06-CONFIG.md](../06-CONFIG.md) · [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) ·
[09-CONVENTIONS.md](../09-CONVENTIONS.md)

**Dépend de** : rien (WP00 en parallèle). **Bloque** : WP02, WP03, WP04, WP05.

---

## 1. Objectif

Fournir un socle stable et sans métier : configuration, journalisation, taxonomie
d'erreurs, accès base, DTO, monnaie, hachage, horloge.

**`core` est volontairement petit.** Tout ce qui est spécifique à un domaine n'y
appartient pas. En particulier : aucune règle de seuil, aucune connaissance des
sources, aucune notion de « bonne affaire ».

---

## 2. Modules & responsabilités

| Module | Responsabilité | Ne contient pas |
|---|---|---|
| `config.py` | Modèles de settings, `.env` + YAML, singleton, validation | valeurs métier |
| `errors.py` | Taxonomie `AppError` et sous-classes | messages métier |
| `logging.py` | `structlog` JSON, `run_id` contextuel | métriques agrégées |
| `db.py` | Connexion WAL, `session_scope`, `apply_migrations`, `check_health` | requêtes métier |
| `models.py` | `RawListing`, `MemorySpec`, `Deal` et leurs énumérations | toute règle de décision |
| `money.py` | `Decimal`, arrondis, conversion de devise, `eur_per_gb` | seuils |
| `hashing.py` | `spec_hash`, `fingerprint` | — |
| `clock.py` | `utc_now()` injectable | fuseaux métier |

---

## 3. Contrats clés

### 3.1 Configuration

- `get_settings()` : singleton, **lève `ConfigError`** en nommant la variable
  manquante. Aucune valeur de secours silencieuse — une clé eBay absente doit
  arrêter le démarrage, pas produire zéro annonce.
- `load_yaml(name, model)` : charge `configs/<name>.yaml` et valide contre le modèle
  fourni par l'appelant. `core` ne connaît pas les schémas métier, il reçoit le type.
- Les secrets sont des `SecretStr` et ne sont **jamais** sérialisés.

### 3.2 Base

- `session_scope()` : commit en sortie normale, rollback sur exception, fermeture
  garantie.
- `apply_migrations()` : applique `migrations/` dans l'ordre, **forward-only**,
  idempotent, table `schema_migrations`.
- `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout` depuis la config.

### 3.3 Monnaie — le garde-fou

`money.py` est le seul endroit où un montant est manipulé.

- Les montants sont des `Decimal`, sérialisés en `TEXT` en base. **Aucun `float` ne
  touche un montant**, de la lecture d'API à l'écriture (règle N3).
- `total_cost(price, shipping)` : si `shipping is None`, l'estimation est appliquée
  **explicitement** et le fait est retourné, pas absorbé. `None` et `0` ne sont
  jamais coalescés (règle N4).
- `eur_per_gb(total_cost, total_gb)` : `quantize` à 4 décimales, `ROUND_HALF_UP`.
  Lève sur `total_gb <= 0` plutôt que de retourner l'infini.

### 3.4 DTO

Tous `frozen=True`. Un étage du pipeline retourne un nouvel objet, il ne mute pas son
entrée : c'est ce qui rend chaque étage testable isolément.

`RawListing.shipping` a un validateur qui **interdit** la valeur `0` quand la source
n'a pas explicitement annoncé la gratuité — le collecteur doit passer `None`.

---

## 4. Migrations livrées par ce WP

```text
migrations/0001_init.sql          listings, schema_migrations, PRAGMA
migrations/0002_spec_cache.sql    spec_cache + index
```

`market_stats`, `alerts`, `source_runs` et `llm_queue` sont livrés par WP04, WP05,
WP06 et WP07 respectivement.

---

## 5. Tests attendus

| Test | Attendu |
|---|---|
| Variable requise absente | `ConfigError` nommant la variable |
| Priorité de configuration | env > YAML > défaut |
| Secret non sérialisé | `model_dump()` ne révèle pas la valeur |
| `session_scope` | rollback effectif sur exception |
| Migrations | base vide → schéma attendu ; réapplication → no-op |
| `eur_per_gb(Decimal("100"), 64)` | `Decimal("1.5625")` |
| `eur_per_gb(x, 0)` | lève, ne retourne pas l'infini |
| `total_cost` avec `shipping=None` | estimation appliquée **et signalée** |
| `total_cost` avec `shipping=0` | 0 réellement ajouté, pas d'estimation |
| `RawListing(shipping=0)` non annoncé gratuit | rejeté par le validateur |
| `utc_now` | aware, UTC, substituable en test |
| `spec_hash` | stable après normalisation d'espaces et de casse |
| Journalisation | `run_id` présent dans tous les événements du bloc |

---

## 6. Critères d'acceptation

- [ ] `core` n'importe aucun autre package du dépôt (D1, vérifié par `import-linter`).
- [ ] `mypy --strict` passe.
- [ ] `.env.example` liste **toutes** les variables de [06-CONFIG.md](../06-CONFIG.md) §1.
- [ ] `apply_migrations()` fonctionne sur base vide et sur base à jour.
- [ ] Aucun secret n'apparaît dans une sortie de log en test.
- [ ] Aucun `float` n'apparaît dans une signature touchant un montant.
- [ ] `justfile` expose `just migrate`, `just lint`, `just test`, `just arch`.
