# WP06 — `runtime` (ordonnanceur, disjoncteur, chien de garde, déploiement)

> **Contexte** : les quatre packages métier de RamTracker fonctionnent. Ce WP les
> câble, les fait tourner tout seuls et — surtout — **détecte quand ils mentent**.
>
> Rappel du principe P3 : un scraper cassé ne lève pas d'erreur. Il remonte zéro
> annonce, et zéro annonce ressemble exactement à « le marché est calme ». Sans le
> chien de garde de ce WP, tout le reste peut tomber en silence pendant des mois.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[01-ARCHITECTURE.md](../01-ARCHITECTURE.md) · [05-SEQUENCES.md](../05-SEQUENCES.md) ·
[07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) · [06-CONFIG.md](../06-CONFIG.md) §3

**Dépend de** : WP03, WP05. **Bloque** : WP07 (voie différée), WP08, WP09.

---

## 1. Objectif

Faire tourner le système sans intervention, source par source, et alerter quand une
source se tait.

---

## 2. Modules & responsabilités

| Module | Responsabilité |
|---|---|
| `pipeline.py` | Câblage des huit étages, persistance, gestion d'erreur par étage |
| `scheduler.py` | Cadence par source, gigue |
| `breaker.py` | Disjoncteur par source, repli exponentiel |
| `watchdog.py` | Chien de garde inversé |
| `cli.py` | `run-once`, `backfill`, `replay`, `report` |

`pipeline.py` ne contient **aucune** règle métier : uniquement l'ordre des appels, la
persistance et le traitement des erreurs.

---

## 3. Contrats clés

### 3.1 Cadence par source

| Source | Intervalle | Gigue | Requêtes/cycle | Requêtes/jour | Quota |
|---|---|---|---|---|---|
| eBay | 10 min | ± 2 min | 4 | 576 | 11 % de 5 000 |
| Reddit | 15 min | ± 3 min | 1 | 96 | négligeable |
| Leboncoin | 75 min | ± 20 min | 1–2 | ≈ 24 | — |
| File LLM différée | 30 min | — | ≤ 1 | ≈ 2 | concurrence 1 |
| Recalcul de l'indice | 60 min | — | local | 24 | — |

La cadence est **par source**, pas globale. Sur eBay l'API autorise largement dix
minutes ; sur Leboncoin c'est la protection anti-bot qui contraint.

La gigue n'est pas de la superstition : un scan qui tombe exactement à la minute
ronde, quatorze fois par jour, est un motif que tout système de détection remarque.

### 3.2 Disjoncteur

```text
échec       → repli 15 min → 1 h → 4 h → 12 h (plafonné, avec gigue)
3 échecs    → disjoncteur OUVERT, alerte technique priorité 3
succès      → fermeture immédiate, compteur remis à zéro
```

Deux règles absolues :

- **Par source.** Leboncoin bloqué ne doit jamais empêcher eBay de tourner.
- **Aucune reprise immédiate** après un `SourceBlocked`. Une boucle de retry serrée
  transforme un blocage temporaire en blocage durable.

### 3.3 Le chien de garde inversé

**La fonctionnalité que tout le monde oublie et qui rend le reste inutile.**
Spécification complète en [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) §4.

```text
Pour chaque source active :
  si elle a produit ≥ min_prior_activity annonces sur sa fenêtre historique
  et que ses empty_cycles_before_alert derniers runs ont raw_count == 0
  alors → alerte technique priorité 3
```

Le compteur surveillé est `raw_count`, **pas** `qualified` : une source peut
légitimement ne rien remonter de qualifié pendant des jours ; qu'elle ne remonte plus
rien du tout est anormal. L'alerte se désarme seule au retour de la source.

### 3.4 Isolation des erreurs

Une source en échec n'interrompt jamais le cycle des autres. Chaque `run_source`
écrit sa ligne dans `source_runs`, **succès comme échec**, avec `error` renseigné.

### 3.5 Déploiement

Le plus simple qui marche : une unité `systemd` avec minuterie sur le serveur
lui-même, à côté d'OpenHands. Alternative `docker compose` à deux services
(l'application, et un ntfy auto-hébergé en option).

Sauvegarde quotidienne : `sqlite3 ramtracker.db ".backup …"`, sept jours de
rétention. **Jamais `cp`** — une copie d'une base en WAL pendant une écriture produit
un fichier incohérent.

---

## 4. Tests attendus

| Test | Attendu |
|---|---|
| Une source lève | les autres terminent leur cycle |
| `source_runs` | une ligne écrite même en échec, avec `error` |
| Disjoncteur | 3 échecs → ouvert ; succès → fermé immédiatement |
| Repli | séquence 15 min / 1 h / 4 h / 12 h respectée, plafonnée |
| Gigue | deux cycles consécutifs ne tombent pas au même offset |
| Chien de garde | source active puis 3 cycles vides → anomalie |
| Chien de garde | source jamais active → **aucune** anomalie |
| Chien de garde | `raw_count>0` mais `qualified=0` → **aucune** anomalie |
| Chien de garde | retour de la source → désarmement |
| `replay` | rejoue la cascade sur l'archive et affiche le différentiel |

Les trois tests négatifs du chien de garde valent autant que le positif : un garde-fou
qui crie à tort finit désactivé.

---

## 5. Critères d'acceptation

- [ ] Le système tourne **trois jours d'affilée** sans intervention.
- [ ] Il a prévenu au moins une fois qu'une source était tombée, lors d'un test
      provoqué (clé invalidée, ou URL détournée).
- [ ] Une source en disjoncteur ouvert n'empêche aucune autre de tourner.
- [ ] `source_runs` est renseignée à chaque cycle, succès comme échec.
- [ ] La sauvegarde quotidienne produit un fichier restaurable.
- [ ] `import-linter` : `runtime` est le seul package à importer les quatre métiers (D5).
- [ ] `mypy --strict` passe.
