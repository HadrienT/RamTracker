# RamTracker

Agent de veille qui traque la DDR4 ECC sous-évaluée sur le marché de l'occasion
(eBay, Leboncoin, Reddit), la qualifie au €/Go et envoie une notification push
quand une annonce sort réellement du marché.

Cible matérielle : **Supermicro X10DRi-T4+** — 16 slots DIMM, DDR4 RDIMM/LRDIMM
2133 ou 2400. La carte accepte le DDR4-2133, qui est la bande la moins chère du
marché : c'est l'arbitrage que le projet exploite.

## Documentation

- **[docs/blueprint.html](docs/blueprint.html)** — le blueprint d'architecture complet :
  matrice de compatibilité, décisions structurantes (ADR-1 à 7), pipeline,
  sources, parseur, dimensionnement du LLM, seuils, politique d'enchères,
  plan de développement et graphe de dépendances.
  Version publiée : <https://claude.ai/code/artifact/bb525b9c-beca-45dc-bfbe-c6a65f8d908d>

- **[tools/charge_llm.py](tools/charge_llm.py)** — modèle d'entonnoir qui chiffre la
  charge réelle imposée au serveur LLM local (partagé avec OpenHands) et le coût
  VRAM d'un second slot de parallélisme. Hypothèses de volume en tête de fichier,
  à réajuster une fois les premières mesures disponibles.

  ```
  python3 tools/charge_llm.py
  ```

## État

Blueprint terminé, implémentation non commencée. Prochaine étape : **phase P0**
(matrice de compatibilité `compat.yaml`, corpus doré de 150 annonces étiquetées,
trois spikes de reconnaissance, création des comptes et clés).

Le jalon visé est **P5 en 8 à 9 soirées** : eBay comme unique source, sans repli
LLM, et une vraie notification sur le téléphone. Leboncoin et l'extraction LLM
viennent ensuite améliorer un système qui fonctionne déjà.
