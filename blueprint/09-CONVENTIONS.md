# 09 — Conventions de code

> Prérequis : [00-PRIMER.md](00-PRIMER.md)
>
> **À lire avant de coder quoi que ce soit.**

---

## 1. Outillage

| Rôle | Outil | Configuration |
|---|---|---|
| Environnement & dépendances | `uv` | `pyproject.toml` |
| Lint & format | `ruff` | ligne 100 |
| Typage | `mypy --strict` | tous les packages |
| Tests | `pytest` + `hypothesis` | marqueurs de [08-TESTING.md](08-TESTING.md) |
| Règles d'architecture | `import-linter` | contrats D1→D8 de [01-ARCHITECTURE.md](01-ARCHITECTURE.md) |
| Migrations | SQL brut versionné | `migrations/` |
| Tâches | `just` | `justfile` |

Python **3.13** partout — poste, serveur, CI.

---

## 2. Nommage

| Élément | Convention | Exemple |
|---|---|---|
| Package | `snake_case`, court | `collect`, `extract`, `decide`, `notify` |
| Module | `snake_case`, nom = responsabilité | `grammar.py`, `prefilter.py`, `watchdog.py` |
| Classe | `PascalCase` | `Breaker`, `CollectResult` |
| Protocol | `PascalCase`, sans suffixe `Interface`/`ABC` | `Collector`, `Notifier` |
| DTO pydantic | `PascalCase` + suffixe de rôle | `RawListing`, `MemorySpec`, `RunReport` |
| Fonction | `snake_case`, verbe | `fetch_recent`, `optimistic_total_gb` |
| Constante | `UPPER_SNAKE` | `DEFAULT_WINDOW_DAYS` |
| Table SQL | `snake_case` pluriel | `listings`, `source_runs` |
| Migration | `NNNN_description.sql` | `0002_spec_cache.sql` |
| Motif de rejet | `snake_case`, stable, jamais traduit | `sodimm`, `meilleur_cas_hors_seuil` |

**Interdits de nommage** : `utils.py`, `helpers.py`, `misc.py`, `common.py`,
`manager.py`, ainsi que `data`, `tmp`, `obj`, `mgr`, `do_stuff`.

Les motifs de rejet sont des identifiants, pas des messages : ils sont persistés en
base, comparés en test et utilisés pour cibler un rejeu. Les renommer casse
l'historique.

---

## 3. Unités et grandeurs

**Cause n°1 de bug silencieux dans ce projet.** Une confusion d'unité ne plante pas :
elle produit une alerte plausible et fausse.

| Grandeur | Type | Unité | Nom de paramètre |
|---|---|---|---|
| Capacité | `int` | gigaoctets | `module_capacity_gb`, `total_gb` — **suffixe obligatoire** |
| Fréquence | `int` | MT/s | `speed_mts` — jamais `speed` ni `mhz` |
| Argent | `Decimal` | devise de `currency` | `price`, `shipping`, `total_cost` |
| Prix rapporté | `Decimal` | €/Go | `eur_per_gb` |
| Décote | `float` | fraction 0→1 | `discount` — **jamais** en pourcents |
| Confiance | `float` | fraction 0→1 | `confidence` |
| Durée | `int` | suffixe obligatoire | `timeout_s`, `interval_min`, `duration_ms`, `window_days` |
| Horodatage | `datetime` **aware UTC** | — | `ts`, `posted_at`, `ends_at` |

| # | Règle |
|---|---|
| **N1** | Tout paramètre porte son unité en suffixe : `_gb`, `_mts`, `_s`, `_min`, `_ms`, `_days`. |
| **N2** | Aucun pourcentage n'entre dans le code. `discount=0.25`, jamais `25`. La conversion se fait à l'affichage. |
| **N3** | L'argent est en `Decimal`. Aucun `float` ne touche un montant, de la lecture de l'API à l'écriture en base. |
| **N4** | `shipping=None` (inconnu) et `shipping=0` (gratuit) sont **deux choses différentes**. Ne jamais coalescer l'un en l'autre. Un port inconnu s'estime explicitement, et l'estimation est tracée. |
| **N5** | Aucun `datetime.now()`. `core.clock.utc_now()` uniquement, pour que les tests puissent figer l'horloge. |
| **N6** | Les capacités sont des entiers en Go. Jamais de Mo, jamais de Tio, jamais de flottant. |

N4 mérite d'être souligné : sur Leboncoin la remise en main propre est gratuite, sur
eBay le port peut valoir 15 % du prix. Confondre « inconnu » et « gratuit » fausse le
€/Go vers le bas, c'est-à-dire dans le sens qui déclenche une alerte.

---

## 4. Typage

- `mypy --strict`, aucun `# type: ignore` sans commentaire justificatif sur la même ligne.
- Aucun `Any` dans une signature publique.
- Les DTO sont `frozen=True`. Un étage du pipeline retourne un nouvel objet, il ne
  mute pas son entrée — c'est ce qui rend chaque étage testable isolément.
- Les énumérations sont des `StrEnum`, pour être lisibles en base et en JSON.

---

## 5. Style

- Docstring d'une ligne sur les fonctions publiques uniquement. Le code dit *comment*,
  le blueprint dit *pourquoi*.
- Un commentaire explique une décision non évidente, jamais ce que fait la ligne.
- Fonctions courtes, un niveau d'abstraction par fonction.
- Aucune valeur littérale de seuil dans le code : elle vient de la configuration.

---

## 6. Definition of Done

- [ ] `mypy --strict` passe.
- [ ] `ruff` passe.
- [ ] `import-linter` passe (contrats D1→D8).
- [ ] Tests unitaires ; pour `extract`, non-régression sur le corpus doré.
- [ ] Les invariants de [08-TESTING.md](08-TESTING.md) §2 concernés sont couverts.
- [ ] Aucun seuil ni paramètre en dur.
- [ ] Erreurs issues de la taxonomie de [07-ERRORS-AND-LOGGING.md](07-ERRORS-AND-LOGGING.md).
- [ ] Journalisation structurée aux frontières, avec `run_id`.
- [ ] Aucun secret dans le code ni dans les logs.
- [ ] `.env.example` à jour si une variable a été ajoutée.
- [ ] Points d'API tierce incertains marqués `[À CONFIRMER]`, jamais devinés.
