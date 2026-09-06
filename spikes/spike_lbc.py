"""Spike Leboncoin — jetable. Une seule requête, aucune reprise.

    python spikes/spike_lbc.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

OUT = pathlib.Path("tests/fixtures/payloads/leboncoin_recherche.html")
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def main() -> int:
    from curl_cffi import requests

    resp = requests.get(
        "https://www.leboncoin.fr/recherche",
        params={"text": "DDR4 ECC", "category": "17", "sort": "time"},
        impersonate="chrome",
        timeout=25,
    )
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200 or "datadome" in resp.text.lower():
        print("bloqué — NE PAS réessayer tout de suite")
        return 1
    OUT.write_text(resp.text)
    m = _NEXT.search(resp.text)
    if not m:
        print("__NEXT_DATA__ absent")
        return 1
    data = json.loads(m.group(1))
    for path in (
        ("props", "pageProps", "searchData", "ads"),
        ("props", "pageProps", "initialProps", "searchData", "ads"),
    ):
        node = data
        for key in path:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        if isinstance(node, list):
            print(f"chemin confirmé : {'.'.join(path)} — {len(node)} annonces")
            break
    print(f"sauvegardé : {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
