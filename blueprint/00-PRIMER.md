# 00 — PRIMER (à lire par tout agent, sans exception)

> Ce fichier est le **contexte minimal complet**. Vous n'avez pas besoin de lire
> `../docs/blueprint.html`. Durée de lecture : ~4 minutes.

---

## 1. Ce qu'on construit

Un **agent de veille sur le marché de la mémoire serveur d'occasion**. Il collecte
les annonces récentes sur plusieurs places de marché, en extrait des spécifications
mémoire structurées, calcule un prix au gigaoctet, et notifie sur téléphone quand
une annonce est réellement sous-évaluée.

La machine cible est un **Supermicro X10DRi-T4+** : 16 slots DIMM, DDR4 **RDIMM ou
LRDIMM**, 2133 ou 2400 MT/s. Détail en [10-HARDWARE-TARGET.md](10-HARDWARE-TARGET.md).

L'intérêt du projet tient à un arbitrage précis : la carte accepte le **DDR4-2133**,
qui est la bande la moins chère du marché parce que plus personne n'en veut, alors
que la machine ferait tourner n'importe quelle barrette à cette fréquence de toute
façon. Acheter plus rapide est un surcoût pur.

On ne construit **pas** un comparateur de prix, ni un outil d'achat automatique.
Le système notifie ; l'humain décide et achète.

## 2. Les 4 principes non négociables

**(P1) Le parseur est le produit, pas le scraper.**
Transformer un titre d'annonce en spécification typée est le seul problème
difficile. Il se développe et se teste **hors ligne**, sur un corpus figé, sans
aucun accès réseau. Le reste est de la plomberie.

**(P2) Aucun seuil de prix n'est écrit en dur.**
Le marché DDR4 a bougé de 30 à 50 % en un an. Un seuil absolu figé aujourd'hui sera
soit muet, soit hurlant dans trois mois, **et personne ne s'en apercevra**. Les
décisions se prennent contre un indice de marché glissant calculé sur les propres
observations du système.

**(P3) Une panne silencieuse est pire qu'un crash.**
Un scraper qui casse ne lève pas d'erreur : il remonte zéro annonce, et zéro annonce
ressemble exactement à « le marché est calme ». Tout étage qui peut se taire doit
être surveillé par un compteur, et l'absence de résultat doit déclencher une alerte
technique. Voir [07-ERRORS-AND-LOGGING.md](07-ERRORS-AND-LOGGING.md) §4.

**(P4) Le LLM est une ressource partagée et contrainte.**
Le serveur d'inférence local sert déjà OpenHands en agentique. RamTracker s'y greffe
en second, jamais en priorité. Le dimensionnement se raisonne en **contention**, pas
en coût mensuel ni en débit.

## 3. Ce qu'on ne construit PAS

- Pas de framework de scraping générique. Quatre collecteurs concrets derrière une
  interface de trois lignes.
- Pas d'ORM, pas de broker de messages, pas de conteneur d'injection de dépendances.
  Un fichier SQLite et un processus.
- Pas de moteur de règles configurable. La qualification est du code Python testé
  contre un corpus.
- Pas d'agent LLM. Le LLM est appelé pour une extraction structurée, en un coup,
  sans boucle ni outils.
- Pas d'interface web au-delà d'un point d'entrée HTTP minimal pour les boutons
  d'action des notifications (WP09).

## 4. Décisions verrouillées (ne pas rediscuter)

| Sujet | Décision |
|---|---|
| Langage | Python 3.13, typé, `uv` pour les dépendances |
| Base de données | **SQLite**, mode WAL, un fichier. Pas de PostgreSQL |
| Processus | **un seul**, ordonnanceur en processus. Pas de Celery, pas de Redis |
| Client HTTP | `httpx` pour les API, `curl_cffi` pour Leboncoin |
| Navigateur headless | **plan B uniquement** — jamais le défaut (voir §5.6) |
| Validation | `pydantic` v2 pour tous les DTO et la configuration |
| Journalisation | `structlog`, sortie JSON |
| Notifications | **ntfy** (hébergé ou auto-hébergé), deux niveaux de priorité |
| Source n°1 | **eBay Browse API** — officielle, 5 000 appels/jour, sans Partner Network |
| Inférence LLM | serveur **local** partagé avec OpenHands, endpoint compatible OpenAI |
| Décodage LLM | **contraint par schéma**, jamais du JSON en espérant |
| Concurrence LLM | **1**, côté RamTracker. OpenHands reste prioritaire |
| Repli LLM distant | API Anthropic, **voie urgente uniquement** |
| Monnaie | `Decimal`, jamais `float` |
| Horodatages | `datetime` **aware UTC** partout |
| Déploiement | `systemd` + minuterie, ou `docker compose`, sur le serveur lui-même |

## 5. Interdits absolus

1. **Écrire un seuil de prix en dur dans le code.** Ils vivent en configuration et se
   comparent à un indice glissant.
2. **Masquer une erreur** avec `except: pass`, `|| true` ou un repli silencieux.
   Une source qui échoue doit être visible.
3. **Faire de l'I/O réseau dans `extract`** (hors le sous-module `extract.llm`).
   Le parseur doit rester testable hors ligne — c'est ce qui rend le corpus doré utile.
4. **Notifier sur une enchère dont la fin est lointaine.** Une cote à J−6 n'est pas
   une information. Voir [03-INTERFACES.md](03-INTERFACES.md) §5.
5. **Notifier une annonce dont `price_basis` vaut `unknown`** sans être passé par le
   LLM. C'est la source n°1 de fausse alerte urgente.
6. **Sortir un navigateur headless avant d'avoir essayé l'impersonation TLS.** Les
   données de Leboncoin sont déjà dans le HTML ; le blocage porte sur l'empreinte
   JA3, pas sur le rendu.
7. **Réessayer immédiatement après un blocage anti-bot.** Repli exponentiel
   obligatoire. Une boucle de retry serrée transforme un blocage temporaire en
   blocage durable.
8. **Utiliser `float` pour de l'argent.**
9. **Appeler le LLM avec une concurrence supérieure à 1**, ou sans décodage contraint.
10. **Jeter la charge utile brute d'une annonce.** Elle est archivée compressée, sans
    exception : sans elle, aucune amélioration du parseur n'est mesurable.
11. **Deviner une API tierce.** Les points `[À CONFIRMER]` se vérifient dans la
    documentation officielle.
12. **Committer un secret** (clé eBay, jeton ntfy, clé API) ou le faire apparaître
    dans un log.
13. **Paralléliser les requêtes vers une même source.** Une à la fois, avec gigue.

## 6. Vocabulaire

| Terme | Sens dans ce projet |
|---|---|
| **Annonce** (`RawListing`) | Une offre telle que collectée, normalisée mais non interprétée. |
| **Spec** (`MemorySpec`) | Le résultat de l'extraction : capacité, quantité, type, fréquence, base de prix, confiance. |
| **Affaire** (`Deal`) | Une spec qualifiée à laquelle un €/Go et une décote ont été attribués. |
| **Base de prix** (`price_basis`) | `lot` = le prix affiché couvre tous les modules ; `unit` = il couvre un module. |
| **Corpus doré** | Le jeu figé de titres réels étiquetés à la main qui sert de vérité terrain au parseur. |
| **Indice de marché** | Médiane glissante 30 jours du €/Go par compartiment de capacité, calculée sur les observations du système. |
| **Barrière absolue** | Plafond dur en €/Go. Protège d'un marché globalement cher. |
| **Barrière relative** | Décote minimale contre l'indice. Protège d'un marché qui monte. |
| **Borne optimiste** | Majorant de la capacité déduit par regex, qui donne un **minorant** du €/Go. Sert au préfiltre. |
| **Voie urgente / différée** | Les deux files d'appel au LLM. L'urgente accepte la contention, la différée l'évite. |
| **Chien de garde inversé** | Alerte déclenchée par l'**absence** de résultats, pas par une erreur. |
| **Quarantaine** | Annonce que ni les règles ni le LLM n'ont tranchée. Ni alerte, ni rejet. |

## 7. Conventions critiques (détail dans `09-CONVENTIONS.md`)

- **Unités explicites, toujours** : `capacity_gb=32` (jamais `capacity`),
  `speed_mts=2400` (jamais `speed`), `timeout_s`, `window_days`.
- **Argent en `Decimal`**, jamais `float`. La conversion se fait à la frontière.
- **Le port fait partie du prix.** `shipping=None` (inconnu) et `shipping=0`
  (gratuit) sont deux choses différentes et ne doivent jamais être confondues.
- Toute annonce écartée porte un **motif de rejet** persisté, pour pouvoir rejouer.

## 8. Definition of Done (minimum, pour toute contribution)

- [ ] Signatures typées, `mypy --strict` passe.
- [ ] Tests unitaires ; pour `extract`, non-régression sur le corpus doré.
- [ ] Aucun seuil ni valeur de configuration en dur.
- [ ] Erreurs issues de la taxonomie de [07-ERRORS-AND-LOGGING.md](07-ERRORS-AND-LOGGING.md).
- [ ] Journalisation structurée aux frontières du composant, avec `run_id`.
- [ ] Aucun secret dans le code ni dans les logs.
- [ ] Tout point incertain sur une API tierce marqué `[À CONFIRMER]`, jamais deviné.
