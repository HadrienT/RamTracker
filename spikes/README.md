# Spikes de reconnaissance (WP00)

Code **jetable**. Objectif : lever le risque technique sur les trois sources
externes, pas produire du code réutilisable. Chaque spike répond à une question
fermée et sauvegarde une réponse réelle dans `tests/fixtures/payloads/`.

| Spike | Question | Sortie attendue |
|---|---|---|
| `spike_ebay.py` | Le flux `client_credentials` marche-t-il ? Quel `category_ids` ? | id de catégorie confirmé + `ebay_search_fr.json` |
| `spike_lbc.py` | `curl_cffi impersonate="chrome"` passe-t-il ? Où sont les annonces dans `__NEXT_DATA__` ? | chemin JSON confirmé + `leboncoin_recherche.html` |
| `spike_reddit.py` | L'OAuth « script » marche-t-il ? Le format de titre est-il stable ? | `reddit_new.json` |

Règles Leboncoin dès le spike : **une** requête, aucune pagination profonde,
aucune reprise immédiate en cas de blocage.

Ces fichiers ne sont pas sur le chemin de la CI et peuvent être supprimés une
fois les `[À CONFIRMER]` levés dans `configs/` et `src/`.
