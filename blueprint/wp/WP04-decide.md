# WP04 — `decide` (dédoublonnage, indice, seuils, enchères)

> **Contexte** : RamTracker qualifie des annonces de mémoire serveur et doit décider
> lesquelles méritent de réveiller quelqu'un. C'est ici que vit la règle du projet la
> plus facile à mal faire : **aucun seuil de prix n'est écrit en dur**.
>
> Le marché DDR4 a bougé de 30 à 50 % en un an. Un seuil absolu figé aujourd'hui sera
> soit muet, soit hurlant dans trois mois, et personne ne s'en apercevra. Les
> décisions se prennent contre un **indice glissant** calculé sur les propres
> observations du système.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[03-INTERFACES.md](../03-INTERFACES.md) §5 · [04-DATA-MODEL.md](../04-DATA-MODEL.md) ·
[06-CONFIG.md](../06-CONFIG.md) §4 · [08-TESTING.md](../08-TESTING.md) §2

**Dépend de** : WP02, WP03. **Bloque** : WP05.

---

## 1. Objectif

Transformer une `MemorySpec` qualifiée et son `RawListing` en `Deal`, ou en `None`.
`decide` décide **s'il faut** alerter et avec quelle urgence ; il n'envoie rien et ne
formate rien.

---

## 2. Modules & responsabilités

| Module | Responsabilité |
|---|---|
| `dedupe.py` | Les trois identités, détection de baisse de prix |
| `market.py` | Indice glissant p25/p50/p75 par compartiment de capacité |
| `thresholds.py` | Double barrière, garde-fous, mode observation |
| `auction.py` | Porte temporelle, `max_bid`, notification unique |

---

## 3. Contrats clés

### 3.1 Les trois identités

Détail en [04-DATA-MODEL.md](../04-DATA-MODEL.md) §1. Le point à ne pas rater :
l'extraction est mise en cache sur le **texte** (`spec_hash`), pas sur l'annonce. Un
vendeur qui supprime et republie obtient un nouvel identifiant mais garde son texte —
donc zéro retraitement, et zéro appel LLM.

### 3.2 L'indice de marché

```text
market_ref[capacité] = p50( eur_per_gb des annonces QUALIFIÉES
                            de même compartiment, fenêtre 30 jours,
                            toutes sources confondues )
discount = 1 − (eur_per_gb / market_ref)
```

Recalculé toutes les heures et persisté dans `market_stats` avec son `sample_size`.
Seules les annonces **qualifiées** entrent dans l'indice : inclure les rejets le
tirerait vers des valeurs sans rapport.

### 3.3 La double barrière

Une alerte n'est émise que si **les deux** conditions sont vraies :

| Barrière | Condition | Ce dont elle protège |
|---|---|---|
| **Absolue** | `eur_per_gb < hard_ceiling` | Un marché globalement cher : une décote de 40 % sur un marché à 12 €/Go reste une mauvaise affaire |
| **Relative** | `discount > min_discount` | Un marché qui monte : sans elle, le plafond dur finirait par ne plus jamais se déclencher, **en silence** |

### 3.4 Ordre d'application — normatif

L'ordre exact est spécifié en [03-INTERFACES.md](../03-INTERFACES.md) §5 et ne doit
pas être réarrangé. Les trois premières règles sont des garde-fous, pas des filtres :

1. Spec rejetée → `None`.
2. `price_basis is UNKNOWN` et `method is not LLM` → `None` (interdit n°5 du primer).
3. `eur_per_gb < plausibility_floor` (0,50 €/Go) → `None` **et renvoi au LLM**. Un
   prix aussi bas est un bug de parsing sur la base de prix, jamais une aubaine.
4. `total_gb < min_total_gb` → `None`. Un module isolé de 8 Go à 2 €/Go est une bonne
   affaire arithmétique et un mauvais achat : il occupe un slot pour peu de capacité.
5. Barrière absolue, puis relative.
6. Enchère → `auction.gate`.

### 3.5 Mode observation

Pendant les 14 premiers jours (`observation_mode.until`, une **date**, pas un
booléen), ou tant que `sample_size < min_sample_size` : la barrière relative est
ignorée, seule l'absolue s'applique, et un récapitulatif quotidien liste ce qui
*aurait* été notifié. C'est la phase de calibrage réelle des seuils.

### 3.6 Enchères

Le prix d'une enchère à J−6 ne veut rien dire : une barrette à 5 € six jours avant la
clôture n'est pas une affaire à 0,15 €/Go, c'est une enchère qui n'a pas commencé.
Notifier là-dessus dresse à ignorer l'application.

```text
reste > gate_minutes (90)   →  WATCH   : liste de veille, AUCUNE notification
reste ≤ gate_minutes        →  évaluer sur (cote + bid_increment)
                               sous les deux barrières → QUIET (priorité 2, muette)
max_bid = (hard_ceiling × total_gb) − port_estimé
```

Deux règles d'exploitation :

- Une enchère entrée dans la fenêtre n'est notifiée **qu'une fois** — sinon l'alerte
  se répète à chaque cycle pendant une heure et demie.
- Une enchère en veille dont le prix **monte** au-dessus du seuil sort de la liste
  **silencieusement**. On ne notifie jamais une non-affaire.

---

## 4. Tests attendus

| Test | Attendu |
|---|---|
| Invariant **I3** | `price_basis=UNKNOWN` + `method≠LLM` → jamais de `Deal` |
| Invariant **I4** | `eur_per_gb < 0.50` → jamais `IMMEDIATE` |
| Invariant **I7** | enchère à J−6 → `WATCH`, aucune notification |
| Barrière absolue seule | décote 40 % sur marché cher → pas d'alerte |
| Barrière relative seule | sous le plafond mais marché encore moins cher → pas d'alerte |
| Mode observation actif | barrière relative ignorée, récapitulatif produit |
| `sample_size` insuffisant | bascule automatique en mode observation |
| Indice | monotone ; robuste à un échantillon vide |
| `max_bid` | 4×16 Go @ 2,50 €/Go, port 9 € → 151 € |
| Enchère notifiée deux fois | refusée à la seconde |
| Enchère dont le prix monte | sortie de veille, aucune notification |
| Baisse de prix > 10 % | ré-évaluation autorisée |

---

## 5. Critères d'acceptation

- [ ] **Aucun seuil numérique dans le code** : tout vient de `thresholds.yaml`.
- [ ] Les invariants I3, I4 et I7 sont couverts et passent.
- [ ] `ramtracker replay --since …` sur l'historique archivé produit une liste
      d'affaires jugée pertinente à la lecture humaine.
- [ ] Le mode observation se désactive tout seul à la date configurée.
- [ ] `import-linter` : `decide` n'importe ni `collect` ni `notify` (D4).
- [ ] `mypy --strict` passe.
