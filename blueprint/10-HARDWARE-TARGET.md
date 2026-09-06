# 10 — La cible : Supermicro X10DRi-T4+

> Prérequis : [00-PRIMER.md](00-PRIMER.md)
>
> Ce document définit **ce qu'on cherche à acheter**. Il est la source de
> `configs/compat.yaml` et donc de tout le filtre de qualification. Une erreur ici se
> propage silencieusement à l'ensemble du système.

---

## 1. La machine

| Caractéristique | Valeur |
|---|---|
| Socket | 2 × LGA2011-3 |
| Processeurs | Intel Xeon E5-2600 **v3** ou **v4** |
| Chipset | Intel C612 |
| Slots DIMM | **16** — 8 par CPU |
| Canaux | 4 par CPU, 2 DIMM par canal |
| Type mémoire | DDR4 **RDIMM** ou **LRDIMM** |
| Fréquence | 2133 (E5 v3) · 2400 (E5 v4) |
| Capacité maximale | 1 To en RDIMM · 2 To en LRDIMM |

`[À CONFIRMER]` — les capacités maximales et la liste des modules validés sont à
vérifier sur la **QVL officielle Supermicro** pendant WP00. Ne pas les deviner.

---

## 2. L'arbitrage qui justifie le projet

La carte fait tourner **toutes** les barrettes à 2133 ou 2400, quelle que soit leur
fréquence nominale. Une DDR4-3200 y est downclockée : on paie plus cher une
caractéristique inutilisable.

Or le DDR4-2133 est la bande la moins chère du marché, précisément parce que plus
personne d'autre n'en veut. Relevés de septembre 2026 sur le refurb professionnel :

| Fréquence | $/Go | Statut pour cette machine |
|---|---|---|
| DDR4-2133 | 4,53 – 5,93 | **La cible** — native, la moins chère |
| DDR4-2400 | 4,61 – 11,25 | Bonne — native sur E5 v4 |
| DDR4-2666 | 6,23 – 12,06 | Downclock — surcoût pur |
| DDR4-3200 | 9,36 – 19,83 | Downclock — à éviter |
| *Médiane toutes DDR4 ECC* | *9,34* | |

Conséquence pour le moteur de décision : une annonce en 2133 n'est pas un
second choix, c'est **la** cible. `configs/sources.yaml` interroge explicitement
`PC4-2133P` en plus des requêtes génériques.

Ces chiffres servent uniquement à **calibrer le point de départ** des seuils. Ils ne
sont jamais écrits dans le code : le marché a bougé de 30 à 50 % en un an, et c'est
l'indice glissant qui fait foi ([00-PRIMER.md](00-PRIMER.md) §2, principe P2).

---

## 3. Matrice de compatibilité

Source de `configs/compat.yaml`. Les rejets durs éliminent l'essentiel du bruit d'un
marché où « DDR4 ECC » désigne aussi bien une barrette de portable qu'un module
serveur.

| Critère | Accepté | Rejeté | Pourquoi c'est piégeux |
|---|---|---|---|
| Génération | `DDR4`, `PC4` | `DDR3`, `PC3`, `DDR5` | « PC3-12800R » ressemble à « PC4-19200R » dans un titre bâclé |
| Registre | `RDIMM` (REG), `LRDIMM` | `UDIMM` non-ECC | « ECC » seul ne suffit pas : l'ECC UDIMM existe et coûte plus cher au Go |
| Format | DIMM 288 broches | `SODIMM`, 260 broches | Beaucoup d'annonces « DDR4 ECC 16 Go » sont des SODIMM de station mobile |
| Fréquence | 2133, 2400 | — | 2666+ accepté mais **déprioritisé** |
| Organisation | `1Rx4`, `2Rx4`, `2Rx8`, `4Rx4` | `x16` | À tracer, pas à rejeter |
| Capacité module | 8, 16, 32, 64 Go | 4 Go | Le 4 Go sature les slots pour rien |
| Marque | Samsung, Hynix, Micron, Kingston, Crucial | — | Les modules Dell/HPE sont généralement OK en DDR4 — **signaler**, pas rejeter |

**Ce qu'il ne faut pas encoder** : aucune règle sur le mélange RDIMM/LRDIMM ni sur
l'appairage des rangs. Ce sont des contraintes de **montage**, pas d'**achat**. Le
système qualifie des annonces, il ne planifie pas une configuration mémoire ;
confondre les deux fait rater des affaires parce qu'elles ne complètent pas un kit
théorique.

---

## 4. Décodeur de références constructeur

**La moitié du travail du parseur, pour un dixième de l'effort.** Les références sont
auto-descriptives : quand un vendeur recopie celle de l'étiquette, capacité, rangs,
fréquence et type sortent d'une table de correspondance avec une confiance de 100 %,
sans aucun traitement de langage.

### Samsung

| Segment | Position | Valeurs |
|---|---|---|
| Famille | `M393` | RDIMM DDR4 · `M386` = LRDIMM · `M378`/`M471` = UDIMM/SODIMM → **rejet** |
| Densité | `A1G43` / `A2G40` / `A4K40` / `A8K40` | 8 · 16 · 32 · 64 Go |
| Vitesse | `-CPB` / `-CRC` / `-CTD` | 2133 · 2400 · 2666 |

Exemple : `M393A4K40BB1-CRC` → RDIMM DDR4, 32 Go, 2Rx4, 2400 MT/s.

### SK Hynix — `[À CONFIRMER]`

`HMA42GR7…` = 16 Go · `HMA84GR7…` = 32 Go · suffixe `-TF` = 2133, `-UH` = 2400.
Le `R` de `HMA…R…` indique RDIMM, `L` indique LRDIMM. Table à compléter et valider
pendant WP00.

### Micron — `[À CONFIRMER]`

`MTA18ASF2G72PDZ` (16 Go 2Rx8), `MTA36ASF4G72PZ` (32 Go 2Rx4). Table à compléter.

### Détection

Un motif de la forme `[A-Z]{1,3}\d{3}[A-Z0-9]{6,10}-[A-Z0-9]{2,4}` appliqué au titre
et à la description attrape la majorité des annonces sérieuses — typiquement celles
des vendeurs professionnels et des démonteurs de datacenter, qui sont justement les
meilleures.

---

## 5. Ce qu'un remplissage coûte

Ordre de grandeur, pour situer l'enjeu et calibrer la patience.

| Configuration | Total | @ 5 €/Go | @ 3 €/Go | @ 2 €/Go |
|---|---|---|---|---|
| 8 × 32 Go | 256 Go | 1 280 € | 768 € | 512 € |
| 16 × 16 Go | 256 Go | 1 280 € | 768 € | 512 € |
| 16 × 32 Go | 512 Go | 2 560 € | 1 536 € | 1 024 € |

L'écart entre le prix marché et une bonne affaire chassée patiemment se compte en
centaines d'euros. C'est le budget que justifie le projet.
