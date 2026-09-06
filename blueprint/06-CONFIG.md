# 06 — Configuration

> Prérequis : [00-PRIMER.md](00-PRIMER.md)
>
> **Interdit n°1 : aucun seuil ni paramètre en dur dans le code.** Tout ce qui suit
> se lit via `core.config`, jamais via `os.environ` dispersé dans les modules.

Deux niveaux : les **secrets et chemins** en `.env`, le **comportement** en YAML
versionné. Priorité : variable d'environnement > YAML > défaut du modèle pydantic.

---

## 1. Variables d'environnement — `.env.example`

| Variable | Requis | Défaut | Rôle |
|---|---|---|---|
| `RAMTRACKER_DB_PATH` | non | `./ramtracker.db` | Chemin de la base SQLite |
| `RAMTRACKER_LOG_LEVEL` | non | `INFO` | Niveau de journalisation |
| `RAMTRACKER_CONFIG_DIR` | non | `./configs` | Répertoire des fichiers YAML |
| `EBAY_CLIENT_ID` | **oui** | — | Identifiant applicatif eBay |
| `EBAY_CLIENT_SECRET` | **oui** | — | `SecretStr` |
| `EBAY_ZIP` | non | — | Code postal pour `X-EBAY-C-ENDUSERCTX` — sans lui le port est faux |
| `REDDIT_CLIENT_ID` | non | — | Application « script » (WP08) |
| `REDDIT_CLIENT_SECRET` | non | — | `SecretStr` |
| `REDDIT_USER_AGENT` | non | — | Descriptif, obligatoire côté Reddit |
| `NTFY_URL` | **oui** | — | URL complète du sujet, jeton compris — `SecretStr` |
| `LLM_BASE_URL` | non | `http://127.0.0.1:8080/v1` | Serveur local partagé avec OpenHands |
| `LLM_MODEL` | non | — | Nom du modèle servi |
| `ANTHROPIC_API_KEY` | non | — | Repli de la voie urgente uniquement — `SecretStr` |

`get_settings()` **lève `ConfigError`** en nommant la variable manquante. Aucun repli
silencieux : une clé eBay absente doit arrêter le démarrage, pas produire zéro
annonce (ce qui ressemblerait à un marché calme — cf. principe P3 du primer).

---

## 2. `configs/compat.yaml` — livré par WP00

La matrice de qualification. Contenu détaillé en
[10-HARDWARE-TARGET.md](10-HARDWARE-TARGET.md).

```yaml
generation:      { accept: [ddr4, pc4], reject: [ddr3, pc3, ddr5] }
registration:    { accept: [rdimm, lrdimm], reject: [udimm_non_ecc] }
form_factor:     { accept: [dimm_288], reject: [sodimm, dimm_260] }
speed_mts:       { native: [2133, 2400], accept_downclock: [2666, 2933, 3200] }
ranks:           { accept: ["1Rx4", "2Rx4", "2Rx8", "4Rx4"], reject: ["x16"] }
capacity_gb:     { accept: [8, 16, 32, 64], reject: [4] }

part_numbers:
  samsung:
    family:   { M393: rdimm, M386: lrdimm, M378: reject, M471: reject }
    density:  { A1G43: 8, A2G40: 16, A4K40: 32, A8K40: 64 }
    speed:    { CPB: 2133, CRC: 2400, CTD: 2666 }
  hynix:    { }   # [À CONFIRMER] au spike WP00
  micron:   { }   # [À CONFIRMER] au spike WP00

reject_keywords: [sodimm, portable, laptop, "so-dimm", ddr3, pc3, ddr5]
```

---

## 3. `configs/sources.yaml`

```yaml
ebay:
  enabled: true
  interval_min: 10
  jitter_min: 2
  marketplaces: [EBAY_FR, EBAY_DE]
  category_ids: ["170083"]        # [À CONFIRMER] au spike WP00
  queries: ["DDR4 ECC RDIMM", "PC4-2133P", "PC4-2400T"]
  price_range_eur: [15, 3000]
  limit: 200

reddit:
  enabled: false                  # activé en WP08
  interval_min: 15
  jitter_min: 3
  subreddits: [homelabsales]
  shippable_from: [EU, UK]

leboncoin:
  enabled: false                  # activé en WP08
  interval_min: 75
  jitter_min: 20
  category: 17
  queries: ["DDR4 ECC", "DDR4 REG serveur"]
  impersonate: chrome
  max_pages: 1                    # jamais de pagination profonde
```

`interval_min` et `jitter_min` ne sont pas décoratifs : un scan qui tombe exactement
à la minute ronde, quatorze fois par jour, est un motif que tout système de détection
remarque.

---

## 4. `configs/thresholds.yaml`

```yaml
barriers:
  hard_ceiling_eur_per_gb: "3.50"   # barrière absolue — Decimal en chaîne
  min_discount: 0.25                # barrière relative, contre l'indice glissant

guards:
  plausibility_floor_eur_per_gb: "0.50"   # en dessous : bug de parsing, renvoi au LLM
  min_total_gb: 32                        # un module isolé de 8 Go n'est pas un bon achat
  min_confidence: 0.80                    # seuil de court-circuit de la cascade

market_index:
  window_days: 30
  min_sample_size: 20               # en dessous : mode observation
  refresh_interval_min: 60
  capacity_buckets: [8, 16, 32, 64]

observation_mode:
  enabled: true
  until: "2026-09-20"               # 14 jours : barrière absolue seule + récapitulatif quotidien

auction:
  gate_minutes: 90                  # avant la fin : veille silencieuse
  bid_increment_eur: "5.00"         # marge ajoutée à la cote pour évaluer le seuil
  notify_once: true

spam:
  daily_cap_urgent: 6
  re_alert_min_drop_pct: 10
  quiet_hours: { from: "23:00", to: "07:00", downgrade_to: 3 }

llm:
  enabled: false                    # activé en WP07
  concurrency: 1                    # JAMAIS plus (PRIMER §5.9)
  batch_size: 4
  timeout_s: 45
  urgent_lane_margin: 0.50          # best_case < 50 % de la barrière ⇒ voie urgente
  deferred_drain_interval_min: 30
  remote_fallback: true             # voie urgente uniquement

watchdog:
  empty_cycles_before_alert: 3
  min_prior_activity: 5             # n'alerte que sur une source qui produisait avant
```

`observation_mode.until` est une date, pas un booléen : le mode se désactive tout
seul, sans qu'il faille y penser.

---

## 5. Ajouter un paramètre

1. L'ajouter au modèle pydantic correspondant dans `core/config.py`, **avec type et
   défaut explicites**.
2. L'ajouter au fichier YAML ci-dessus et à ce document.
3. Si c'est un secret : `SecretStr`, `.env.example` mis à jour, **jamais** de valeur
   réelle committée.
4. Ajouter un test qui vérifie que l'absence de la variable produit une erreur
   explicite plutôt qu'un comportement dégradé.
