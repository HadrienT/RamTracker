"""Spike eBay — jetable. Vérifie client_credentials + trouve le bon category_ids.

    EBAY_CLIENT_ID=... EBAY_CLIENT_SECRET=... python spikes/spike_ebay.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import httpx

OUT = pathlib.Path("tests/fixtures/payloads/ebay_search_fr.json")


def main() -> int:
    cid = os.environ["EBAY_CLIENT_ID"]
    secret = os.environ["EBAY_CLIENT_SECRET"]
    zip_code = os.environ.get("EBAY_ZIP", "69001")

    token = httpx.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        auth=(cid, secret),
    ).json()["access_token"]

    resp = httpx.get(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        params={
            "q": "DDR4 ECC RDIMM",
            "filter": "buyingOptions:{FIXED_PRICE},price:[15..3000],priceCurrency:EUR",
            "sort": "newlyListed",
            "limit": "50",
        },
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
            "X-EBAY-C-ENDUSERCTX": f"contextualLocation=country=FR,zip={zip_code}",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    OUT.write_text(json.dumps(body, indent=2, ensure_ascii=False))
    cats = {
        c["categoryId"]
        for item in body.get("itemSummaries", [])
        for c in item.get("categories", [])
    }
    print(f"OK — {body.get('total')} résultats, catégories vues : {sorted(cats)}")
    print(f"sauvegardé : {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
