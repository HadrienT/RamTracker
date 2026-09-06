# 02 — Arborescence du dépôt

> Prérequis : [00-PRIMER.md](00-PRIMER.md) · [01-ARCHITECTURE.md](01-ARCHITECTURE.md)

Un fichier = une responsabilité. Les noms `utils.py`, `helpers.py`, `common.py` et
`misc.py` sont **interdits** ([09-CONVENTIONS.md](09-CONVENTIONS.md) §2).

---

```text
RamTracker/
├── blueprint/                    # ce dossier — la spécification
├── docs/
│   └── blueprint.html            # document narratif (le « pourquoi »)
├── tools/
│   └── charge_llm.py             # modèle d'entonnoir : charge LLM, coût VRAM
├── configs/
│   ├── compat.yaml               # matrice de compatibilité + décodeur de références (WP00)
│   ├── sources.yaml              # par source : requêtes, marchés, cadence, gigue
│   └── thresholds.yaml           # barrières, garde-fous, politique d'enchères, anti-spam
├── migrations/                   # SQL brut, forward-only, appliqué dans l'ordre
│   ├── 0001_init.sql
│   ├── 0002_spec_cache.sql
│   ├── 0003_market_stats.sql
│   └── 0004_alerts.sql
├── src/ramtracker/
│   ├── core/
│   │   ├── config.py             # Settings pydantic, chargement .env + YAML, singleton
│   │   ├── errors.py             # taxonomie AppError et sous-classes
│   │   ├── logging.py            # structlog JSON, run_id contextuel
│   │   ├── db.py                 # connexion WAL, session_scope, apply_migrations
│   │   ├── models.py             # RawListing, MemorySpec, Deal — DTO purs
│   │   ├── money.py              # Decimal, arrondis, conversion de devise
│   │   ├── hashing.py            # spec_hash, fingerprint
│   │   └── clock.py              # utc_now injectable
│   ├── collect/
│   │   ├── base.py               # Protocol Collector, CollectResult
│   │   ├── ebay.py               # WP03 — API Browse, jeton en cache, achat + enchère
│   │   ├── leboncoin.py          # WP08 — curl_cffi, __NEXT_DATA__, détection de défi
│   │   ├── reddit.py             # WP08 — OAuth script, parseur de titres [H]/[W]
│   │   └── registry.py           # nom de source → instance, depuis sources.yaml
│   ├── extract/
│   │   ├── partnum.py            # étage 1 — décodeur de références constructeur
│   │   ├── grammar.py            # étage 2 — grammaire d'expressions régulières
│   │   ├── coherence.py          # étage 3 — contrôles croisés, ajustement de confiance
│   │   ├── prefilter.py          # étage 4 — borne optimiste, préfiltre €/Go (WP07)
│   │   ├── llm.py                # étage 5 — repli LLM local (WP07) — SEULE I/O du package
│   │   ├── qualify.py            # application de compat.yaml, motif de rejet
│   │   └── cascade.py            # orchestration des étages, court-circuit sur confiance
│   ├── decide/
│   │   ├── dedupe.py             # external_id, spec_hash, fingerprint
│   │   ├── market.py             # indice glissant p50 par compartiment de capacité
│   │   ├── thresholds.py         # double barrière, garde-fous, mode observation
│   │   └── auction.py            # porte des 90 min, max_bid, notification unique
│   ├── notify/
│   │   ├── base.py               # Protocol Notifier
│   │   ├── ntfy.py               # implémentation ntfy
│   │   ├── templates.py          # rendu achat immédiat / enchère
│   │   └── ratelimit.py          # cooldown, plafond quotidien, silence nocturne
│   └── runtime/
│       ├── pipeline.py           # câblage des huit étages
│       ├── scheduler.py          # cadence par source, gigue
│       ├── breaker.py            # disjoncteur par source, repli exponentiel
│       ├── watchdog.py           # chien de garde inversé
│       ├── llm_queue.py          # voies urgente et différée (WP07)
│       └── cli.py                # run-once, backfill, replay, report
├── tests/
│   ├── fixtures/
│   │   ├── titles.jsonl          # LE CORPUS DORÉ — 150 annonces étiquetées (WP00)
│   │   └── payloads/             # charges utiles réelles par source, pour les collecteurs
│   ├── test_partnum.py
│   ├── test_grammar.py
│   ├── test_coherence.py
│   ├── test_cascade_golden.py    # non-régression sur le corpus doré
│   ├── test_prefilter.py         # dont la propriété d'admissibilité
│   ├── test_qualify.py
│   ├── test_market.py
│   ├── test_thresholds.py
│   ├── test_auction.py
│   ├── test_ratelimit.py
│   ├── test_collect_ebay.py      # contre les charges utiles figées
│   └── test_invariants.py        # I1 → I6 de 08-TESTING.md
├── deploy/
│   ├── ramtracker.service
│   ├── ramtracker.timer
│   └── docker-compose.yml
├── .env.example                  # toutes les variables de 06-CONFIG.md §2
├── pyproject.toml                # uv, ruff, mypy --strict, contrats import-linter
├── justfile                      # just migrate | lint | test | run-once | report
└── README.md
```

---

## Responsabilités qui prêtent à confusion

| Fichier | Contient | Ne contient **pas** |
|---|---|---|
| `core/models.py` | Les trois DTO et leurs validateurs de champ | toute règle de décision |
| `extract/qualify.py` | L'application de `compat.yaml` à une spec | la lecture du fichier YAML (c'est `core/config.py`) |
| `extract/cascade.py` | L'ordre des étages et le court-circuit | la logique d'un étage |
| `decide/thresholds.py` | La décision d'alerter et l'urgence | le rendu du message |
| `notify/ratelimit.py` | Le droit d'envoyer maintenant | la décision d'alerter |
| `runtime/pipeline.py` | Le câblage, la persistance, la gestion d'erreur par étage | toute règle métier |
| `runtime/breaker.py` | L'état ouvert/fermé par source et le calendrier de repli | la détection du défi anti-bot (c'est `collect/leboncoin.py`) |

La dernière ligne mérite attention : **le collecteur détecte**, le disjoncteur
**décide**. Un collecteur qui gérerait lui-même son repli rendrait la politique
invisible et non testable.
