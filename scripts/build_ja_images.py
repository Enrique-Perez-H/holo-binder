#!/usr/bin/env python3
"""Builds ja-images.json: card images for Japanese sets that TCGdex has no pictures for.

The official Pokémon Card site (pokemon-card.com) lists every Japanese card, newest set first,
but its API can't filter by set. This walks the first pages of that list, groups cards by the
set folder in the image path, and matches them to TCGdex's card list for the same set by order
and name. Only sets where almost every name matches are written.

Usage: build_ja_images.py [pages] [official_cache.json]
Output format: {"M6": {"001": "M6/050613_P_TAMATAMA.jpg", ...}, ...}
The app prefixes https://www.pokemon-card.com/assets/images/card_images/large/ to each path.
"""
import collections
import difflib
import json
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "ja-images.json"
SEARCH = ("https://www.pokemon-card.com/card-search/resultAPI.php?keyword=&se_ta=&regulation_sidebar_form=all"
          "&pg=&illust=&sm_and_keyword=true&page=%d")
TCGDEX = "https://api.tcgdex.net/v2/ja/sets/"
MIN_MATCH = 0.85


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "holo-binder-image-index"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def norm(name):
    return "".join(name.split()).replace("　", "")


def main(pages=200, cache=None):
    if cache:
        official = json.loads(pathlib.Path(cache).read_text(encoding="utf-8"))
    else:
        official = []
        for page in range(1, int(pages) + 1):
            official += get(SEARCH % page)["cardList"]
            time.sleep(0.3)

    folders = collections.OrderedDict()
    for c in official:
        folder = c["cardThumbFile"].split("/")[-2]
        folders.setdefault(folder, []).append(c)

    result = {}
    for folder, cards in folders.items():
        try:
            tcg = get(TCGDEX + folder)
        except Exception:
            continue
        theirs = tcg.get("cards", [])
        if not theirs or any(c.get("image") for c in theirs):
            continue  # TCGdex already has pictures for this set
        cards = sorted(cards, key=lambda c: int(c["cardID"]))
        if len(cards) < len(theirs) * 0.9:
            print(f"{folder}: only {len(cards)} of {len(theirs)} cards found, skipped")
            continue
        # Align by name so a few cards missing on one side don't shift everything after them.
        sm = difflib.SequenceMatcher(None, [norm(c["name"]) for c in theirs], [norm(c["cardNameAltText"]) for c in cards], autojunk=False)
        pairs = {}
        for blk in sm.get_matching_blocks():
            for i in range(blk.size):
                pairs[theirs[blk.a + i]["localId"]] = "/".join(cards[blk.b + i]["cardThumbFile"].split("/")[-2:])
        ratio = len(pairs) / len(theirs)
        print(f"{folder}: {len(cards)} official / {len(theirs)} TCGdex, {ratio:.0%} matched")
        if ratio < MIN_MATCH:
            continue
        result[folder] = pairs

    OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(result)} sets to {OUT.name}")


if __name__ == "__main__":
    main(*sys.argv[1:])
