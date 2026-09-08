# Worker de suppression de compte eBay (WP10)

Point d'entrée de conformité RGPD/CCPA hébergé gratuitement sur **Cloudflare
Workers** (palier gratuit : 100 000 requêtes/jour, toujours actif, TLS et
sous-domaine `*.workers.dev` fournis). Il accuse réception des notifications eBay
24/7 — même quand le serveur maison est éteint — et les met en file dans
**Cloudflare KV**. RamTracker tire cette file avec `ramtracker
account-deletion-drain` (appelé aussi à chaque cycle de `loop`).

```
eBay ──HTTPS──▶ Worker (challenge + file KV)  ◀──tirage──  RamTracker (efface en base)
                 always-on, gratuit                          serveur maison, la journée
```

## Prérequis

- Un compte Cloudflare **gratuit** (aucune carte bancaire).
- Node.js ≥ 18 sur la machine de déploiement.

## Mise en place (une fois)

```bash
cd deploy/worker
npm install
npx wrangler login                       # ouvre le navigateur

# 1. Créer le namespace KV et coller l'id dans wrangler.toml
npx wrangler kv namespace create PENDING

# 2. Premier déploiement pour connaître l'URL publique
npx wrangler deploy
# → https://ramtracker-ebay-deletion.<ton-sous-domaine>.workers.dev

# 3. Reporter cette URL (+ le chemin) dans wrangler.toml :
#    EBAY_DELETION_ENDPOINT_URL = "https://ramtracker-ebay-deletion.<...>.workers.dev/ebay/marketplace-account-deletion"

# 4. Secrets
npx wrangler secret put EBAY_VERIFICATION_TOKEN   # même valeur que .env et que le portail eBay
npx wrangler secret put PULL_SECRET               # invente un jeton long, à mettre aussi dans .env

# 5. Redéployer avec la bonne config
npx wrangler deploy
```

### Secrets supplémentaires (vérification de signature)

Le worker vérifie le header `x-ebay-signature` de chaque notification (ECDSA/SHA1,
courbe P-256). Il lui faut une clé applicative eBay pour appeler `getPublicKey` :

```bash
npx wrangler secret put EBAY_CLIENT_ID       # même valeur que .env
npx wrangler secret put EBAY_CLIENT_SECRET   # même valeur que .env
```

Tant que ces deux secrets ne sont pas posés, le worker **ne peut pas** vérifier
et laisse passer (fail-open, tracé dans les logs). Une fois posés, une
notification dont la signature ne se vérifie pas reçoit **412 Precondition
Failed** et n'est pas mise en file. Pour n'auditer sans bloquer, décommenter
`ENFORCE_SIGNATURE = "false"` dans `wrangler.toml`.

Les entrées de file portent `verified: true|false` : `ramtracker
account-deletion-drain` les traite toutes (une entrée `false` ne peut apparaître
qu'en mode audit) mais le drapeau est journalisé.

## Côté RamTracker (`.env`)

```ini
ACCOUNT_DELETION_QUEUE_URL=https://ramtracker-ebay-deletion.<ton-sous-domaine>.workers.dev
ACCOUNT_DELETION_PULL_SECRET=<le même jeton que PULL_SECRET>
```

`ramtracker loop` et `ramtracker run-once` tirent la file automatiquement. Pour
forcer un passage : `uv run ramtracker account-deletion-drain`.

## Côté portail eBay

*Developer Portal → Application Keys → Alerts and Notifications → Marketplace
account deletion* :

| Champ | Valeur |
|---|---|
| Email | ton adresse |
| Endpoint URL | `https://ramtracker-ebay-deletion.<...>.workers.dev/ebay/marketplace-account-deletion` |
| Verification token | la valeur de `EBAY_VERIFICATION_TOKEN` |

*Save* déclenche le challenge en direct. `npx wrangler tail` permet de le voir passer.

## Routes

| Méthode | Chemin | Auth | Rôle |
|---|---|---|---|
| `GET` | `/ebay/marketplace-account-deletion?challenge_code=…` | — | Réponse au challenge eBay |
| `POST` | `/ebay/marketplace-account-deletion` | — | Réception d'une notification → file KV, `204` |
| `GET` | `/pending` | `Bearer PULL_SECRET` | Liste des notifications en attente |
| `POST` | `/ack` | `Bearer PULL_SECRET` | `{"notificationIds": […]}` → retrait de la file |

## Durcissement optionnel : allow-list d'IP eBay (Cloudflare)

La vérification de signature suffit à écarter un POST forgé. Pour aussi couper le
bruit au bord, ajouter une règle WAF sur le compte Cloudflare (*Security → WAF →
Custom rules*, non scriptable ici) :

```
(http.request.uri.path eq "/ebay/marketplace-account-deletion"
 and not ip.src in {<plages publiées par eBay>})   →   Block
```

eBay publie ses plages de notification sur
<https://developer.ebay.com/marketplace-account-deletion>. Ne pas filtrer
`/pending` ni `/ack` : ils viennent du serveur maison, pas d'eBay.

## Limite connue

Seuls ECDSA/SHA1 sont gérés (le seul schéma qu'eBay émet aujourd'hui). Si eBay
bascule sur un autre algorithme, le worker renverra `unavailable` et repassera en
fail-open jusqu'à mise à jour — visible dans `wrangler tail`.
