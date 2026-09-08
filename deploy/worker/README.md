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

## Limite connue

La signature `x-ebay-signature` n'est pas vérifiée (cf. `blueprint/wp/WP10`
§6). Le worker n'expose que `/pending` et `/ack` derrière `PULL_SECRET` ; l'impact
d'un POST forgé sur le chemin eBay se limite à une anonymisation anticipée.
