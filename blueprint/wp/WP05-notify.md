# WP05 — `notify` (ntfy, gabarits, anti-spam)

> **Contexte** : RamTracker a décidé qu'une annonce mérite une alerte (WP04). Ce
> package décide **comment** elle est rendue et **si le quota autorise l'envoi**.
>
> La séparation avec `decide` n'est pas cosmétique : les deux échouent pour des
> raisons différentes, et un agent de veille qui notifie trop est un agent de veille
> qu'on désactive au bout de trois jours.
>
> **C'est le WP qui rend le système réel** : à sa livraison, le téléphone sonne pour
> une vraie annonce.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[03-INTERFACES.md](../03-INTERFACES.md) §6 · [06-CONFIG.md](../06-CONFIG.md) §4 ·
[04-DATA-MODEL.md](../04-DATA-MODEL.md) §2

**Dépend de** : WP04. **Bloque** : WP06.

---

## 1. Objectif

Rendre un `Deal` en notification lisible d'un coup d'œil, et ne l'envoyer que si les
règles de débit l'autorisent.

---

## 2. Modules & responsabilités

| Module | Responsabilité |
|---|---|
| `base.py` | `Protocol Notifier`, `Notification`, `Action` |
| `ntfy.py` | Implémentation ntfy — deux priorités, boutons d'action |
| `templates.py` | Rendu achat immédiat / enchère |
| `ratelimit.py` | Cooldown, plafond quotidien, silence nocturne |

---

## 3. Contrats clés

### 3.1 Deux niveaux, pas cinq

| Urgence | Priorité | Son | Contenu spécifique |
|---|---|---|---|
| `IMMEDIATE` (achat) | 5 | oui | €/Go, décote, bouton « Ouvrir l'annonce » |
| `QUIET` (enchère) | 2 | non | cote actuelle, temps restant, **`max_bid`** |

La notification d'enchère porte une information que celle d'achat n'a pas besoin de
porter : **le plafond à ne pas dépasser**. Sans lui, l'alerte oblige à refaire le
calcul sur le téléphone, au moment où il reste dix minutes.

### 3.2 Contenu

Le titre doit se lire sans ouvrir la notification. Ce qui compte, dans l'ordre :
le **€/Go**, la **décote**, la **capacité totale**, la source.

```text
titre  2,10 €/Go — 34 % sous le marché
corps  4 × 32 Go RDIMM 2400 · 128 Go
       269 € + 9 € port · leboncoin · Lyon
       réf. M393A4K40BB1-CRC
```

`[À CONFIRMER]` — les noms exacts des en-têtes ntfy (`X-Title`, `X-Priority`,
`X-Tags`, `X-Click`, `X-Actions`) sont à vérifier dans la documentation officielle au
moment du codage.

### 3.3 L'anti-spam — obligatoire dès le premier jour

| Règle | Effet |
|---|---|
| Une alerte par `fingerprint` | Survit à une republication sous un nouvel identifiant |
| Re-alerte à la baisse seulement | Prix en baisse de plus de `re_alert_min_drop_pct` |
| Plafond quotidien (6) | Au-delà, bascule en récapitulatif |
| Silence nocturne 23 h → 7 h | Priorité 5 ramenée à 3 |

Le plafond quotidien mérite une justification : si six affaires se déclenchent le
même jour, c'est le **seuil qui est mal réglé**, pas le marché qui s'écroule. Basculer
en récapitulatif protège la crédibilité du canal.

Toute suppression émet `notify.suppressed` avec son motif
([07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) §3). Sans cet événement, il
est impossible de distinguer « rien d'intéressant » de « l'anti-spam a tout mangé ».

### 3.4 Le bouton « Ignorer 24 h »

Il pointe vers un point d'entrée HTTP livré en **WP09**. Tant que WP09 n'existe pas,
l'action n'est pas incluse dans la notification — pas de bouton mort.

---

## 4. Tests attendus

| Test | Attendu |
|---|---|
| `IMMEDIATE` | priorité 5, bouton d'ouverture présent |
| `QUIET` | priorité 2, `max_bid` présent dans le corps |
| Invariant **I5** | une empreinte → une alerte ; deuxième refusée |
| Baisse > 10 % | re-alerte autorisée |
| Baisse < 10 % | re-alerte refusée |
| 7ᵉ alerte urgente du jour | supprimée, `notify.suppressed` émis |
| 23 h 30 | priorité 5 ramenée à 3 |
| Échec d'envoi | une reprise, puis `NotifyError` journalisée en `ERROR` |
| Champs obligatoires | présents quel que soit le gabarit |

On teste que les champs obligatoires sont présents et que la priorité correspond à
l'urgence — **pas** la formulation exacte du message.

---

## 5. Critères d'acceptation

- [ ] **Le téléphone sonne pour une vraie annonce eBay.** Le système existe.
- [ ] L'invariant I5 est couvert et passe.
- [ ] Aucune notification d'enchère ne part sans `max_bid`.
- [ ] Toute suppression émet `notify.suppressed` avec un motif.
- [ ] L'URL du sujet ntfy n'apparaît dans aucun log.
- [ ] `import-linter` : `notify` n'importe que `core` (D2).
- [ ] `mypy --strict` passe.
