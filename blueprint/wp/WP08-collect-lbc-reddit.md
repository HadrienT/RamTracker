# WP08 — Collecteurs Leboncoin & Reddit

> **Contexte** : le système fonctionne déjà de bout en bout avec eBay (WP03→WP06) et
> notifie sur téléphone. Ce WP élargit la couverture au marché C2C francophone — le
> vrai gisement d'affaires — et au marché anglophone du homelab.
>
> Ces deux sources arrivent **en dernier volontairement**. Leboncoin est le poste le
> plus coûteux du projet, et l'attaquer avant d'avoir un système qui marche est le
> meilleur moyen d'abandonner.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) §5 ·
[03-INTERFACES.md](../03-INTERFACES.md) §3 · [05-SEQUENCES.md](../05-SEQUENCES.md) §3 ·
[06-CONFIG.md](../06-CONFIG.md) §3 · [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md)

**Dépend de** : WP03 (l'interface), WP06 (le disjoncteur).
**Parallélisable avec** : WP07.

---

## 1. Leboncoin

### 1.1 Ce à quoi on s'attaque

Leboncoin bloque en moyenne 9,5 millions de requêtes malveillantes par jour, dont
environ 90 % de scraping. DataDome évalue trois signaux : **empreinte TLS/JA3**,
empreinte navigateur, réputation IP. Les proxys datacenter sont éliminés d'office.

La position du projet est cependant bien meilleure que celle d'un scraper commercial :
l'IP est **résidentielle française** — le signal le plus dur à falsifier, déjà acquis
— et le volume est de **vingt-quatre requêtes par jour**. Ce profil est indiscernable
d'un utilisateur qui consulte une recherche sauvegardée.

Écrire le collecteur pour **rester dans ce profil**, pas pour « passer » la protection.

### 1.2 Impersonation TLS avant navigateur headless

Le signal qui trahit un client Python standard est son empreinte JA3. `curl_cffi` en
`impersonate="chrome"` la corrige. Or les données sont déjà dans le HTML : Leboncoin
est une application Next.js, tout le JSON vit dans `<script id="__NEXT_DATA__">`. Il
n'y a **rien à rendre**, donc rien qui justifie un navigateur — une extraction HTML
est environ dix fois moins coûteuse en ressources.

Playwright reste le plan B, derrière la même interface `Collector`, activable par
configuration sans toucher au reste. Interdit n°6 du primer : ne pas le sortir avant
d'avoir essayé l'impersonation TLS.

### 1.3 Extraction

```text
GET /recherche?text=…&category=17&sort=time     curl_cffi, impersonate="chrome"

<script id="__NEXT_DATA__" type="application/json">
  props.pageProps.searchData.ads                      [À CONFIRMER] chemin courant
  props.pageProps.initialProps.searchData.ads         [À CONFIRMER] repli

champs : list_id · subject · body · price[0] · url · location · owner · index_date
```

Les deux chemins sont marqués `[À CONFIRMER]` : les vérifier au spike WP00 et écrire
le collecteur pour **essayer le second si le premier est absent**, en levant
`SourceSchemaChanged` si aucun ne répond.

### 1.4 Détection de défi

Le défi anti-bot est un **état de premier ordre**, pas une erreur générique :
HTTP 403, ou marqueur DataDome dans le corps. Le collecteur lève `SourceBlocked` et
positionne `challenged=True`. Il ne décide **jamais** de réessayer : c'est
`runtime.breaker` (WP06), avec repli exponentiel.

Règles non négociables : une requête à la fois, délai aléatoire, **jamais** de
parallélisme, **jamais** de pagination profonde (`max_pages: 1`).

### 1.5 Qualité des titres

Texte libre, orthographe libre, trois graphies pour « barrette ». C'est la source qui
alimentera le plus la quarantaine et donc le corpus doré. Prévoir que le taux de
recours au LLM y soit nettement plus élevé que sur eBay.

---

## 2. Reddit

`r/homelabsales` impose un format de titre `[Pays] [H] ce que je vends [W] ce que je
veux`, ce qui en fait le corpus le plus propre des trois.

Mais c'est un marché **majoritairement américain** : port transatlantique et droits de
douane rendent la plupart des annonces inintéressantes à l'achat.

**Conséquence de conception** : traiter Reddit en priorité comme un **capteur de
prix** qui alimente l'indice de marché (WP04), avec un filtre `shippable_from` qui ne
remonte à l'alerte que ce qui est expédiable depuis l'Europe. C'est aussi la meilleure
source d'observations pendant le mode observation, avant que les données propres au
système ne suffisent.

```text
POST /api/v1/access_token           application « script »
GET  /r/homelabsales/new?limit=100  User-Agent descriptif OBLIGATOIRE
```

---

## 3. Cadence

Reprise de [06-CONFIG.md](../06-CONFIG.md) §3, à ne pas durcir :

| Source | Intervalle | Gigue | Pages |
|---|---|---|---|
| Leboncoin | 75 min | ± 20 min | 1 |
| Reddit | 15 min | ± 3 min | 1 |

---

## 4. Tests attendus

Tous contre `tests/fixtures/payloads/`, **sans réseau**.

| Test | Attendu |
|---|---|
| Page LBC réelle | N `RawListing`, `raw_count` correct |
| Chemin JSON principal absent | repli sur le chemin secondaire |
| Les deux chemins absents | `SourceSchemaChanged` |
| HTTP 403 | `SourceBlocked`, `challenged=True` |
| Marqueur DataDome dans un corps 200 | `SourceBlocked` |
| Remise en main propre | `shipping is None`, **jamais** `0` |
| Titre Reddit `[H]/[W]` | vendeur et acheteur correctement séparés |
| Annonce hors `shippable_from` | collectée pour l'indice, **exclue** de l'alerte |
| Collecteur LBC | aucune requête parallèle émise |

---

## 5. Critères d'acceptation

- [ ] Leboncoin remonte des annonces réelles sur au moins trois cycles consécutifs.
- [ ] Un blocage provoqué ouvre le disjoncteur sans boucle de reprise.
- [ ] Aucune requête parallèle vers une même source, vérifié par test.
- [ ] Playwright n'est **pas** utilisé par défaut.
- [ ] Les annonces Reddit hors zone alimentent l'indice sans jamais déclencher d'alerte.
- [ ] Aucune donnée de vendeur au-delà de ce qui sert au dédoublonnage.
- [ ] `mypy --strict` passe.
