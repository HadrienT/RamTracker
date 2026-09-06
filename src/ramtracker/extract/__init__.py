"""`extract` — transforme un `RawListing` en `MemorySpec`.

Contrat D8 : aucune I/O (réseau, fichier, base, horloge) **hors** le sous-module
`extract.llm`. C'est ce qui rend la suite de tests du parseur déterministe et
hors ligne.
"""
