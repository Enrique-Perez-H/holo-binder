#!/usr/bin/env python3
"""Data for the Discover tab: the latest sets of each language, with prices and chase numbers.

For the newest sets (by release date) this collects, from TCGdex and Cardmarket's price guide:
booster box price, the price of every card, the top 3 cards, how concentrated the value is,
and the Pokémon that carry the set. The app turns these numbers into a ranking.

Output: discover.json (read by the app). discover-cache.json keeps what never changes (release
dates, Cardmarket IDs, Pokémon numbers, English names) so daily runs only read the price guide.
Usage: build_discover.py [guide.json]   (a local guide file is for testing)
"""
import concurrent.futures
import datetime
import json
import pathlib
import re
import sys
import urllib.parse

import update_prices as up

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "discover.json"
CACHE = ROOT / "discover-cache.json"
LANGS = ("ja", "en")
N_SETS = 10
MIN_CARDS = 40
SKIP_NAME = re.compile(r"promo|black star|trainer kit|mcdonald|starter|deck|battle academy|collection file|gift|campaign|デッキ|プロモ|スターター|ファイル|キャンペーン|ギフト|BOX|ボックス|セット", re.I)
SKIP_ID = re.compile(r"(^|-)p$|^tk|^mcd|^mep$|^svp$|^swshp$|^smp$|^xyp$|^bwp$|^MC$|^SV[KL]|^CS|^SMP|-P$", re.I)
# "Mega Rayquaza ex" -> "Rayquaza"
SUFFIX = re.compile(r"(\s|-)(ex|EX|V|VMAX|VSTAR|GX|BREAK|Star|δ)$")
PREFIX = re.compile(r"^(Mega |M |Radiant |Dark |Light |Alolan |Galarian |Hisuian |Paldean |Team Rocket's |Origin Forme |Terastal )")
STANDARD_BOX = re.compile(r"Deluxe|Enhanced|Special|Case|Bundle")
SPRITE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/%d.png"


def tcgdex(path):
    return up.fetch_json(up.TCGDEX % tuple(path.split("/", 1)))


def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"releases": {}, "cards": {}, "names": {}}


def pokemon_name(card_name):
    name = card_name.split(" [")[0].strip()
    mega = name.startswith("Mega ")
    for _ in range(3):
        name = PREFIX.sub("", name)
        name = SUFFIX.sub("", name).strip()
    return re.sub(r" [XY]$", "", name) if mega else name


def find_recent(lang, cache, today):
    """The newest real sets: not promos or decks, with enough cards."""
    listing = tcgdex(f"{lang}/sets")
    dates = cache["releases"].setdefault(lang, {})
    todo = [s["id"] for s in listing if s["id"] not in dates]

    def release(set_id):
        try:
            d = tcgdex(f"{lang}/sets/" + urllib.parse.quote(set_id))
            return set_id, (d.get("releaseDate") or "") + "|" + (d.get("serie") or {}).get("id", "")
        except Exception:
            return set_id, None

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        for set_id, date in pool.map(release, todo):
            if date is not None:
                dates[set_id] = date
    when = lambda sid: dates.get(sid, "|").split("|")[0]
    ok = [s for s in listing if when(s["id"]) and when(s["id"]) <= today and not dates[s["id"]].endswith("|tcgp")  # TCG Pocket is digital
          and (s.get("cardCount") or {}).get("total", 0) >= MIN_CARDS
          and not SKIP_NAME.search(s["name"]) and not SKIP_ID.search(s["id"])]
    ok.sort(key=lambda s: when(s["id"]), reverse=True)
    return ok[:N_SETS]


def load_cards(lang, set_id, cache):
    """Card list of a set with Cardmarket id, Pokémon number and rarity (looked up once per card)."""
    cards = tcgdex(f"{lang}/sets/" + urllib.parse.quote(set_id)).get("cards", [])
    known = cache["cards"].setdefault(lang, {})

    def detail(card):
        if card["id"] in known and known[card["id"]].get("pid"):
            return
        try:
            d = tcgdex(f"{lang}/cards/" + urllib.parse.quote(card["id"]))
        except Exception:
            return
        cm = (d.get("pricing") or {}).get("cardmarket") or {}
        known[card["id"]] = {"pid": cm.get("idProduct"), "dex": (d.get("dexId") or [None])[0], "rar": d.get("rarity"), "cat": d.get("category")}

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        list(pool.map(detail, cards))
    return cards


def main(guide_source=up.GUIDE_URL):
    today = datetime.date.today().isoformat()
    cache = load_cache()
    guide = up.fetch_json(guide_source) if guide_source.startswith("http") else json.loads(pathlib.Path(guide_source).read_text(encoding="utf-8"))
    by_id = {str(g["idProduct"]): g for g in guide.get("priceGuides", [])}
    date = guide.get("createdAt", "")[:10] or today

    chosen, cards_of = {}, {}
    for lang in LANGS:
        try:
            chosen[lang] = find_recent(lang, cache, today)
            for s in chosen[lang]:
                cards_of[(lang, s["id"])] = load_cards(lang, s["id"], cache)
        except Exception as e:
            print(f"{lang}: couldn't read the set list ({e})")
            chosen[lang] = []

    # boxes: same lookup as the price job (expansion from the cards' Cardmarket ids)
    set_ids = {f"{lang}:{sid}": [cache["cards"][lang][c["id"]]["pid"] for c in cs if cache["cards"].get(lang, {}).get(c["id"], {}).get("pid")]
               for (lang, sid), cs in cards_of.items()}
    boxes = {}
    try:
        up.find_boxes(set_ids, boxes, date)
    except Exception as e:
        print(f"Couldn't look up booster boxes: {e}")

    # English card names come from Cardmarket's product list (names there are English for every language)
    names = cache["names"]
    need = {str(c["pid"]) for lang_cards in cache["cards"].values() for c in lang_cards.values() if c.get("pid")} - set(names)
    if need:
        try:
            for p in up.fetch_json(up.CATALOG % "singles")["products"]:
                if str(p["idProduct"]) in need:
                    names[str(p["idProduct"])] = p["name"]
        except Exception as e:
            print(f"Couldn't read Cardmarket's product list: {e}")

    out = {"updated": date, "sets": {}}
    for lang in LANGS:
        sets = []
        for s in chosen[lang]:
            key = f"{lang}:{s['id']}"
            cards = []
            for c in cards_of[(lang, s["id"])]:
                info = cache["cards"].get(lang, {}).get(c["id"], {})
                g = by_id.get(str(info.get("pid"))) if info.get("pid") else None
                price = next((v for v in (up.pick(g, "trend"), up.pick(g, "avg"), up.pick(g, "low")) if v), None) if g else None
                cards.append({"id": c["id"], "n": c["localId"], "name": c["name"], "en": names.get(str(info.get("pid")), "").split(" [")[0],
                              "image": c.get("image"), "rar": info.get("rar"), "cat": info.get("cat"), "dex": info.get("dex"), "price": price})
            priced = sorted((c for c in cards if c["price"]), key=lambda c: -c["price"])
            total = sum(c["price"] for c in priced)
            top = [{k: c[k] for k in ("id", "n", "name", "en", "image", "rar", "price")} for c in priced[:3]]
            mons = {}
            for c in priced:
                if c["cat"] not in (None, "Pokemon"):
                    continue
                label = pokemon_name(c["en"]) if c["en"] else c["name"]
                m = mons.setdefault(c["dex"] or label, {"name": label, "dex": c["dex"], "value": 0, "cards": 0, "best": 0})
                m["value"] += c["price"]; m["cards"] += 1; m["best"] = max(m["best"], c["price"])
            featured = sorted(mons.values(), key=lambda m: -m["value"])[:6]
            for m in featured:
                m["value"] = round(m["value"], 2); m["best"] = round(m["best"], 2)
                m["sprite"] = SPRITE % m["dex"] if m["dex"] else None
            box_entry = boxes.get(key) or {}
            box_prices = []
            for pid, name in (box_entry.get("products") or {}).items():
                g = by_id.get(pid)
                p = next((v for v in (up.pick(g, "trend"), up.pick(g, "avg"), up.pick(g, "low")) if v), None) if g else None
                if p:
                    box_prices.append({"name": name, "price": p})
            # the normal box: skip deluxe/enhanced/case versions, and prefer the full-size one over "(18 Boosters)"
            box_prices = [b for b in box_prices if not STANDARD_BOX.search(b["name"])]
            box_prices.sort(key=lambda b: ("(" in b["name"], b["price"]))
            share = lambda n: round(sum(c["price"] for c in priced[:n]) / total, 4) if total else None
            sets.append({
                "id": s["id"], "name": s["name"], "releaseDate": cache["releases"][lang][s["id"]].split("|")[0],
                "cards": len(cards), "priced": len(priced), "total": round(total, 2),
                "box": box_prices[0] if box_prices else None,
                "cmName": re.sub(r" Booster Box.*$", "", box_prices[0]["name"]) if box_prices else None,
                "top": top, "top1": share(1), "top3": share(3), "top10": share(10),
                "median": round(priced[len(priced) // 2]["price"], 2) if priced else None,
                "hits20": sum(1 for c in priced if c["price"] >= 20),
                "featured": featured,
            })
        out["sets"][lang] = sets
        print(f"{lang}: " + ", ".join(f"{x['id']} ({x['releaseDate']})" for x in sets))

    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(f"Wrote {OUT.name} ({OUT.stat().st_size // 1024} KB) and {CACHE.name} ({CACHE.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(*sys.argv[1:])
