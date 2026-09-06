# 07 — Erreurs et journalisation

> Prérequis : [00-PRIMER.md](00-PRIMER.md)

Rappel du principe **P3** : une panne silencieuse est pire qu'un crash. Ce document
existe pour qu'aucun échec ne puisse se déguiser en « marché calme ».

---

## 1. Taxonomie

Toutes les erreurs dérivent de `AppError`, qui porte un `code` stable et un
`context: dict[str, Any]` sérialisable.

```text
AppError
├── ConfigError              variable ou fichier de configuration manquant / invalide
├── SourceError
│   ├── SourceUnavailable    réseau, 5xx, timeout — transitoire
│   ├── SourceBlocked        403, défi anti-bot, 429 — déclenche le disjoncteur
│   ├── SourceAuthError      401, jeton expiré ou révoqué
│   └── SourceSchemaChanged  la réponse ne correspond plus au contrat attendu
├── ExtractError
│   ├── LowConfidence        la cascade n'a pas tranché — mise en quarantaine
│   └── LLMUnavailable       serveur local saturé ou injoignable
├── NotifyError              échec d'envoi de la notification
└── StorageError             base verrouillée, migration en échec
```

| Erreur | Qui la lève | Qui l'attrape | Effet |
|---|---|---|---|
| `ConfigError` | `core.config` | personne | **arrêt du démarrage** |
| `SourceUnavailable` | `collect.*` | `runtime.pipeline` | run marqué en échec, autres sources poursuivies |
| `SourceBlocked` | `collect.leboncoin` | `runtime.breaker` | disjoncteur, repli exponentiel |
| `SourceAuthError` | `collect.ebay` | `runtime.pipeline` | une seule reprise après rafraîchissement du jeton |
| `SourceSchemaChanged` | `collect.*` | `runtime.pipeline` | **alerte technique immédiate** — voir §4 |
| `LowConfidence` | `extract.cascade` | `runtime.pipeline` | quarantaine, aucune alerte |
| `LLMUnavailable` | `extract.llm` | `runtime.llm_queue` | voie urgente : repli distant ; voie différée : remise en file |
| `NotifyError` | `notify.*` | `runtime.pipeline` | reprise une fois, puis journalisation en `ERROR` |
| `StorageError` | `core.db` | personne | **arrêt du cycle** |

`SourceSchemaChanged` est la seule erreur de collecte qui alerte immédiatement, sans
attendre le disjoncteur : elle signale que le contrat de données a changé, ce qui ne
se répare pas tout seul.

---

## 2. Ce qui est interdit

1. `except Exception: pass`, et toute variante silencieuse.
2. Un `return None` ou une liste vide en guise de gestion d'erreur, sans journal.
3. Rattraper `AppError` de façon générique là où un sous-type précis est attendu.
4. Journaliser un secret, une clé ou l'URL complète du sujet ntfy.
5. Réessayer immédiatement après un `SourceBlocked`.

---

## 3. Contrat de journalisation

`structlog`, sortie **JSON**, un événement par ligne. Champs obligatoires sur tout
événement émis depuis un cycle :

| Champ | Type | Toujours présent |
|---|---|---|
| `ts` | ISO 8601 UTC | oui |
| `level` | `debug` … `error` | oui |
| `event` | verbe court, stable, en anglais | oui |
| `run_id` | ULID du cycle | oui, propagé par contextvar |
| `source` | clé de `sources.yaml` | dans `collect` et `runtime` |
| `listing_id` | `source:external_id` | quand une annonce est concernée |
| `spec_hash` | préfixe 12 caractères | dans `extract` |
| `duration_ms` | entier | aux frontières de package |

Événements à émettre systématiquement, quelle que soit l'issue :

```text
source.fetch.start     source raw_count=… since=…
source.fetch.done      source raw_count new_count duration_ms challenged
extract.cascade.done   spec_hash method confidence reject_reason
llm.call.done          lane batch_size duration_ms fallback_used
decide.evaluated       listing_id eur_per_gb discount urgency
notify.sent            listing_id priority
notify.suppressed      listing_id reason      ← cap, cooldown, silence nocturne
run.done               run_id sources_ok sources_failed alerts_sent
```

`notify.suppressed` est aussi important que `notify.sent` : sans lui, il est
impossible de distinguer « rien d'intéressant » de « l'anti-spam a tout mangé ».

---

## 4. Le chien de garde inversé

**La fonctionnalité que tout le monde oublie et qui rend le reste inutile.**

Un scraper cassé ne lève pas d'erreur. Leboncoin change son schéma, eBay renomme un
champ, un jeton expire : dans tous les cas, zéro annonce, zéro alerte, aucune trace.
Et zéro alerte ressemble exactement à un marché calme. Cela peut durer des mois.

La parade s'appuie sur `source_runs` ([04-DATA-MODEL.md](04-DATA-MODEL.md) §2) :

```text
Pour chaque source active :
  si la source a produit ≥ min_prior_activity annonces sur sa fenêtre historique
  et que ses empty_cycles_before_alert derniers runs ont raw_count == 0
  alors → alerte technique, priorité 3
          "leboncoin — 0 annonce depuis 3 cycles"
```

Trois précisions qui font la différence entre un garde-fou utile et une source de
bruit :

- Le compteur surveillé est `raw_count`, **pas** `qualified`. Une source peut
  légitimement ne rien remonter de qualifié pendant des jours ; qu'elle ne remonte
  plus rien **du tout** est anormal.
- La condition `min_prior_activity` évite d'alerter sur une source jamais activée.
- L'alerte est **désarmée** dès que la source repart, sans intervention.

Ce contrôle tourne après chaque cycle, dans le même processus. Il n'a pas besoin
d'être fiable à 100 % — il a besoin d'exister.
