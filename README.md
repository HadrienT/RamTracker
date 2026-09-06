# RamTracker

Agent de veille qui traque la DDR4 ECC sous-évaluée sur le marché de l'occasion
(eBay, Leboncoin, Reddit), la qualifie au €/Go et envoie une notification push
quand une annonce sort réellement du marché.

Cible matérielle : **Supermicro X10DRi-T4+** — 16 slots DIMM, DDR4 RDIMM/LRDIMM
2133 ou 2400. La carte accepte le DDR4-2133, qui est la bande la moins chère du
marché : c'est l'arbitrage que le projet exploite.

## Documentation

- **[blueprint/](blueprint/)** — la **spécification d'implémentation**, normative.
  Écrite pour être lue par des agents de code sans contexte préalable. Douze
  documents transverses (`00-PRIMER` → `10-HARDWARE-TARGET`) et dix work packages
  autonomes dans `blueprint/wp/`. Commencer par
  [blueprint/README.md](blueprint/README.md), puis
  [blueprint/00-PRIMER.md](blueprint/00-PRIMER.md).

- **[docs/blueprint.html](docs/blueprint.html)** — le document **narratif** : le
  *pourquoi* des décisions (analyse de marché, arbitrages, chiffrages).
  Non normatif. Version publiée :
  <https://claude.ai/code/artifact/bb525b9c-beca-45dc-bfbe-c6a65f8d908d>

- **[tools/charge_llm.py](tools/charge_llm.py)** — modèle d'entonnoir qui chiffre la
  charge réelle imposée au serveur LLM local (partagé avec OpenHands) et le coût
  VRAM d'un second slot de parallélisme.

  ```
  python3 tools/charge_llm.py
  ```

## État

Blueprint terminé, implémentation non commencée.

**Prochaine étape : [WP00](blueprint/wp/WP00-reconnaissance.md)** — `compat.yaml`,
corpus doré de 150 annonces étiquetées, trois spikes de reconnaissance, comptes et
clés. Il ne produit aucun code de production mais bloque tout le reste.

Chemin critique jusqu'à la première notification réelle :
`WP00 → WP01 → WP02 → WP03 → WP04 → WP05`. À ce stade, eBay seul, sans LLM, et le
téléphone sonne. Leboncoin (WP08) et l'extraction LLM (WP07) viennent ensuite
améliorer un système qui fonctionne déjà.
