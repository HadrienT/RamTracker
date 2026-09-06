# WP09 — Boucle d'amélioration

> **Contexte** : le système tourne, notifie et couvre trois sources. Il produit
> maintenant deux choses exploitables qu'il ne sait pas encore utiliser : les
> **alertes ignorées** et la **quarantaine**.
>
> Ce WP transforme un système qui fonctionne en un système qui s'améliore. Son
> objectif réel : rendre le taux de fausses alertes **mesurable**, donc réductible.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[04-DATA-MODEL.md](../04-DATA-MODEL.md) · [08-TESTING.md](../08-TESTING.md) §1 et §4 ·
[03-INTERFACES.md](../03-INTERFACES.md) §7

**Dépend de** : WP06. **Bloque** : rien.

---

## 1. Objectif

Fermer trois boucles : le retour d'usage sur les alertes, le rejeu du parseur sur
l'historique archivé, et le rapport hebdomadaire.

---

## 2. Le point d'entrée d'action

Trente lignes de FastAPI, en écoute sur **`127.0.0.1` uniquement**, qui servent les
boutons des notifications :

```text
POST /mute/{fingerprint}     → alerts.outcome = 'ignored', cooldown 24 h
POST /bought/{fingerprint}   → alerts.outcome = 'bought'
```

Chaque « Ignorer » devient une **étiquette négative**. C'est la donnée qui permettra
plus tard de dire si un seuil est trop généreux, plutôt que de le deviner.

Tant que ce WP n'est pas livré, WP05 n'inclut pas le bouton dans la notification :
pas de bouton mort.

---

## 3. Le rejeu

C'est la contrepartie de l'archivage brut (ADR-6 du document narratif, interdit n°10
du primer). Sans lui, chaque amélioration du parseur est un pari aveugle.

```text
ramtracker replay --since 2026-08-01
```

Rejoue la cascade courante sur `listings.raw_payload` et affiche le **différentiel** :

```text
rejouées                     1 284
  nouvellement qualifiées       37   ← ce que la correction a débloqué
  nouvellement rejetées          4   ← ce qu'elle a cassé  ⚠
  changement de spec            12
  inchangées                 1 231
  affaires manquées a posteriori 3   ← auraient dépassé le seuil
```

La ligne « nouvellement rejetées » est la plus importante : c'est la seule qui dise
qu'une amélioration a régressé. La ligne « affaires manquées » chiffre en euros ce
que le bug a coûté.

Le rejeu s'appuie sur `spec_cache.parser_version` : les entrées dont la version est
antérieure sont recalculées, les autres non.

---

## 4. Réinjection de la quarantaine

Revue mensuelle, semi-automatique :

1. Lister les entrées `spec_cache` avec `reject_reason='low_confidence'`.
2. Les étiqueter à la main.
3. Les ajouter à `tests/fixtures/titles.jsonl`.
4. Relancer `just test-golden` — le taux de résolution par étage montre
   immédiatement ce que la nouvelle règle a rapporté.

Le corpus doré ne fait que **grandir**. On n'en retire jamais une entrée pour faire
passer un test ([08-TESTING.md](../08-TESTING.md) §1).

---

## 5. Le rapport hebdomadaire

```text
ramtracker report --weekly
```

| Section | Contenu | À quoi ça sert |
|---|---|---|
| Indice de marché | €/Go médian par capacité, évolution sur 4 semaines | Voir si le marché bouge, et donc si le plafond dur est encore pertinent |
| Alertes | envoyées, ignorées, achetées, supprimées par l'anti-spam | Mesurer le taux de fausses alertes |
| Sources | annonces brutes, qualifiées, cycles vides, blocages | Santé de la collecte |
| Extraction | résolution par étage, taille de la quarantaine | Rendement du parseur |
| LLM | appels, secondes de GPU, replis distants | Contention réelle avec OpenHands |

Envoyé par ntfy en priorité 2, le dimanche.

---

## 6. Tests attendus

| Test | Attendu |
|---|---|
| `POST /mute` | `outcome='ignored'`, cooldown appliqué |
| Point d'entrée | écoute sur `127.0.0.1`, **jamais** `0.0.0.0` |
| Empreinte inconnue | 404, aucune écriture |
| `replay` sans changement de parseur | différentiel entièrement « inchangées » |
| `replay` après régression volontaire | « nouvellement rejetées » > 0 |
| `replay` | ne modifie **jamais** `alerts`, ni n'envoie de notification |
| Rapport sur base vide | produit un rapport valide, pas une exception |

Le test « `replay` n'envoie pas de notification » est indispensable : un rejeu sur
trois mois d'historique qui déclencherait les alertes correspondantes serait une
catastrophe.

---

## 7. Critères d'acceptation

- [ ] Le taux de fausses alertes est **mesuré** et figure dans le rapport hebdomadaire.
- [ ] `replay` est strictement en lecture seule vis-à-vis des alertes.
- [ ] Le point d'entrée HTTP n'écoute que sur `127.0.0.1`.
- [ ] La quarantaine a été revue au moins une fois et a enrichi le corpus doré.
- [ ] Le rapport hebdomadaire arrive sur le téléphone.
- [ ] `mypy --strict` passe.
