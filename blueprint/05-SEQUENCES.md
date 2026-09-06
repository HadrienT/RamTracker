# 05 — Séquences

> Prérequis : [01-ARCHITECTURE.md](01-ARCHITECTURE.md) · [03-INTERFACES.md](03-INTERFACES.md)

Quatre parcours bout-en-bout. Ils fixent l'ordre des appels et les points de
persistance ; les signatures sont dans `03`.

---

## 1. Cycle nominal — d'eBay à la notification

```mermaid
sequenceDiagram
    participant S as scheduler
    participant B as breaker
    participant C as collect.ebay
    participant DB as SQLite
    participant X as extract.cascade
    participant D as decide
    participant N as notify

    S->>B: allow("ebay") ?
    B-->>S: oui
    S->>C: fetch_recent(since)
    C->>C: jeton en cache, sinon OAuth
    C-->>S: CollectResult(listings, raw_count)
    S->>B: record_success("ebay")

    loop pour chaque annonce
        S->>DB: is_new(source, external_id) ?
        alt déjà vue et prix inchangé
            S->>DB: UPDATE last_seen
        else nouvelle ou prix en baisse
            S->>DB: INSERT listings (dont raw_payload)
            S->>DB: SELECT spec_cache WHERE spec_hash
            alt cache manquant ou parser_version périmée
                S->>X: run(listing, matrix, llm)
                X-->>S: MemorySpec
                S->>DB: INSERT spec_cache
            end
            S->>D: evaluate(listing, spec, index, policy, now)
            alt Deal retourné
                S->>N: allow(deal) ?
                N-->>S: oui
                S->>N: send(render(deal))
                S->>DB: INSERT alerts
            end
        end
    end
    S->>DB: INSERT source_runs
```

Le `SELECT spec_cache` **avant** l'appel à la cascade est ce qui fait tout le travail
d'économie : un repost, un doublon inter-sources ou une simple republication ne
déclenchent aucune extraction.

---

## 2. Annonce ambiguë — préfiltre puis file LLM (WP07)

```mermaid
sequenceDiagram
    participant X as extract.cascade
    participant P as extract.prefilter
    participant Q as runtime.llm_queue
    participant L as serveur LLM local
    participant A as API distante

    X->>X: partnum.decode → None
    X->>X: grammar.parse → confiance 0.55
    X->>X: coherence.check → confiance 0.45
    Note over X: sous le seuil : ne pas deviner
    X->>P: best_case_eur_per_gb(listing)
    alt meilleur cas > barrière absolue
        P-->>X: rejet "meilleur_cas_hors_seuil"
        Note over P,X: aucun appel LLM — zéro faux négatif par construction
    else peut être une affaire
        P-->>X: 1,80 €/Go
        X->>Q: enqueue(spec_hash, lane, best_case)
        alt voie urgente
            Q->>L: extract_batch, timeout court
            alt serveur occupé par OpenHands
                L-->>Q: timeout
                Q->>A: repli distant
                A-->>Q: MemorySpec
            else
                L-->>Q: MemorySpec
            end
        else voie différée
            Note over Q: minuterie 30 min ; tour sauté si le serveur est occupé
            Q->>L: extract_batch
            L-->>Q: MemorySpec
        end
    end
```

La voie urgente n'est empruntée que lorsque la borne optimiste est très en dessous de
la barrière — quelques fois par semaine. C'est ce qui rend acceptable d'accepter la
contention avec OpenHands dans ce cas précis.

---

## 3. Blocage anti-bot et disjoncteur

```mermaid
sequenceDiagram
    participant S as scheduler
    participant B as breaker
    participant C as collect.leboncoin
    participant N as notify

    S->>C: fetch_recent(since)
    C->>C: HTTP 403, ou marqueur DataDome dans le corps
    C-->>S: SourceBlocked
    S->>B: record_failure("leboncoin")
    B->>B: échec 1/3 — prochaine tentative dans 15 min

    Note over S,B: deuxième cycle, puis troisième

    S->>B: record_failure("leboncoin")
    B->>B: 3 échecs — disjoncteur OUVERT, repli 4 h
    B->>N: alerte technique, priorité 3
    Note over S: eBay et Reddit continuent normalement
```

Le disjoncteur est **par source**. Une seule règle à ne jamais enfreindre : aucune
nouvelle tentative avant la fenêtre suivante. Une boucle de retry serrée transforme
un blocage temporaire en blocage durable.

---

## 4. Le chien de garde inversé

```mermaid
sequenceDiagram
    participant S as scheduler
    participant W as watchdog
    participant DB as SQLite
    participant N as notify

    Note over S: après chaque cycle
    S->>W: check(conn, policy, now)
    W->>DB: SELECT raw_count, qualified<br/>des 3 derniers runs par source
    alt une source remontait des annonces et n'en remonte plus
        W-->>S: Anomaly(source, "0 annonce depuis 3 cycles")
        S->>N: alerte technique, priorité 3
    else nominal
        W-->>S: []
    end
```

C'est l'alerte la plus importante du système : la seule qui signale que **le système
ment**. Sans elle, un changement de schéma chez Leboncoin passe pour un marché calme
et peut durer des mois.
