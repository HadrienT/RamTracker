# WP02 — `extract` (parseur déterministe)

> **Contexte** : RamTracker collecte des annonces de mémoire serveur d'occasion et
> alerte quand le prix au gigaoctet est anormalement bas. Transformer
> « Lot de 4 barrettes 16Go DDR4 ECC REG 2133 » en spécification typée est **le seul
> problème réellement difficile** du projet : tout le reste est de la plomberie.
>
> Ce package est développé et testé **entièrement hors ligne**, contre le corpus doré
> produit par WP00. C'est le contrat **D8** : `extract` ne fait aucune I/O — ni
> réseau, ni fichier, ni base, ni horloge. C'est ce qui permet d'itérer dessus
> pendant que les collecteurs sont bloqués, et de faire tourner sa suite de tests en
> une seconde.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[03-INTERFACES.md](../03-INTERFACES.md) §4 · [08-TESTING.md](../08-TESTING.md) ·
[10-HARDWARE-TARGET.md](../10-HARDWARE-TARGET.md) · [09-CONVENTIONS.md](../09-CONVENTIONS.md) §3

**Dépend de** : WP00 (corpus + `compat.yaml`), WP01 (`core.models`).
**Bloque** : WP04. **Parallélisable avec** : WP03.

---

## 1. Objectif

Une cascade du plus déterministe au plus coûteux, qui s'arrête dès qu'elle est sûre,
et qui **ne devine jamais**. Un champ incertain vaut `None` et fait baisser la
confiance ; il ne prend pas une valeur plausible.

Le repli LLM (étage 5) et le préfiltre (étage 4) sont livrés par **WP07**. Ce WP
livre une cascade complète et fonctionnelle sans eux : `cascade.run` accepte
`llm=None`.

---

## 2. Modules & responsabilités

| Module | Étage | Responsabilité |
|---|---|---|
| `partnum.py` | 1 | Décodeur de références constructeur — confiance 1.0 |
| `grammar.py` | 2 | Grammaire d'expressions régulières — confiance 0.60 à 0.95 |
| `coherence.py` | 3 | Contrôles croisés, ajustement de confiance |
| `qualify.py` | — | Application de `compat.yaml`, remplissage de `reject_reason` |
| `cascade.py` | — | Orchestration, court-circuit sur confiance |

---

## 3. Contrats clés

### 3.1 Étage 1 — références constructeur

Le meilleur rapport effort/résultat du projet. Une référence est auto-descriptive :
capacité, rangs, fréquence et type sortent d'une table, sans traitement de langage.
Détail des tables en [10-HARDWARE-TARGET.md](../10-HARDWARE-TARGET.md) §4.

Appliquer la détection au titre **et** à la description. Les vendeurs professionnels
mettent souvent la référence dans le corps de l'annonce uniquement.

### 3.2 Étage 2 — grammaire

Extrait capacité, multiplicateur, type, fréquence, rangs et **base de prix**. Cas à
couvrir obligatoirement, avec leurs pièges, en [08-TESTING.md](../08-TESTING.md) §1.

Deux conventions de fréquence coexistent et doivent être unifiées :
`PC4-17000` = 2133, `PC4-19200` = 2400, `PC4-21300` = 2666.

`price_basis` est extrait ici. Les marqueurs `pièce`, `l'unité`, `chacune`,
`per stick`, `Stück` donnent `UNIT` ; leur absence associée à un multiplicateur
explicite donne `LOT` ; sinon `UNKNOWN`.

### 3.3 Étage 3 — cohérence

Chaque contrôle **ajuste la confiance**, aucun ne rejette :

| Contrôle | Effet si violé |
|---|---|
| `module_count × module_capacity_gb == total_gb` quand les deux sont annoncés | confiance → 0.30 |
| `module_capacity_gb ∈ {4, 8, 16, 32, 64, 128}` | confiance → 0.30 — souvent une fréquence lue comme capacité |
| Fréquence et code `PC4-*` concordants | confiance → 0.40 |
| `price_basis is UNKNOWN` | confiance plafonnée à 0.70 |

Le dernier est structurant : il garantit qu'une annonce dont la base de prix est
ambiguë ne peut jamais court-circuiter la cascade, et finira donc au LLM ou en
quarantaine plutôt qu'en alerte. C'est la contrepartie de l'interdit n°5 du primer.

### 3.4 Qualification

`qualify` applique `compat.yaml` et remplit `reject_reason` avec un identifiant
stable (`sodimm`, `ddr3`, `udimm_non_ecc`, `capacity_4gb`…). Ces motifs sont
persistés, comparés en test et servent à cibler un rejeu : les renommer casse
l'historique ([09-CONVENTIONS.md](../09-CONVENTIONS.md) §2).

### 3.5 Cascade

```text
partnum.decode  →  si trouvé : qualify, retour (confiance 1.0)
grammar.parse   →  coherence.check
si confiance ≥ min_confidence  :  qualify, retour
sinon si llm is not None       :  délégation (WP07)
sinon                          :  quarantaine (reject_reason="low_confidence")
```

Le seuil `min_confidence` vient de `thresholds.yaml`, jamais d'une constante.

---

## 4. Tests attendus

| Test | Attendu |
|---|---|
| Corpus doré complet | exactitude ≥ 85 % sur les qualifiées |
| Pièges `prix_unitaire` | **100 %** — aucun toléré |
| `M393A4K40BB1-CRC` | 32 Go, 2400, rdimm, confiance 1.0, méthode `part_number` |
| « 64 Go (4x16) » | `total_gb=64`, `module_count=4`, pas 256 |
| « 8x32GB … 256GB TOTAL » | cohérence validée, confiance haute |
| « DDR4 32GB ECC » | `module_count=1`, `price_basis=UNKNOWN`, confiance ≤ 0.70 |
| « PC4-19200 » | `speed_mts=2400` |
| « DDR4 2133 MHz — 8 Go » | `capacity=8`, pas 2133 |
| SODIMM déguisé | `reject_reason="sodimm"` |
| Invariant **I2** | aucune I/O : `socket`, `open`, `sqlite3.connect` remplacés par des doubles qui lèvent |
| `cascade.run(llm=None)` | quarantaine propre, aucune exception |

---

## 5. Critères d'acceptation

- [ ] Exactitude ≥ 85 % sur le corpus doré, **sans aucun accès réseau**.
- [ ] Aucun piège `prix_unitaire` mal interprété.
- [ ] Invariant I2 vérifié : `extract` ne fait aucune I/O.
- [ ] `import-linter` : `extract` n'importe ni `collect`, ni `decide`, ni `notify` (D2, D3).
- [ ] `just test-golden` affiche le tableau de résolution par étage de
      [08-TESTING.md](../08-TESTING.md) §4.
- [ ] Tous les motifs de rejet sont documentés dans `qualify.py` et stables.
- [ ] `mypy --strict` passe.
