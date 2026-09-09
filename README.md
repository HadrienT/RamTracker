# RamTracker

Agent de veille qui traque la DDR4 ECC sous-évaluée sur le marché de l'occasion
(eBay, Leboncoin, Reddit), la qualifie au €/Go et envoie une notification push
quand une annonce sort réellement du marché.

Cible matérielle : **Supermicro X10DRi-T4+** — 16 slots DIMM, DDR4 RDIMM/LRDIMM
2133 ou 2400. La carte accepte le DDR4-2133, qui est la bande la moins chère du
marché : c'est l'arbitrage que le projet exploite.

## Mise en route

```bash
uv sync --all-extras
cp .env.example .env          # renseigner EBAY_CLIENT_ID / SECRET / NTFY_URL
uv run ramtracker migrate
uv run ramtracker run-once --source ebay
uv run ramtracker loop        # ordonnanceur en continu (cadence + gigue par source)
uv run ramtracker status      # santé : sources muettes/en erreur, marché, alertes (code retour 1 si dégradé)
```

Tâches de développement dans le `justfile` : `just lint`, `just arch`,
`just test`, `just test-golden`, `just report`.

## Architecture

Six packages sous `src/ramtracker/`, contrats d'import vérifiés par `import-linter` :

| Package | Rôle |
|---|---|
| `core` | config, logging, erreurs, base SQLite, DTO, monnaie, hachage, horloge |
| `collect` | un collecteur par source → `RawListing` (eBay, Leboncoin, Reddit) |
| `extract` | cascade déterministe `RawListing` → `MemorySpec` ; repli LLM isolé dans `extract.llm` |
| `decide` | dédoublonnage, indice de marché glissant, double barrière, enchères |
| `notify` | rendu ntfy, anti-spam |
| `runtime` | ordonnanceur, disjoncteur par source, chien de garde inversé, CLI |

Le parseur (`extract`) se teste **hors ligne** contre le corpus doré
(`tests/fixtures/titles.jsonl`) : `just test-golden` affiche le taux de
résolution par étage. Aucun seuil de prix n'est écrit en dur — tout vit dans
`configs/thresholds.yaml` et se compare à l'indice glissant.

## Documentation

- **[blueprint/](blueprint/)** — la spécification d'implémentation normative.
  Commencer par [blueprint/README.md](blueprint/README.md) puis
  [blueprint/00-PRIMER.md](blueprint/00-PRIMER.md).
- **[docs/blueprint.html](docs/blueprint.html)** — le document narratif (le
  *pourquoi* des décisions). Non normatif.
- **[tools/charge_llm.py](tools/charge_llm.py)** — modèle d'entonnoir : charge
  réelle sur le serveur LLM local (partagé avec OpenHands).

## État

Implémentation des WP01→WP10 en place : collecte eBay/Leboncoin/Reddit, cascade
d'extraction (références constructeur + grammaire + cohérence + préfiltre + repli
LLM local), indice de marché, double barrière, notifications ntfy, ordonnanceur
avec disjoncteur et chien de garde inversé, boucle de rejeu et rapport
hebdomadaire, suppression de compte eBay (conformité RGPD/CCPA : Worker Cloudflare
gratuit + `ramtracker account-deletion-drain`).

Points marqués `[À CONFIRMER]` dans `configs/` et le code (id de catégorie eBay,
chemins JSON Leboncoin, en-têtes ntfy, `response_format` du serveur LLM, tables
de décodage Hynix/Micron) : à lever au **[WP00](blueprint/wp/WP00-reconnaissance.md)**
avec les spikes de `spikes/` et un vrai relevé de 150 titres pour le corpus doré
(le fichier livré est un corpus de départ à étendre).

Déploiement : `deploy/ramtracker.service` (systemd, `Type=simple`, tourne à côté
d'OpenHands) ou `deploy/docker-compose.yml`. La conformité RGPD/CCPA d'eBay est
assurée sans rien exposer depuis la maison : un Cloudflare Worker gratuit
(`deploy/worker/`, voir son README) accuse réception 24/7 et RamTracker tire la
file. `deploy/ramtracker-account-deletion.service` reste disponible pour un
auto-hébergement 24/7 optionnel.
