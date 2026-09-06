# WP00 — Reconnaissance & référentiel

> **Contexte** : RamTracker traque la DDR4 ECC sous-évaluée pour un Supermicro
> X10DRi-T4+. Ce WP ne produit **aucun code de production**. Il produit les deux
> choses sans lesquelles rien d'autre ne peut être écrit : le **référentiel de
> compatibilité** et le **corpus doré**. Il lève aussi le risque technique sur les
> trois sources externes.
>
> C'est l'étape la plus ingrate du projet et la plus rentable. La sauter revient à
> écrire un parseur sans savoir ce qu'il doit reconnaître, et à découvrir les
> surprises d'API au pire moment.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[10-HARDWARE-TARGET.md](../10-HARDWARE-TARGET.md) ·
[08-TESTING.md](../08-TESTING.md) §1 · [06-CONFIG.md](../06-CONFIG.md) §2

**Dépend de** : rien. **Bloque** : WP02 (corpus + matrice), WP03 (clés eBay).
**Parallélisable avec** : WP01.

---

## 1. Objectif

Produire quatre livrables : `configs/compat.yaml`, `tests/fixtures/titles.jsonl`,
`tests/fixtures/payloads/`, et un jeu de comptes et de clés fonctionnel.

---

## 2. Livrables

### 2.1 `configs/compat.yaml`

Transcription de [10-HARDWARE-TARGET.md](../10-HARDWARE-TARGET.md) §3 et §4, au
format défini en [06-CONFIG.md](../06-CONFIG.md) §2.

Les tables de décodage SK Hynix et Micron sont marquées `[À CONFIRMER]` dans le
blueprint : les compléter ici, contre les fiches produit constructeur, **pas** contre
des annonces. Vérifier également les capacités maximales sur la QVL Supermicro.

### 2.2 `tests/fixtures/titles.jsonl` — le corpus doré

150 titres réels relevés à la main sur les trois sources, étiquetés avec la spec
attendue. Format et typologie de pièges obligatoires en
[08-TESTING.md](../08-TESTING.md) §1.

Contraintes :

- Au moins **40 pièges**, et au moins **8 de type `prix_unitaire`** — c'est le piège
  qui produit de fausses alertes urgentes, donc celui qui décrédibilise le système.
- Les trois langues représentées : français, allemand, anglais.
- Les annonces qui portent une **référence constructeur** sont étiquetées comme
  telles, pour mesurer le rendement de l'étage 1.
- Étiquetage **à la main**. Ne pas pré-remplir avec un parseur : le corpus servirait
  alors à valider ses propres erreurs.

### 2.3 `tests/fixtures/payloads/`

Une réponse réelle capturée par source, anonymisée des identifiants de vendeur :

```text
payloads/ebay_search_fr.json          réponse item_summary/search complète
payloads/ebay_search_auction.json     variante enchères
payloads/leboncoin_recherche.html     page HTML entière, avec __NEXT_DATA__
payloads/reddit_new.json              listing r/homelabsales
```

Ce sont ces fichiers qui permettront à la CI de tester les collecteurs **sans
réseau** ([08-TESTING.md](../08-TESTING.md) §3).

### 2.4 Comptes et clés

| Service | À obtenir | Vérification |
|---|---|---|
| eBay Developers | `client_id`, `client_secret` | un `item_summary/search` renvoie du JSON |
| Reddit | application « script » | un `/new` authentifié répond |
| ntfy | un sujet au nom long et non devinable | une notification arrive sur le téléphone |
| Serveur LLM local | URL et nom du modèle | une complétion `response_format` contrainte revient valide |

---

## 3. Les trois spikes

Code **jetable**, dans `spikes/`, non versionné en production. Objectif : lever le
risque, pas produire du code réutilisable. Chacun répond à une question fermée.

| Spike | Question | Réponse attendue |
|---|---|---|
| `spike_ebay.py` | Le flux `client_credentials` fonctionne-t-il, et quel est le bon `category_ids` ? | Un identifiant de catégorie confirmé, une réponse JSON sauvegardée |
| `spike_lbc.py` | `curl_cffi` en `impersonate="chrome"` passe-t-il, et où sont les annonces dans `__NEXT_DATA__` ? | Le chemin JSON confirmé, une page sauvegardée |
| `spike_reddit.py` | L'OAuth « script » fonctionne-t-il et le format de titre est-il stable ? | Un listing sauvegardé |

Pour Leboncoin, respecter dès le spike les règles du primer : **une** requête à la
fois, aucune pagination profonde, aucune reprise immédiate en cas de blocage.

---

## 4. Ce que ce WP ne fait pas

- Aucun module sous `src/`.
- Aucune décision d'architecture : elles sont déjà prises
  ([00-PRIMER.md](../00-PRIMER.md) §4).
- Aucun essai d'optimiser les requêtes. On cherche à savoir si ça répond.

---

## 5. Critères d'acceptation

- [ ] `configs/compat.yaml` valide contre le modèle pydantic prévu en WP01, sans
      aucun `[À CONFIRMER]` restant sur les tables de décodage.
- [ ] `titles.jsonl` contient 150 lignes, dont ≥ 40 pièges et ≥ 8 `prix_unitaire`.
- [ ] Les trois langues sont représentées dans le corpus.
- [ ] `tests/fixtures/payloads/` contient au moins une capture réelle par source.
- [ ] Les trois spikes ont tourné et renvoyé des données réelles.
- [ ] Une notification de test est arrivée sur le téléphone.
- [ ] Une complétion contrainte par schéma est revenue valide du serveur LLM local.
- [ ] Aucun secret dans le dépôt ; `.env.example` liste toutes les variables.
