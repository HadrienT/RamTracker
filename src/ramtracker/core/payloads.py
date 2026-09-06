"""Compression des charges utiles brutes (interdit n°10 : ne jamais les jeter).

`raw_payload` est archivé compressé sans exception : sans lui, aucune
amélioration du parseur n'est mesurable (rejeu, WP09).
"""

from __future__ import annotations

import zstandard

_MAGIC = b"RTZ1"
_compressor = zstandard.ZstdCompressor(level=10)
_decompressor = zstandard.ZstdDecompressor()


def pack(raw: bytes) -> bytes:
    """Compresse une charge utile pour l'archivage."""
    return _MAGIC + _compressor.compress(raw)


def unpack(blob: bytes) -> bytes:
    """Décompresse une charge utile archivée."""
    if not blob.startswith(_MAGIC):
        raise ValueError("charge utile non reconnue : préfixe absent")
    return _decompressor.decompress(blob[len(_MAGIC) :])
