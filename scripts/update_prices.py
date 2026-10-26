#!/usr/bin/env python3
"""Daily Cardmarket price snapshot for Holo Binder.

Reads collection.json (pushed by the app), downloads Cardmarket's public
Pokémon price guide, and appends one row per tracked card to history.json.
Row format matches the app: [date, trend, avg, low, avg7, avg30, reverse_trend].

It also tracks the booster box of every set in the collection. The set's Cardmarket expansion is
found from the Cardmarket IDs of its cards, the boxes are looked up in Cardmarket's product list,
and their prices go into the same history under history["boxes"] (set -> box names and IDs).
"""
import datetime
import json
import pathlib
import re
import sys
import urllib.request

GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"
ROOT = pathlib.Path(__file__).resolve().parent.parent
COLLECTION = ROOT / "collection.json"
HISTORY = ROOT / "history.json"
KEEP_DAYS = 730
CATALOG = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_%s_6.json"
BOX_CATEGORY = 53  # "Pokémon Display"
BOX_NAME = re.compile(r"Booster Box( \(\d+ Boosters?\))?$")
RECHECK_DAYS = 7


def pick(guide, field):
    """Same rule as the app: use the normal price, fall back to the holo price."""
    value = guide.get(field)
    return value if value is not None else guide.get(field + "-holo")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "holo-binder-price-bot"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def set_keys(collection):
    """{"ja:M6": [cardmarket ids of its cards], ...} for every set that has a card in the collection."""
    sets = {}
    for key, card in collection.get("cards", {}).items():
        set_id = card.get("setId")
        if set_id and card.get("cm"):
            sets.setdefault(key.split(":")[0] + ":" + set_id, []).append(card["cm"])
    return sets


def find_boxes(sets, boxes, date):
    """Fill in boxes[set_key] for sets we haven't looked up yet (or looked up a week ago without luck)."""
    todo = {}
    for key, ids in sets.items():
        old = boxes.get(key)
        stale = old and not old.get("products") and (
            old.get("cards") != len(ids) or _days_between(old.get("checked", date), date) >= RECHECK_DAYS)
        if not old or stale:
            todo[key] = ids
    if not todo:
        return
    singles = {p["idProduct"]: p["idExpansion"] for p in fetch_json(CATALOG % "singles")["products"]}
    sealed = fetch_json(CATALOG % "nonsingles")["products"]
    for key, ids in todo.items():
        counts = {}
        for pid in ids:
            exp = singles.get(pid)
            if exp:
                counts[exp] = counts.get(exp, 0) + 1
        expansion = max(counts, key=counts.get) if counts else None
        # Prices are per language because each language's cards belong to their own Cardmarket expansion
        # (e.g. "Black Bolt JP Booster Box"). A stray card (such as a promo) must not decide the expansion.
        if expansion and counts[expansion] < len(ids) / 2:
            print(f"{key}: no clear Cardmarket expansion ({counts}), skipped")
            expansion = None
        products = {
            str(p["idProduct"]): p["name"]
            for p in sealed
            if expansion and p["idExpansion"] == expansion and p["idCategory"] == BOX_CATEGORY
            and BOX_NAME.search(p["name"]) and "Jumbo" not in p["name"]
        }
        boxes[key] = {"expansion": expansion, "products": products, "checked": date, "cards": len(ids)}
        print(f"{key}: expansion {expansion}, boxes: {', '.join(products.values()) or 'none found'}")


def _days_between(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def main(guide_source=GUIDE_URL):
    collection = load_json(COLLECTION, None)
    if not collection:
        print("No collection.json yet. Connect the app to this repo first.")
        return 0

    ids = {str(c["cm"]) for c in collection.get("cards", {}).values() if c.get("cm")}
    if not ids:
        print("No tracked cards with a Cardmarket ID yet.")
        return 0
    sets = set_keys(collection)

    if guide_source.startswith("http"):
        req = urllib.request.Request(guide_source, headers={"User-Agent": "holo-binder-price-bot"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            guide = json.load(resp)
    else:
        guide = json.loads(pathlib.Path(guide_source).read_text(encoding="utf-8"))

    date = guide.get("createdAt", "")[:10]
    by_id = {str(g["idProduct"]): g for g in guide.get("priceGuides", [])}

    history = load_json(HISTORY, {"products": {}})
    products = history.setdefault("products", {})
    boxes = history.setdefault("boxes", {})
    try:
        find_boxes(sets, boxes, date)
    except Exception as e:  # box tracking must never stop the card prices
        print(f"Couldn't look up booster boxes: {e}")
    for key in list(boxes):
        if key not in sets:
            del boxes[key]
    box_ids = {pid for entry in boxes.values() for pid in entry.get("products", {})}
    ids |= box_ids
    written = missing = 0
    for pid in sorted(ids):
        g = by_id.get(pid)
        if not g:
            missing += 1
            continue
        trend, avg, low = pick(g, "trend"), pick(g, "avg"), pick(g, "low")
        main_price = next((v for v in (trend, avg, low) if v is not None), None)
        if main_price is None:
            missing += 1
            continue
        rev = None
        if pid not in box_ids and (g.get("trend") is not None or g.get("avg") is not None or g.get("low") is not None):
            # With a normal price present, the "-holo" fields are the reverse holo price.
            rev = next((g.get(f + "-holo") for f in ("trend", "avg", "low") if g.get(f + "-holo") is not None), None)
        row = [date, main_price, avg, low, pick(g, "avg7"), pick(g, "avg30"), rev]
        rows = products.setdefault(pid, [])
        if rows and rows[-1][0] == date:
            rows[-1] = row
        else:
            rows.append(row)
        del rows[:-KEEP_DAYS]
        written += 1

    history["updated"] = date
    history["source"] = "Cardmarket price guide"
    HISTORY.write_text(json.dumps(history, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(f"{date}: saved {written} cards, {missing} without a Cardmarket price.")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
