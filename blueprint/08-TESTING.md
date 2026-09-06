# 08 — Stratégie de test

> Prérequis : [00-PRIMER.md](00-PRIMER.md) · [03-INTERFACES.md](03-INTERFACES.md)
>
> **À lire avant de coder quoi que ce soit.**

---

## 1. Le corpus doré

C'est la pièce maîtresse du projet, et l'étape la plus ingrate. `tests/fixtures/titles.jsonl`
contient **150 titres réels** relevés à la main sur les trois sources, étiquetés avec
la spec attendue, dont **au moins 40 pièges**.

```jsonl
{"text":"Lot de 4 barrettes 16Go DDR4 ECC REG Samsung 2133","trap":"reg_seul_indice_rdimm",
 "expect":{"module_capacity_gb":16,"module_count":4,"total_gb":64,"kind":"rdimm",
           "speed_mts":2133,"price_basis":"lot"}}
{"text":"16 Go DDR4 ECC REG - 25 EUR piece, j'en ai 8","trap":"prix_unitaire",
 "expect":{"module_capacity_gb":16,"module_count":8,"price_basis":"unit"}}
{"text":"DDR4 32GB ECC Samsung","trap":"kit_ou_module",
 "expect":{"module_capacity_gb":32,"module_count":1,"price_basis":"unknown"}}
```

Typologie de pièges à couvrir obligatoirement :

| Piège | Exemple | Ce qui se casse sans lui |
|---|---|---|
| `prix_unitaire` | « 25 € pièce, j'en ai 8 » | €/Go divisé par 8 → **fausse alerte urgente** |
| `total_et_decompose` | « 64 Go (4x16) » | Double comptage → 256 Go au lieu de 64 |
| `kit_ou_module` | « DDR4 32GB ECC » | Ambiguïté non détectée, confiance surévaluée |
| `code_pc4` | « PC4-19200 » | Fréquence non résolue (= 2400) |
| `ordre_inverse` | « DDR4 2133 MHz — 8 Go » | 2133 lu comme capacité |
| `reg_seul_indice_rdimm` | « ECC REG » sans « RDIMM » | Qualifié `unknown`, donc écarté à tort |
| `sodimm_deguise` | « DDR4 ECC 16 Go » (SODIMM) | Achat incompatible |
| `reference_constructeur` | « M393A4K40BB1-CRC » | Étage 1 raté, appel LLM inutile |

Le corpus est **figé**. On y ajoute (notamment depuis la quarantaine, cf. WP09), on
n'en retire jamais une entrée pour faire passer un test.

---

## 2. Invariants

Ce sont des propriétés du système, pas des cas de test. Chacun a son test dédié dans
`tests/test_invariants.py` et ne doit jamais être désactivé.

| # | Invariant | Comment il est vérifié |
|---|---|---|
| **I1** | `optimistic_total_gb(texte) >= total_gb réel` pour toute annonce | Exhaustif sur le corpus doré + `hypothesis` sur des titres générés. **C'est ce qui garantit zéro faux négatif au préfiltre.** |
| **I2** | `extract` (hors `extract.llm`) ne fait aucune I/O | `socket.socket`, `open` et `sqlite3.connect` remplacés par des doubles qui lèvent |
| **I3** | Aucune alerte si `price_basis is UNKNOWN` et `method is not LLM` | Test sur `decide.evaluate` |
| **I4** | `eur_per_gb < plausibility_floor` ⇒ jamais `urgency IMMEDIATE` | Test sur `decide.evaluate` |
| **I5** | Une empreinte ne produit qu'une alerte, sauf baisse > `re_alert_min_drop_pct` | Test sur `notify.ratelimit` |
| **I6** | `shipping=None` et `shipping=0` produisent des `total_cost` différents | Test sur `core.money` |
| **I7** | Une enchère hors de la fenêtre de fin ne produit jamais de notification | Test sur `decide.auction` |

I1 mérite un mot. Le préfiltre n'a le droit d'exister **que** parce qu'il ne peut pas
écarter une vraie affaire. Si I1 tombe, le préfiltre devient un filtre à faux
négatifs silencieux — exactement le genre de panne que le principe P3 interdit.

---

## 3. Catégories de tests

| Marqueur | Portée | Réseau | Doit tourner en |
|---|---|---|---|
| *(aucun)* | Unitaire, un module | non | < 1 s au total |
| `@pytest.mark.golden` | Cascade complète contre `titles.jsonl` | non | < 2 s |
| `@pytest.mark.contract` | Collecteurs contre charges utiles figées | non | < 3 s |
| `@pytest.mark.property` | `hypothesis` sur I1 et la grammaire | non | < 10 s |
| `@pytest.mark.live` | Appels réels aux API | **oui** | exclu de la CI |

**La CI ne touche jamais au réseau.** Les tests de collecteurs rejouent des réponses
réelles capturées pendant le spike WP00 et stockées dans `tests/fixtures/payloads/`.
Les tests `live` s'exécutent à la main, avant un déploiement.

---

## 4. Métrique de progression du parseur

`just test-golden` affiche le taux de résolution **par étage** :

```text
corpus : 150 annonces
  étage 1 — référence constructeur   34  (22,7 %)
  étage 2 — grammaire                84  (56,0 %)
  étage 3 — cohérence (ajustements)  12
  étage 4 — préfiltre (écartées)     19  (12,7 %)
  étage 5 — LLM                      11  (7,3 %)
  quarantaine                         2  (1,3 %)
  ── exactitude sur les qualifiées : 96,4 %
```

C'est le tableau de bord du projet. Quand une règle est ajoutée, on voit
immédiatement combien d'annonces passent de l'étage 5 à l'étage 2 — c'est-à-dire
combien de secondes de GPU et de latence viennent d'être économisées.

**Seuil de sortie de WP02** : exactitude ≥ 85 % sans aucun appel réseau, et **aucun**
piège `prix_unitaire` mal interprété — celui-là est bloquant à 100 %.

---

## 5. Ce qu'on ne teste pas

- Le rendu exact des gabarits de notification. On teste que les champs obligatoires
  sont présents et que la priorité correspond à l'urgence, pas la formulation.
- Les valeurs de l'indice de marché dans l'absolu. On teste la **monotonie** et le
  comportement en échantillon insuffisant.
- Les bibliothèques tierces.

---

## 6. CI

```yaml
# .github/workflows/ci.yml — esquisse
- uv sync
- just lint          # ruff + mypy --strict
- just arch          # import-linter, contrats D1→D8
- just test          # tout sauf @live
```

`just arch` n'est pas optionnel : c'est le seul garde-fou qui empêche `extract`
d'acquérir discrètement une dépendance réseau et de rendre le corpus doré inutile.
