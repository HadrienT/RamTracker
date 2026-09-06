# WP03 — `collect` : interface + collecteur eBay

> **Contexte** : RamTracker collecte des annonces de mémoire serveur sur plusieurs
> places de marché. eBay est traité **en premier** parce que c'est une API officielle,
> gratuite (5 000 appels/jour), documentée et sanctionnée — donc la source qui
> valide la chaîne complète en une soirée.
>
> Commencer par Leboncoin reviendrait à passer trois soirées sur l'anti-bot avant
> d'avoir la moindre notification, et à découvrir ensuite que le parseur ne marche
> pas. Leboncoin et Reddit sont livrés par WP08.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[03-INTERFACES.md](../03-INTERFACES.md) §3 · [04-DATA-MODEL.md](../04-DATA-MODEL.md) §2 ·
[06-CONFIG.md](../06-CONFIG.md) §3 · [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md)

**Dépend de** : WP01. **Bloque** : WP04, WP06. **Parallélisable avec** : WP02.

---

## 1. Objectif

Définir l'interface `Collector` — trois lignes — et livrer une implémentation eBay
qui produit des `RawListing` complets, **port compris**.

---

## 2. Modules & responsabilités

| Module | Responsabilité |
|---|---|
| `base.py` | `Protocol Collector`, `CollectResult` |
| `ebay.py` | OAuth applicatif, jeton en cache, recherche achat + enchère, normalisation |
| `registry.py` | Nom de source → instance, construit depuis `sources.yaml` |

---

## 3. Contrats clés

### 3.1 L'interface

```python
class Collector(Protocol):
    name: str
    def fetch_recent(self, since: datetime) -> CollectResult: ...
```

Règles valables pour **toute** implémentation présente et future :

- Elle **détecte** un blocage et le signale (`challenged`, ou `SourceBlocked`). Elle
  ne **décide** jamais de réessayer : c'est `runtime.breaker` (WP06). Un collecteur
  qui gérerait son propre repli rendrait la politique invisible et non testable.
- Elle remplit `raw_count` **même quand `listings` est vide**. C'est ce compteur qui
  distingue « la source répond mais n'a rien de neuf » de « la source est cassée », et
  c'est le socle du chien de garde inversé.
- Elle ne parallélise jamais ses requêtes vers une même source.
- `shipping` reste `None` si la source ne le donne pas. **Jamais `0`.**

### 3.2 Le jeton eBay

`client_credentials`, scope `https://api.ebay.com/oauth/api_scope`, validité 2 h.
Mis en cache sur disque avec sa date d'expiration ; rafraîchi à T−5 min. Un `401`
déclenche **une seule** reprise après rafraîchissement, puis `SourceAuthError`.

### 3.3 Les deux requêtes

```text
achat    filter=buyingOptions:{FIXED_PRICE|BEST_OFFER}   sort=newlyListed
enchère  filter=buyingOptions:{AUCTION}                  sort=endingSoonest
```

Le tri diffère volontairement : pour l'achat immédiat ce qui compte est la nouveauté,
pour l'enchère c'est l'imminence de la clôture ([03-INTERFACES.md](../03-INTERFACES.md) §5).

### 3.4 Le port — ne pas négliger

`X-EBAY-C-ENDUSERCTX: contextualLocation=country=FR,zip=…` est **obligatoire**. Sans
lui, les frais de port renvoyés sont ceux du marché par défaut, et le €/Go calculé
est faux — c'est-à-dire que le seuil d'alerte se déclenche sur des valeurs erronées.

### 3.5 Budget d'appels

Quatre requêtes par cycle (FR et DE × achat et enchère) toutes les dix minutes font
**576 appels/jour**, soit 11 % du quota gratuit. Il reste largement de quoi ajouter
des marchés et des requêtes par référence constructeur.

`[À CONFIRMER]` — l'identifiant de catégorie `170083` doit être confirmé au spike
WP00 avant d'être écrit dans `sources.yaml`.

---

## 4. Tests attendus

Tous contre `tests/fixtures/payloads/`, **sans réseau**.

| Test | Attendu |
|---|---|
| Parsing d'une réponse réelle | N `RawListing` valides, `raw_count` correct |
| Annonce sans port annoncé | `shipping is None`, jamais `0` |
| Annonce à port gratuit annoncé | `shipping == 0` |
| Enchère | `sale_type=AUCTION`, `ends_at` aware UTC, `current_bid` renseigné |
| Réponse vide | `CollectResult` valide, `raw_count=0`, aucune exception |
| `401` | une reprise, puis `SourceAuthError` |
| `429` | `SourceBlocked` |
| Champ attendu absent du JSON | `SourceSchemaChanged`, pas un `KeyError` nu |
| `raw_payload` | présent et décompressable pour chaque annonce |

Le test « champ attendu absent » est celui qui compte : c'est lui qui garantit qu'un
changement de contrat chez eBay produit une alerte technique plutôt qu'un silence.

---

## 5. Critères d'acceptation

- [ ] Une exécution unique écrit des `RawListing` valides en base, port renseigné.
- [ ] `raw_count` est correct y compris quand aucune annonce n'est nouvelle.
- [ ] Aucun `shipping=0` produit pour un port inconnu.
- [ ] Tous les tests tournent sans réseau, contre les charges utiles figées.
- [ ] Le jeton est mis en cache et réutilisé entre deux cycles.
- [ ] `import-linter` : `collect` n'importe que `core` (D2).
- [ ] Aucun identifiant de catégorie ou marché en dur : tout vient de `sources.yaml`.
- [ ] `mypy --strict` passe.
