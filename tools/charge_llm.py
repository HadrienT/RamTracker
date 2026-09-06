# -*- coding: utf-8 -*-
"""Modele d'entonnoir RamTracker -> charge reelle sur le LLM local."""

# --- hypotheses de volume (nouvelles annonces/jour, apres dedup par external_id) ---
SRC = {"ebay FR+DE": 160, "leboncoin": 15, "reddit": 20}
BRUT = sum(SRC.values())

# --- taux de survie a chaque etage (ordre = ordre d'execution) ---
ETAGES = [
    ("dedup (source, external_id)",      1.00, "gratuit — la meme annonce revue a chaque cycle"),
    ("cache de specs (spec_hash)",       0.88, "reposts LBC + doublons inter-sources"),
    ("rejet par mots-cles",              0.55, "DDR3 / SODIMM / DDR5 / non-ECC / portable"),
    ("parseur a regles (confiance ok)",  0.22, "78% resolus sans LLM : reference + regex"),
    ("prefiltre €/Go admissible",        0.40, "borne optimiste deja au-dessus du plafond"),
]

n = BRUT
print(f"{'etage':38s} {'restant/j':>10s}   commentaire")
print("-" * 96)
print(f"{'annonces brutes collectees':38s} {n:10.0f}")
for nom, taux, note in ETAGES:
    n *= taux
    print(f"{nom:38s} {n:10.1f}   {note}")
LLM_PAR_JOUR = n
print("-" * 96)
print(f"=> annonces envoyees au LLM : {LLM_PAR_JOUR:.1f}/jour\n")

# --- cout par appel ---
TOK_SYS, TOK_ANNONCE, TOK_SORTIE = 350, 170, 110
for lot in (1, 4):
    tin  = TOK_SYS + lot * TOK_ANNONCE
    tout = lot * TOK_SORTIE
    print(f"lot de {lot}: {tin:5d} tok entree + {tout:4d} tok sortie", end="  |  ")
    for pre, dec in ((900, 45), (2500, 90)):     # GPU modeste / GPU confortable
        s = tin / pre + tout / dec
        print(f"{s:5.1f}s @ {pre}/{dec} tok/s", end="   ")
    print()

appels = LLM_PAR_JOUR / 4
print(f"\n=> ~{appels:.1f} appels/jour en lots de 4")
for pre, dec in ((900, 45), (2500, 90)):
    s = appels * ((TOK_SYS + 4*TOK_ANNONCE)/pre + (4*TOK_SORTIE)/dec)
    print(f"   occupation totale du GPU : {s:5.1f} s/jour  ({s/86400*100:.3f} % du temps) @ {pre}/{dec} tok/s")

# --- cout du --parallel 2 : KV cache ---
print("\n--- cout VRAM d'un 2e slot (KV cache) ---")
print("octets/token = 2 x n_layers x n_kv_heads x head_dim x octets_par_elem\n")
print(f"{'modele':22s} {'KB/tok':>8s} {'32k ctx':>9s} {'64k ctx':>9s}  (fp16)")
for nom, L, H, D in (("~8B  (32L, 8KV)", 32, 8, 128),
                     ("~14B (48L, 8KV)", 48, 8, 128),
                     ("~32B (64L, 8KV)", 64, 8, 128),
                     ("~70B (80L, 8KV)", 80, 8, 128)):
    per = 2 * L * H * D * 2
    print(f"{nom:22s} {per/1024:8.0f} {per*32768/2**30:8.1f}G {per*65536/2**30:8.1f}G")
