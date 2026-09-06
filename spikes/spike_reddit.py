"""Spike Reddit — jetable. OAuth « script » + stabilité du format de titre.

    REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=... REDDIT_USER_AGENT=... \
        python spikes/spike_reddit.py
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys

import httpx

OUT = pathlib.Path("tests/fixtures/payloads/reddit_new.json")
_HW = re.compile(r"\[H\].*?\[W\]", re.IGNORECASE | re.DOTALL)


def main() -> int:
    ua = os.environ["REDDIT_USER_AGENT"]
    token = httpx.post(
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        auth=(os.environ["REDDIT_CLIENT_ID"], os.environ["REDDIT_CLIENT_SECRET"]),
        headers={"User-Agent": ua},
    ).json()["access_token"]

    resp = httpx.get(
        "https://oauth.reddit.com/r/homelabsales/new",
        params={"limit": "100"},
        headers={"Authorization": f"Bearer {token}", "User-Agent": ua},
    )
    resp.raise_for_status()
    body = resp.json()
    OUT.write_text(json.dumps(body, indent=2))
    titles = [c["data"]["title"] for c in body["data"]["children"]]
    hw = sum(1 for t in titles if _HW.search(t))
    print(f"OK — {len(titles)} annonces, {hw} au format [H]…[W]")
    print(f"sauvegardé : {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
