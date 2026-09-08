# WP10 — Suppression de compte eBay

> **Contexte** : dès que RamTracker utilise des **clés eBay de production**, eBay
> impose (RGPD / CCPA) un point d'entrée public qui reçoit une notification par
> utilisateur qui ferme son compte, et efface ses données personnelles. Sans lui,
> eBay **suspend l'accès à l'API**.
>
> Réf. eBay : <https://developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion>

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[06-CONFIG.md](../06-CONFIG.md) §1 · [04-DATA-MODEL.md](../04-DATA-MODEL.md) §2-§3 ·
[01-ARCHITECTURE.md](../01-ARCHITECTURE.md) §5 · [`deploy/worker/README.md`](../../deploy/worker/README.md)

**Dépend de** : WP03. **Bloque** : passage des clés eBay en production.

---

## 1. Contrainte

Le serveur maison ne tourne que la journée, et l'objectif est **zéro service
payant**. Or eBay exige un point d'entrée joignable en permanence : si l'endpoint
échoue de façon répétée, eBay alerte par mail puis peut suspendre les clés.

La responsabilité est donc **coupée en deux** :

```
eBay ──HTTPS──▶ Worker Cloudflare (challenge + file KV)  ◀──tirage──  RamTracker
                 palier gratuit, toujours actif                       serveur maison, la journée
```

- Le **Worker** ([`deploy/worker/`](../../deploy/worker/)) accuse réception 24/7 et
  met chaque notification en file (Cloudflare KV). eBay ne voit jamais de panne.
- **RamTracker tire la file** (`ramtracker account-deletion-drain`, appelé aussi à
  chaque cycle de `loop`) et anonymise en base les annonces du vendeur concerné.

RamTracker ne stocke qu'une donnée personnelle eBay : le **nom d'utilisateur du
vendeur** (`listings.seller_id`, et le bloc `seller` dans `listings.raw_payload`).

---

## 2. Le Worker

Palier gratuit Cloudflare Workers : 100 000 requêtes/jour, toujours actif, TLS et
sous-domaine `*.workers.dev` fournis — **aucun domaine à acheter**. File dans
Cloudflare KV (1 000 écritures/jour gratuites, large pour des notifications rares).

| Méthode | Chemin | Auth | Rôle |
|---|---|---|---|
| `GET` | `/ebay/marketplace-account-deletion?challenge_code=…` | — | `200 {"challengeResponse": sha256(code+token+url)}` |
| `POST` | `/ebay/marketplace-account-deletion` | — | Topic `MARKETPLACE_ACCOUNT_DELETION` → `PENDING.put(notificationId, …)`, `204` |
| `GET` | `/pending` | `Bearer PULL_SECRET` | Notifications en attente (métadonnées KV) |
| `POST` | `/ack` | `Bearer PULL_SECRET` | `{"notificationIds": […]}` → retrait de la file |

`sha256hex(challenge_code + verification_token + endpoint_url)` — ordre imposé ;
`endpoint_url` identique **au caractère près** à l'URL déclarée dans le portail.

---

## 3. Le tirage côté RamTracker

`ramtracker.runtime.ebay_deletion.drain()` :

1. `GET {queue_url}/pending` avec le bearer.
2. Pour chaque entrée `{notificationId, username}` → `process_deletion` :
   `notificationId` déjà dans `account_deletion_events` ⇒ rien ; sinon, pour chaque
   `listings` (`source='ebay'`, `seller_id = username`) → `seller_id = NULL` +
   retrait du bloc `seller` de `raw_payload` ; puis trace `(notification_id,
   received_at, scrubbed_rows)`.
3. `POST {queue_url}/ack` avec les `notificationId` traités.

Une panne réseau du Worker n'interrompt pas le cycle (`drain` journalise et rend
`0`). Le `username` n'est **jamais** persisté.

L'app FastAPI équivalente (`create_app` / `ramtracker serve-account-deletion`)
reste disponible pour les tests et un éventuel auto-hébergement 24/7 (VM gratuite),
mais n'est pas le mode de déploiement retenu.

---

## 4. Configuration

| Variable | Rôle |
|---|---|
| `EBAY_VERIFICATION_TOKEN` | 32-80 car. `[A-Za-z0-9_-]`, choisi librement ; aussi dans le portail eBay **et** `wrangler secret put` |
| `EBAY_DELETION_ENDPOINT_URL` | URL publique du Worker + chemin eBay, identique à celle du portail |
| `ACCOUNT_DELETION_QUEUE_URL` | URL de base du Worker (sans chemin) |
| `ACCOUNT_DELETION_PULL_SECRET` | Jeton partagé RamTracker ↔ Worker pour `/pending` et `/ack` |

`drain()` sans file configurée ne fait rien ; configurée à moitié ⇒ `ConfigError`.

---

## 5. Étapes manuelles (hors code)

1. Compte Cloudflare **gratuit**. `cd deploy/worker && npm install && npx wrangler login`.
2. `npx wrangler kv namespace create PENDING` → coller l'`id` dans `wrangler.toml`.
3. `npx wrangler deploy` → noter l'URL `*.workers.dev`.
4. Reporter l'URL dans `wrangler.toml` (`EBAY_DELETION_ENDPOINT_URL`) et dans `.env`
   (`EBAY_DELETION_ENDPOINT_URL`, `ACCOUNT_DELETION_QUEUE_URL`).
5. `npx wrangler secret put EBAY_VERIFICATION_TOKEN` et `... PULL_SECRET`
   (mêmes valeurs que `.env`). `npx wrangler deploy` à nouveau.
6. Portail eBay → **Application Keys → Alerts and Notifications → Marketplace
   account deletion** : email, URL du Worker + chemin, jeton. *Save* déclenche le
   challenge — `npx wrangler tail` pour le voir passer.

---

## 6. Tests attendus

| Test | Attendu |
|---|---|
| `challenge_response` | SHA-256 de `code+token+endpoint`, dans cet ordre |
| GET challenge (app FastAPI) | 200, JSON, `challengeResponse` conforme |
| `create_app` sans config / jeton malformé | `ConfigError` |
| POST notification (app FastAPI) | 204, annonces du vendeur anonymisées |
| POST même `notificationId` deux fois | traité une seule fois |
| POST topic inattendu | 204, aucun effacement |
| `drain` sans file configurée | `0`, aucun appel |
| `drain` à moitié configuré | `ConfigError` |
| `drain` avec file peuplée | annonces anonymisées, `/ack` reçoit les `notificationId` |
| `drain` rejoué | idempotent (une seule ligne `account_deletion_events`) |

---

## 7. Vérification de la signature `x-ebay-signature`

**Fait dans le Worker** (`deploy/worker/src/worker.js`). Le header est un JSON
base64 `{ alg, kid, signature, digest }` ; la signature est en DER, courbe P-256,
condensé SHA-1 (seul schéma qu'eBay émet). Le Worker récupère la clé publique via
`commerce/notification/v1/public_key/{kid}` (jeton `client_credentials`, cache par
`kid`), convertit la signature DER → P1363 pour WebCrypto et vérifie contre les
octets du corps (repli sur une resérialisation JSON compacte). Signature invalide
⇒ **412**, jamais mise en file. `ENFORCE_SIGNATURE=false` repasse en audit ; sans
les secrets `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET` du Worker, c'est fail-open tracé.

**Reste ouvert :**

- **App FastAPI** (`create_app()`, chemin test / auto-hébergement 24/7) : ne
  vérifie pas encore. À faire avec `cryptography` (`load_pem_public_key`, `verify`
  accepte le DER nativement) *si* ce mode est retenu ; le Worker étant la voie
  utilisée, non bloquant.
- **Allow-list d'IP eBay** en règle WAF Cloudflare sur le chemin de notification
  (cf. `deploy/worker/README.md`) — défense en profondeur, non scriptable.

---

## 8. Critères d'acceptation

- [ ] Le portail eBay valide le point d'entrée (challenge réussi via le Worker).
- [ ] Une notification de test remonte par `drain` et anonymise les annonces.
- [ ] Aucun `username` eBay n'est persisté par le traitement.
- [ ] Aucun service payant : Worker + KV sur palier gratuit.
- [ ] `mypy --strict`, `ruff`, `import-linter` passent.
