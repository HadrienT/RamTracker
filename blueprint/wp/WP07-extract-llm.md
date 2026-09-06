# WP07 — `extract.llm` (préfiltre admissible + repli LLM local)

> **Contexte** : la cascade de WP02 met en quarantaine les annonces qu'elle ne
> tranche pas. Ce WP les résout, en s'appuyant sur le **serveur LLM local qui sert
> déjà OpenHands**.
>
> Le point à comprendre avant de coder : **le problème n'est pas le débit, c'est la
> collision**. Après préfiltrage, le LLM voit environ 8 annonces par jour, soit
> ~2 appels en lots de 4, soit **11 à 23 secondes de GPU par jour**. Le seul risque
> réel est qu'un de ces deux appels tombe pendant une boucle agentique d'OpenHands.
> Ce n'est pas un problème de dimensionnement, c'est un problème d'ordonnancement.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) §2 (P4) et §5 ·
[03-INTERFACES.md](../03-INTERFACES.md) §4 · [05-SEQUENCES.md](../05-SEQUENCES.md) §2 ·
[06-CONFIG.md](../06-CONFIG.md) §4 · `../../tools/charge_llm.py`

**Dépend de** : WP02. La voie différée nécessite WP06.
**Parallélisable avec** : WP08.

---

## 1. Objectif

Deux choses, dans cet ordre : un **préfiltre gratuit** qui écarte ce qui ne peut pas
être une affaire, puis un **repli LLM** qui ne voit que le résidu.

---

## 2. L'entonnoir

```text
nouvelles annonces / jour                195
  après cache de specs (spec_hash)       172
  après rejet par mots-clés               94
  après parseur à règles                  21
  après préfiltre €/Go admissible          8   ← ce que le LLM voit
```

Chaque étage est gratuit. `tools/charge_llm.py` recalcule ce tableau : réajuster les
hypothèses de volume en tête de fichier une fois les premières mesures disponibles.

---

## 3. Le préfiltre — surtout pas sur le prix

Filtrer sur le prix absolu est le réflexe évident, et il est **faux** : un lot à
1 800 € peut être 512 Go à 3,50 €/Go, c'est-à-dire exactement la cible. Un plafond de
prix ferait rater les meilleures affaires, qui sont justement les gros lots. Et on ne
peut pas filtrer sur le €/Go, puisqu'il faut la capacité — ce que le parseur produit.

La sortie est une **borne inférieure admissible du €/Go** : on calcule par expression
régulière la capacité *maximale plausible*, donc le €/Go *minimal possible*.

```text
optimistic_total_gb  = max(capacités détectées) × max(multiplicateurs détectés)
best_case_eur_per_gb = prix_total / optimistic_total_gb
si best_case > hard_ceiling → rejet "meilleur_cas_hors_seuil", sans appel LLM
```

**La propriété qui compte** : la capacité réelle ne peut qu'être inférieure ou égale à
la borne, donc le €/Go réel ne peut qu'être supérieur ou égal au meilleur cas. Si même
le meilleur cas dépasse la barrière, l'annonce n'est une affaire sous **aucun**
parsing possible. **Zéro faux négatif par construction** — c'est l'invariant **I1**.

La fonction retourne `None` quand elle ne peut rien borner ; dans ce cas on ne
préfiltre pas. Elle doit être **délibérément généreuse** : `« 512GB TOTAL (16x32GB) »`
donne une borne absurdement haute, donc laisse passer. C'est le comportement voulu —
le filtre n'écarte que ce dont il est certain.

---

## 4. Le LLM local

### 4.1 Contention avec OpenHands

`concurrency = 1` côté RamTracker, sans exception. Les appels sont **différables par
conception** : une annonce part au LLM précisément parce qu'elle est ambiguë, donc
qu'elle n'est pas une évidence.

| Voie | Déclencheur | Comportement |
|---|---|---|
| **urgente** | `best_case < urgent_lane_margin × hard_ceiling` | Tentative immédiate, timeout court, **repli sur l'API distante** si le serveur local est occupé. Quelques fois par semaine |
| **différée** | tout le reste | File vidée toutes les 30 min, **tour sauté** si le serveur est occupé |

Détection d'occupation : `[À CONFIRMER]` — sur llama.cpp, `/health` renvoie 503 quand
tous les slots sont pris ; sous vLLM, `vllm:num_requests_running` sur `/metrics`.

### 4.2 Faut-il un second slot de parallélisme ?

**Recommandation : non.** Sur llama.cpp, `--parallel 2` divise `-c` par deux, donc
ampute le contexte d'OpenHands en permanence ; le compenser exige de doubler `-c`,
et le cache KV se paie comptant :

```text
octets/token = 2 × n_layers × n_kv_heads × head_dim × octets_par_élément

modèle              KB/tok   32k ctx   64k ctx   (fp16)
~8B  (32L, 8KV)        128     4,0 Go    8,0 Go
~32B (64L, 8KV)        256     8,0 Go   16,0 Go
~70B (80L, 8KV)        320    10,0 Go   20,0 Go
```

Payer 4 à 16 Go de VRAM en permanence pour servir vingt secondes de travail par jour
est un mauvais échange. Rester en `--parallel 1` et faire la queue.

| Serveur | Si un 2ᵉ slot est malgré tout voulu | Le piège |
|---|---|---|
| **vLLM** | **rien à faire** — continuous batching déjà parallèle, pool KV partagé | — |
| **llama.cpp** | `--parallel 2` **et** doubler `-c` | Sans doubler `-c`, OpenHands perd la moitié de son contexte |
| **Ollama** | `OLLAMA_NUM_PARALLEL=2` | Multiplie la VRAM du KV au lieu de diviser le contexte |

### 4.3 Décodage contraint — non négociable

Avec un modèle local, espérer du JSON valide en le demandant poliment est une perte
de temps. Le décodage contraint garantit une sortie conforme au schéma et rend un
petit modèle parfaitement fiable sur cette tâche précise.

`[À CONFIRMER]` selon le serveur : `response_format: {type:"json_schema", …}` ou
grammaire GBNF sur llama.cpp ; `guided_json` sur vLLM ; `format` sur Ollama.

### 4.4 Le prompt

Règles à énoncer explicitement, parce que ce sont celles que le modèle enfreint :

```text
- Ne devine jamais. Un champ incertain vaut null.
- price_basis="unit" si le prix affiché est celui d'UN module
  ("pièce", "l'unité", "chacune", "per stick", "Stück"). "lot" sinon. Sinon "unknown".
- module_count = nombre de modules VENDUS, pas le nombre disponible en stock.
- "REG"/"Registered"/"RDIMM" => rdimm. "LR"/"LRDIMM" => lrdimm.
- PC4-17000=2133, PC4-19200=2400, PC4-21300=2666.
```

---

## 5. Tests attendus

| Test | Attendu |
|---|---|
| Invariant **I1**, exhaustif sur le corpus doré | `optimistic_total_gb ≥ total_gb réel`, sans exception |
| Invariant **I1**, `hypothesis` | idem sur titres générés |
| « DDR4 ECC 16GB — 180 € » | rejet `meilleur_cas_hors_seuil`, aucun appel LLM |
| « 512GB TOTAL (16x32GB) » | borne généreuse, **laisse passer** |
| Texte sans capacité détectable | `None`, aucun préfiltrage |
| Sortie LLM non conforme au schéma | rejetée, quarantaine, jamais d'alerte |
| Serveur local indisponible, voie urgente | repli distant emprunté |
| Serveur local indisponible, voie différée | remise en file, aucun repli distant |
| Serveur occupé | tour sauté, `attempts` incrémenté |
| Concurrence | jamais plus d'un appel simultané |

---

## 6. Critères d'acceptation

- [ ] L'invariant I1 est couvert exhaustivement **et** par test de propriété.
- [ ] Aucun appel LLM n'est émis pour une annonce écartée par le préfiltre.
- [ ] La concurrence côté RamTracker ne dépasse jamais 1, vérifié sous charge simulée.
- [ ] Le décodage est contraint par schéma ; une sortie non conforme part en
      quarantaine plutôt qu'en alerte.
- [ ] Le repli distant n'est **jamais** emprunté par la voie différée.
- [ ] `import-linter` : `extract.llm` est le **seul** module de `extract` autorisé à
      faire de l'I/O (exception documentée au contrat D8).
- [ ] `mypy --strict` passe.
