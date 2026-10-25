#!/usr/bin/env python3
"""Daily Cardmarket price snapshot for Holo Binder.

Reads collection.json (pushed by the app), downloads Cardmarket's public
Pokémon price guide, and appends one row per tracked card to history.json.
Row format matches the app: [date, trend, avg, low, avg7, avg30, reverse_trend].
"""
import json
import pathlib
import sys
import urllib.request

GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"
ROOT = pathlib.Path(__file__).resolve().parent.parent
COLLECTION = ROOT / "collection.json"
HISTORY = ROOT / "history.json"
KEEP_DAYS = 730


def pick(guide, field):
    """Same rule as the app: use the normal price, fall back to the holo price."""
    value = guide.get(field)
    return value if value is not None else guide.get(field + "-holo")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def main(guide_source=GUIDE_URL):
    collection = load_json(COLLECTION, None)
    if not collection:
        print("No collection.json yet. Connect the app to this repo first.")
        return 0

    ids = {str(c["cm"]) for c in collection.get("cards", {}).values() if c.get("cm")}
    if not ids:
        print("No tracked cards with a Cardmarket ID yet.")
        return 0

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
        if g.get("trend") is not None or g.get("avg") is not None or g.get("low") is not None:
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
