#!/usr/bin/env python3
"""
wow_price.py - Look up current World of Warcraft auction house prices
using Blizzard's official Game Data API.

Defaults to WoW: Forever. Use --game retail for regular retail WoW.

Usage:
    python wow_price.py "Copper Ore"                     # WoW: Forever (default)
    python wow_price.py 2770                             # look up by item ID instead of name
    python wow_price.py "Copper Ore" --game retail       # retail WoW
    python wow_price.py "Some Sword" --game retail --realm area-52

Setup (one time):
    1. Create a client at https://develop.battle.net/access/clients
    2. Run this script once - it asks for the Client ID and Secret and saves them
       to wow_price_config.json next to the script.

Notes on WoW: Forever:
    - Forever has no realms. Its auction data is split into numbered auction houses
      (shared across all rulesets), and this script checks all of them and shows each
      house that has the item.
    - Blizzard hasn't officially documented Forever's API yet (support went live in
      early November 2026), so endpoints may change. If lookups suddenly break,
      that's the likely reason.
    - Data refreshes about hourly; the script caches snapshots for 60 minutes.
"""

import argparse
import base64
import csv
import json
import os
import re
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime

if getattr(sys, "frozen", False):
    # Packaged .exe: keep user data next to the exe; bundled files live in _MEIPASS.
    HERE = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, "_MEIPASS", HERE)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = HERE

# Ship these read-mostly lookup tables with the exe; copy them out on first run.
for _seed in ("item_info.json", "item_stats.json", "item_cache.json"):
    _src, _dst = os.path.join(BUNDLE_DIR, _seed), os.path.join(HERE, _seed)
    if _src != _dst and os.path.exists(_src) and not os.path.exists(_dst):
        try:
            import shutil
            shutil.copyfile(_src, _dst)
        except OSError:
            pass

CONFIG_PATH = os.path.join(HERE, "wow_price_config.json")
CACHE_DIR = os.path.join(HERE, ".wow_price_cache")
CACHE_SECONDS = 60 * 60

# Forever: every ruleset returns the same auction houses, so one is enough.
FOREVER_RULESET = 2
FOREVER_FALLBACK_HOUSES = [110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 123, 124, 125]


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


# ---------- helpers ----------

def fmt_gold(copper):
    copper = int(round(copper))
    g, rem = divmod(copper, 10000)
    s, c = divmod(rem, 100)
    parts = []
    if g:
        parts.append(f"{g:,}g")
    if s or g:
        parts.append(f"{s}s")
    parts.append(f"{c}c")
    return " ".join(parts)


def http_json(url, headers=None, data=None):
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise ApiError(e.code, f"Blizzard API error {e.code} for {url.split('?')[0]}\n{body}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not reach Blizzard API: {e.reason}")


def load_credentials():
    cid = os.environ.get("BLIZZARD_CLIENT_ID")
    secret = os.environ.get("BLIZZARD_CLIENT_SECRET")
    if cid and secret:
        return cid, secret
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return cfg["client_id"], cfg["client_secret"]
    if sys.stdin is None or not sys.stdin.isatty():
        raise SystemExit("No Blizzard API credentials found. Restart the app to enter them.")
    print("No Blizzard API credentials found.")
    print("Create a client at https://develop.battle.net/access/clients, then paste below.")
    cid = input("Client ID: ").strip()
    secret = input("Client Secret: ").strip()
    with open(CONFIG_PATH, "w") as f:
        json.dump({"client_id": cid, "client_secret": secret}, f)
    print(f"Saved to {CONFIG_PATH}\n")
    return cid, secret


def has_credentials():
    if os.environ.get("BLIZZARD_CLIENT_ID") and os.environ.get("BLIZZARD_CLIENT_SECRET"):
        return True
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return bool(cfg.get("client_id") and cfg.get("client_secret"))
    except (OSError, ValueError):
        return False


def save_credentials(cid, secret):
    with open(CONFIG_PATH, "w") as f:
        json.dump({"client_id": cid.strip(), "client_secret": secret.strip()}, f)


def get_token(cid, secret):
    cache = os.path.join(CACHE_DIR, "token.json")
    if os.path.exists(cache):
        with open(cache) as f:
            tok = json.load(f)
        if tok.get("expires_at", 0) > time.time() + 60:
            return tok["access_token"]
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    try:
        resp = http_json(
            "https://oauth.battle.net/token",
            headers={"Authorization": f"Basic {auth}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data=b"grant_type=client_credentials",
        )
    except ApiError as e:
        raise SystemExit(f"Login to Blizzard API failed - check your Client ID/Secret.\n{e}")
    tok = {"access_token": resp["access_token"],
           "expires_at": time.time() + resp.get("expires_in", 3600)}
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache, "w") as f:
        json.dump(tok, f)
    return tok["access_token"]


class Blizz:
    def __init__(self, token, region, game):
        self.token = token
        self.region = region
        self.game = game
        self.base = f"https://{region}.api.blizzard.com"
        self.snapshot_time = int(time.time())

    def ns(self, kind):
        if self.game == "forever":
            return f"{kind}-forever-{self.region}"
        return f"{kind}-{self.region}"

    def get(self, path, kind, **params):
        params = {"namespace": self.ns(kind), "locale": "en_US", **params}
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        return http_json(url, headers={"Authorization": f"Bearer {self.token}"})

    def cached(self, key, fetch):
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, f"{self.game}_{self.region}_{key}.json")
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_SECONDS:
            self.snapshot_time = int(os.path.getmtime(path))
            with open(path) as f:
                return json.load(f)
        print(f"Downloading fresh auction snapshot ({key})... this can take a moment.")
        data = fetch()
        with open(path, "w") as f:
            json.dump(data, f)
        self.snapshot_time = int(time.time())
        return data


# ---------- item lookup ----------

def norm_name(text):
    """Item names compared the same way everywhere: case, spacing and curly apostrophes ignored."""
    return " ".join((text or "").replace("\u2019", "'").replace("\u2018", "'").lower().split())


def _known_matches(game, words):
    """(id, name) for items the app has already seen whose name contains every word."""
    out = []
    for key, info in _info_cache().items():
        g, _, iid = key.partition(":")
        name = info.get("name")
        if g == game and iid.isdigit() and name and all(w in norm_name(name) for w in words):
            out.append((int(iid), name))
    return out


def find_items(api, query, class_id=None, subclass_id=None):
    """Return list of (id, name). Accepts an item name or a numeric item ID,
    optionally limited to one auction-house category.

    Blizzard's name search matches ANY word of the query and returns the lowest item IDs first,
    so "Heavy Leather" brings back every leather item and the real one can be pages down. This
    reads further pages until the exact name turns up, then keeps only names that contain every
    word typed (falling back to the loose matches when nothing does)."""
    query = " ".join(query.replace("\u2019", "'").replace("\u2018", "'").split())
    if query.isdigit():
        item_id = int(query)
        try:
            d = api.get(f"/data/wow/item/{item_id}", "static")
            info = remember_info(api.game, item_id, d)
            return [(item_id, info["name"] or f"Item {item_id}")]
        except ApiError:
            return [(item_id, cached_info(api.game, item_id).get("name") or f"Item {item_id}")]

    want, words = norm_name(query), norm_name(query).split()
    params = {"name.en_US": query, "orderby": "id", "_pageSize": 1000}
    if class_id is not None:
        params["item_class.id"] = class_id
    if subclass_id is not None:
        params["item_subclass.id"] = subclass_id
    items, seen, page, max_pages = [], set(), 1, 3
    while page <= max_pages:
        try:
            res = api.get("/data/wow/search/item", "static", **params, _page=page)
        except ApiError as e:
            if page == 1 and params["_pageSize"] == 1000:
                params["_pageSize"] = 100            # some API versions cap the page size
                continue
            if page > 1:
                break
            raise SystemExit(
                "Item name search isn't working for this game's data right now.\n"
                "Look up the item ID instead (e.g. search the item on Wowhead - the number in "
                "the page address) and enter that number.\n"
                f"({e.code})")
        results = res.get("results", [])
        if page == 1 and len(results) <= 100:
            max_pages = 6                            # small pages: allow a few more of them
        for r in results:
            d = r.get("data", {})
            nm = _loc(d.get("name"))
            if nm and d.get("id") not in seen:
                seen.add(d["id"])
                items.append((d["id"], nm))
                remember_info(api.game, d["id"], d, save=False)
        if any(norm_name(n) == want for _i, n in items) or page >= (res.get("pageCount") or 1) \
                or len(results) < 100:
            break
        page += 1
    save_info()
    if class_id is None:                             # plus anything already known locally
        for iid, nm in _known_matches(api.game, words):
            if iid not in seen:
                seen.add(iid)
                items.append((iid, nm))
    exact = [i for i in items if norm_name(i[1]) == want]
    if exact:
        return exact
    every = [i for i in items if all(w in norm_name(i[1]) for w in words)]
    return every or items[:200]


# ---------- item categories (same as the in-game auction house) ----------

ITEM_INFO_PATH = os.path.join(HERE, "item_info.json")
CATEGORY_SECONDS = 7 * 86400
_info = None


def _loc(x):
    return x.get("en_US") if isinstance(x, dict) else x


def _info_cache():
    global _info
    if _info is None:
        _info = load_json(ITEM_INFO_PATH, {})
    return _info


def save_info():
    with open(ITEM_INFO_PATH, "w") as f:
        json.dump(_info_cache(), f)


def remember_info(game, item_id, data, save=True, cls=None, sub=None):
    """Store an item's name and auction-house category from Blizzard item data."""
    c = data.get("item_class") or {}
    sc = data.get("item_subclass") or {}
    q = data.get("quality") or {}
    info = {"name": _loc(data.get("name")),
            "cls": _loc(c.get("name")) or cls, "sub": _loc(sc.get("name")) or sub,
            "q": q.get("type") if isinstance(q, dict) else None,
            "lvl": data.get("level"), "req": data.get("required_level"),
            "buy": data.get("purchase_price"), "vsell": data.get("sell_price")}
    _info_cache()[f"{game}:{item_id}"] = info
    if save:
        save_info()
    return info


def cached_info(game, item_id):
    return _info_cache().get(f"{game}:{item_id}") or {}


def item_info(api, item_id):
    """Category info for one item, fetched from Blizzard the first time."""
    info = cached_info(api.game, item_id)
    if info.get("cls") and "q" in info:
        return info
    try:
        return remember_info(api.game, item_id, api.get(f"/data/wow/item/{item_id}", "static"))
    except ApiError:
        return info


def category_label(cls, sub):
    if not cls:
        return "Uncategorized"
    return f"{cls} \u203a {sub}" if sub and sub != cls else cls


def get_categories(api):
    """[{'id', 'name', 'subs': [{'id', 'name'}]}] straight from Blizzard, cached for a week."""
    path = os.path.join(CACHE_DIR, f"{api.game}_{api.region}_categories.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CATEGORY_SECONDS:
        return load_json(path, [])
    idx = api.get("/data/wow/item-class/index", "static")
    cats = []
    for c in idx.get("item_classes", []):
        try:
            d = api.get(f"/data/wow/item-class/{c['id']}", "static")
            subs = [{"id": sc["id"], "name": _loc(sc.get("name"))} for sc in d.get("item_subclasses", [])]
        except ApiError:
            subs = []
        cats.append({"id": c["id"], "name": _loc(c.get("name")),
                     "subs": sorted(subs, key=lambda x: x["name"] or "")})
    cats.sort(key=lambda c: c["name"] or "")
    os.makedirs(CACHE_DIR, exist_ok=True)
    save_json(path, cats)
    return cats


def category_members(api, class_id, subclass_id=None, cls_name=None, sub_name=None, max_pages=10):
    """Every item in a category as (id, name), cached for a week."""
    key = f"{api.game}_{api.region}_cat2_{class_id}_{subclass_id}"
    path = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CATEGORY_SECONDS:
        return [tuple(x) for x in load_json(path, [])]
    params = {"item_class.id": class_id, "orderby": "id", "_pageSize": 1000}
    if subclass_id is not None:
        params["item_subclass.id"] = subclass_id
    members, page = [], 1
    while page <= max_pages:
        try:
            res = api.get("/data/wow/search/item", "static", **params, _page=page)
        except ApiError:
            if params["_pageSize"] == 1000 and page == 1:
                params["_pageSize"] = 100        # some API versions cap page size
                continue
            raise
        for r in res.get("results", []):
            d = r.get("data", {})
            nm = _loc(d.get("name"))
            if nm:
                members.append((d["id"], nm))
                remember_info(api.game, d["id"], d, save=False, cls=cls_name,
                              sub=sub_name if subclass_id is not None else None)
        if page >= (res.get("pageCount") or 1):
            break
        page += 1
    save_info()
    os.makedirs(CACHE_DIR, exist_ok=True)
    save_json(path, members)
    return members


QUALITIES = ["POOR", "COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "ARTIFACT", "HEIRLOOM"]


def quality_rank(q):
    return QUALITIES.index(q) if q in QUALITIES else None


# ---------- auction data ----------

def add_listings(book, auctions):
    for a in auctions or []:
        if not isinstance(a, dict):
            continue
        price = _val(a.get("unit_price")) or _val(a.get("buyout"))
        iid = _d(a.get("item")).get("id")
        if price and iid:
            book.setdefault(iid, []).append((price, _val(a.get("quantity")) or 1))


def retail_sources(api, realm):
    sources = []
    data = api.cached("commodities", lambda: api.get("/data/wow/auctions/commodities", "dynamic"))
    book = {}
    add_listings(book, data.get("auctions"))
    sources.append(("Region-wide commodity AH", book))
    if realm:
        r = api.get(f"/data/wow/realm/{realm}", "dynamic")
        cr_id = int(r["connected_realm"]["href"].split("/connected-realm/")[1].split("?")[0])
        data = api.cached(f"realm_{cr_id}",
                          lambda: api.get(f"/data/wow/connected-realm/{cr_id}/auctions", "dynamic"))
        book = {}
        add_listings(book, data.get("auctions"))
        api.gear_ids = set(book)
        sources.append((f"Realm AH ({realm})", book))
    return sources


def forever_house_list(api):
    base = f"/data/wow/ruleset/{FOREVER_RULESET}/auctions/"
    try:
        idx = api.get(base, "dynamic")
    except ApiError:
        return [(h, f"Auction house {h}") for h in FOREVER_FALLBACK_HOUSES]
    houses = []
    for key in ("auctions", "auction_houses", "houses", "results"):
        if isinstance(idx.get(key), list):
            for h in idx[key]:
                if isinstance(h, dict) and "id" in h:
                    name = h.get("name")
                    name = name.get("en_US") if isinstance(name, dict) else name
                    houses.append((h["id"], name or f"Auction house {h['id']}"))
            break
    return houses or [(h, f"Auction house {h}") for h in FOREVER_FALLBACK_HOUSES]


_forever_memo = {}      # region -> (snapshot time, sources, gear ids): skip re-reading the big file


def forever_sources(api):
    path = os.path.join(CACHE_DIR, f"{api.game}_{api.region}_forever_all_houses_v5.json")
    memo = _forever_memo.get(api.region)
    try:
        mtime = int(os.path.getmtime(path))
    except OSError:
        mtime = None
    if memo and mtime == memo[0] and time.time() - mtime < CACHE_SECONDS:
        api.snapshot_time, api.gear_ids = memo[0], memo[2]
        return memo[1]

    def fetch_all():
        base = f"/data/wow/ruleset/{FOREVER_RULESET}/auctions"

        def one(house):
            hid, name = house
            listings, seen, gear = [], set(), set()

            def add(lst):
                if not isinstance(lst, list):      # e.g. {"href": ...} links, not listings
                    return
                for a in lst:
                    if not isinstance(a, dict):
                        continue
                    aid = a.get("id")
                    if aid is not None:
                        if aid in seen:
                            continue
                        seen.add(aid)
                    listings.append(a)
                    if "unit_price" not in a:          # gear is priced by buyout
                        gear.add(_d(a.get("item")).get("id"))

            try:
                d = api.get(f"{base}/{hid}", "dynamic")
            except ApiError:
                d = {}
            add(d.get("auctions"))
            add(d.get("commodities"))
            # The house call returns gear only, plus a *link* to the stackables
            # (ore, herbs, cloth, potions) at /{house}/commodities, whose listings
            # come back under "auctions". Decide by what actually arrived.
            has_stack = any("unit_price" in a for a in listings)
            has_gear = any("unit_price" not in a for a in listings)
            if not has_stack:
                try:
                    c = api.get(f"{base}/{hid}/commodities", "dynamic")
                    add(c.get("commodities"))
                    add(c.get("auctions"))
                except ApiError:
                    pass
            if not has_gear:
                try:
                    g = api.get(f"{base}/{hid}/auctions", "dynamic")
                    add(g.get("auctions"))
                    add(g.get("commodities"))
                except ApiError:
                    pass
            gear.discard(None)
            return {"id": hid, "name": name, "auctions": listings, "gear": sorted(gear)}

        # the houses don't depend on each other, so ask for several at once
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(5) as ex:
            return list(ex.map(one, forever_house_list(api)))

    houses = api.cached("forever_all_houses_v5", fetch_all)
    api.gear_ids = {i for h in houses for i in h.get("gear", [])}
    counts = {}
    for h in houses:
        counts[h["name"]] = counts.get(h["name"], 0) + 1
    sources = []
    for h in houses:
        book = {}
        add_listings(book, h["auctions"])
        # several houses can share a name; add the number so they can be told apart
        label = f"{h['name']} #{h['id']}" if counts[h["name"]] > 1 else h["name"]
        sources.append((label, book))
    try:
        _forever_memo[api.region] = (int(os.path.getmtime(path)), sources, api.gear_ids)
    except OSError:
        pass
    return sources


def summarize(listings):
    listings = sorted(listings)
    total = sum(q for _, q in listings)
    lowest = listings[0][0]
    target = max(1, total * 0.10)
    acc, spent = 0, 0
    for price, qty in listings:
        take = min(qty, target - acc)
        acc += take
        spent += take * price
        if acc >= target:
            break
    weights = [max(0, min(int(q), 1000)) for _, q in listings]
    want, seen, median = (sum(weights) - 1) // 2, 0, lowest
    for (price, _q), w in zip(listings, weights):
        seen += w
        if seen > want:
            median = price
            break
    return {"lowest": lowest, "cheap10": spent / acc, "median": median,
            "quantity": total, "listings": len(listings)}


# ---------- structured search (used by the window app) ----------

def lookup_items(api, query, limit=None, class_id=None, subclass_id=None):
    """Every item matching the search, each with a combined price summary and a
    per-auction-house breakdown. Exact name matches first, then the busiest items."""
    items = find_items(api, query, class_id, subclass_id)
    res = {"query": query, "items": [], "total": len(items), "ts": None}
    if not items:
        return res
    sources = get_sources(api)
    res["ts"] = api.snapshot_time
    out = build_entries(api, sources, items)
    q = norm_name(query)
    out.sort(key=lambda e: (norm_name(e["name"]) != q, q not in norm_name(e["name"]), not e["found"],
                            -(e.get("quantity") or 0), e["name"]))
    # fill in categories the search didn't include, for the results people will see
    missing = [e for e in out[:limit] if not e.get("cls")][:15]
    for e in missing:
        info = item_info(api, e["id"])
        e["cls"], e["sub"] = info.get("cls"), info.get("sub")
    record_history(api.game, api.snapshot_time, [e for e in out if e["found"]])
    res["items"] = out[:limit] if limit else out
    return res


def build_entries(api, sources, items, only_listed=False):
    """Card data for each (id, name): combined summary, per-house breakdown, category."""
    out = []
    for item_id, name in items:
        houses, everything = [], []
        for label, book in sources:
            lst = book.get(item_id)
            if lst:
                houses.append({"label": label, **summarize(lst)})
                everything.extend(lst)
        if only_listed and not everything:
            continue
        houses.sort(key=lambda h: h["lowest"])
        info = cached_info(api.game, item_id)
        entry = {"id": item_id, "name": name, "houses": houses, "found": bool(everything),
                 "cls": info.get("cls"), "sub": info.get("sub"), "q": info.get("q"),
                 "lvl": info.get("lvl"), "req": info.get("req")}
        if everything:
            entry.update(summarize(everything))
        out.append(entry)
    return out


def browse_category(api, class_id, subclass_id=None, cls_name=None, sub_name=None):
    """Everything currently listed on the AH in one category, busiest first."""
    members = category_members(api, class_id, subclass_id, cls_name, sub_name)
    sources = get_sources(api)
    out = build_entries(api, sources, members, only_listed=True)
    for e in out:
        e["cls"] = e["cls"] or cls_name
        if subclass_id is not None:
            e["sub"] = e["sub"] or sub_name
    out.sort(key=lambda e: (-(e.get("quantity") or 0), e["name"]))
    record_history(api.game, api.snapshot_time, out)
    return {"query": category_label(cls_name, sub_name), "items": out, "total": len(out),
            "members": len(members), "ts": api.snapshot_time, "browse": True}


# ---------- watchlist ----------

WATCHLIST_PATH = os.path.join(HERE, "watchlist.json")


def load_watchlist():
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return []


def save_watchlist(entries):
    with open(WATCHLIST_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def connect(game="forever", region="us"):
    cid, secret = load_credentials()
    return Blizz(get_token(cid, secret), region, game)


def local_item(game, query):
    """{'id', 'name'} for an exact item name the app has already seen, else None."""
    found = [(i, n) for i, n in _known_matches(game, norm_name(query).split()) if norm_name(n) == norm_name(query)]
    return _pick(game, found)


def _pick(game, items):
    """One of several items sharing a name: the one on the auction house now, else the lowest ID."""
    if not items:
        return None
    memo = _forever_memo.get("us") if game == "forever" else None
    listed = [i for i in items if memo and any(i[0] in book for _l, book in memo[1])]
    item_id, name = min(listed or items)
    return {"id": item_id, "name": name}


def resolve_item(api, query):
    """Turn a name or ID into {'id', 'name'}; None if not found.
    A name must match exactly: a near miss would price a different item."""
    query = query.strip()
    if query.isdigit():
        items = find_items(api, query)
        return {"id": items[0][0], "name": items[0][1]} if items else None
    known = local_item(api.game, query)
    if known:
        return known
    return _pick(api.game, [i for i in find_items(api, query) if norm_name(i[1]) == norm_name(query)])


def get_sources(api, realm=None):
    return forever_sources(api) if api.game == "forever" else retail_sources(api, realm)


_summary_memo = [None, {}]      # [the sources it belongs to, {item id: summary}]


def item_summary(sources, item_id):
    """Combine an item's listings across every auction house. None if not listed.
    Remembered per price snapshot, so tables can ask again for free."""
    if _summary_memo[0] is not sources:
        _summary_memo[:] = [sources, {}]
    memo = _summary_memo[1]
    if item_id in memo:
        s = memo[item_id]
        return dict(s) if s else None
    listings, cheapest_house, cheapest = [], None, None
    for label, book in sources:
        for price, qty in book.get(item_id, []):
            listings.append((price, qty))
            if cheapest is None or price < cheapest:
                cheapest, cheapest_house = price, label
    s = {**summarize(listings), "house": cheapest_house} if listings else None
    memo[item_id] = s
    return dict(s) if s else None


def check_watchlist(api, entries, realm=None):
    """One row per watchlist entry, with Day/Week/Month trends. Also records history."""
    sources = get_sources(api, realm)
    ts = api.snapshot_time
    rows = []
    for e in entries:
        s = item_summary(sources, e["id"])
        info = e if e.get("cls") else item_info(api, e["id"])
        base = {"id": e["id"], "name": e["name"], "ts": ts,
                "cls": info.get("cls"), "sub": info.get("sub")}
        rows.append({**base, "found": True, **s} if s else {**base, "found": False})
    record_history(api.game, ts, rows)
    add_trends(api.game, ts, rows)
    return rows


def fmt_pct(p):
    return "  --" if p is None else f"{p:+.1f}%"


def format_watchlist(rows):
    if not rows:
        return "Your watchlist is empty."
    w = max(12, min(30, max(len(r["name"]) for r in rows)))
    out = [f"{'Item':<{w}}  {'Lowest':>12}  {'Market':>12}  {'Qty':>9}  {'Day':>7}  {'Week':>7}  {'Month':>7}",
           "-" * (w + 70)]
    for r in rows:
        name = r["name"][:w]
        if r["found"]:
            out.append(f"{name:<{w}}  {fmt_gold(r['lowest']):>12}  {fmt_gold(r['cheap10']):>12}  "
                       f"{r['quantity']:>9,}  {fmt_pct(r.get('day')):>7}  "
                       f"{fmt_pct(r.get('week')):>7}  {fmt_pct(r.get('month')):>7}")
        else:
            out.append(f"{name:<{w}}  {'not listed':>12}")
    return "\n".join(out)


# ---------- price history ----------

HISTORY_DB = os.path.join(HERE, "price_history.db")
PERIODS = {"day": 86400, "week": 7 * 86400, "month": 30 * 86400}


def _db():
    con = sqlite3.connect(HISTORY_DB, timeout=15)
    con.execute("""CREATE TABLE IF NOT EXISTS prices (
                     ts INTEGER, game TEXT, item_id INTEGER,
                     lowest INTEGER, market INTEGER, qty INTEGER,
                     PRIMARY KEY (game, item_id, ts))""")
    return con


def record_history(game, ts, rows):
    """Save one price point per item per auction snapshot (duplicates are ignored)."""
    data = [(ts, game, r["id"], int(r["lowest"]), int(round(r["cheap10"])), r["quantity"])
            for r in rows if r.get("found")]
    if not data:
        return
    with closing(_db()) as con, con:
        con.executemany("INSERT OR IGNORE INTO prices VALUES (?,?,?,?,?,?)", data)


def price_history(game, item_id, since_ts):
    """List of (ts, lowest, market, qty) since a time, oldest first."""
    with closing(_db()) as con:
        return con.execute("SELECT ts, lowest, market, qty FROM prices "
                           "WHERE game=? AND item_id=? AND ts>=? ORDER BY ts",
                           (game, item_id, int(since_ts))).fetchall()


def pct_change(game, item_id, current, ts, seconds):
    """% change in market price vs. the record closest to `seconds` ago (within 25%)."""
    target, slack = ts - seconds, seconds * 0.25
    with closing(_db()) as con:
        row = con.execute("SELECT market FROM prices WHERE game=? AND item_id=? "
                          "AND ts BETWEEN ? AND ? ORDER BY ABS(ts - ?) LIMIT 1",
                          (game, item_id, int(target - slack), int(target + slack),
                           int(target))).fetchone()
    if not row or not row[0]:
        return None
    return (current - row[0]) / row[0] * 100


def add_trends(game, ts, rows):
    for r in rows:
        if r.get("found"):
            for key, secs in PERIODS.items():
                r[key] = pct_change(game, r["id"], r["cheap10"], ts, secs)


# ---------- item name cache ----------

ITEM_CACHE_PATH = os.path.join(HERE, "item_cache.json")


def resolve_cached(api, query):
    """resolve_item, but remembers answers so repeat lookups skip the search."""
    key = f"{api.game}:{norm_name(query)}"
    cache = {}
    if os.path.exists(ITEM_CACHE_PATH):
        try:
            with open(ITEM_CACHE_PATH) as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
    hit = cache.get(key)
    name = norm_name(query)
    if hit and (name.isdigit() or norm_name(hit.get("name")) == name):
        return hit                 # (older versions could save a different item under a name)
    entry = resolve_item(api, query)
    if entry:
        cache[key] = entry
        with open(ITEM_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=1)
    return entry


# ---------- gold parsing ----------

_GOLD_PART = re.compile(r"(\d+(?:\.\d+)?)\s*([gsc])")


def parse_gold(text):
    """'1g 50s', '8s', '2.5g', '75c', or a bare number (gold) -> copper. None if blank."""
    t = text.lower().replace(",", "").strip()
    if not t:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return int(round(float(t) * 10000))
    parts = _GOLD_PART.findall(t)
    if not parts or _GOLD_PART.sub("", t).strip():
        raise ValueError(f'Can\'t read "{text}" as a price. Try something like 8s, 1g 50s or 2.5g.')
    mult = {"g": 10000, "s": 100, "c": 1}
    return int(round(sum(float(n) * mult[u] for n, u in parts)))


# ---------- fishing sessions ----------

SESSIONS_PATH = os.path.join(HERE, "fishing_sessions.json")
AH_CUT = 0.05  # auction house takes 5% of each sale


def parse_catch(text):
    """Lines like '20 Raw Mackerel', 'Raw Mackerel x20', 'Raw Mackerel 20', '6303'
    -> list of (qty, query)."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.isdigit():
            out.append((1, s))
            continue
        m = re.fullmatch(r"(\d+)\s+(\d+)", s)       # two bare numbers: larger one is the item ID
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.append((min(a, b), str(max(a, b))))
            continue
        m = re.match(r"^(.+?)\s*[x*]\s*(\d+)$", s, re.I)          # "Name x20", "6303 x5"
        if m:
            out.append((int(m.group(2)), m.group(1).strip()))
            continue
        m = re.match(r"^(\d+)\s*[x*]?\s+(.+)$", s, re.I)          # "20 Name", "20x Name"
        if m:
            out.append((int(m.group(1)), m.group(2).strip()))
            continue
        m = re.match(r"^(.+?)\s+(\d+)$", s)                       # "Name 20"
        if m:
            out.append((int(m.group(2)), m.group(1).strip()))
            continue
        out.append((1, s))
    return out


def value_catch(api, catch):
    """Price a list of (qty, query). Returns rows, unresolved names and totals."""
    merged, unresolved = {}, []
    for qty, query in catch:
        e = resolve_cached(api, query)
        if not e:
            unresolved.append(query)
            continue
        if e["id"] in merged:
            merged[e["id"]]["qty"] += qty
        else:
            merged[e["id"]] = {"id": e["id"], "name": e["name"], "qty": qty}
    sources = get_sources(api) if merged else []
    rows, summaries = [], []
    for item in merged.values():
        s = item_summary(sources, item["id"])
        if s:
            summaries.append({"id": item["id"], **s, "found": True})
            each = s["cheap10"]
            rows.append({**item, "found": True, "each": each, "total": each * item["qty"]})
        else:
            rows.append({**item, "found": False, "each": 0, "total": 0})
    if summaries:
        record_history(api.game, api.snapshot_time, summaries)
    total = sum(r["total"] for r in rows)
    return {"rows": rows, "unresolved": unresolved, "total": total,
            "after_cut": total * (1 - AH_CUT), "ts": api.snapshot_time}


def load_sessions():
    if os.path.exists(SESSIONS_PATH):
        try:
            with open(SESSIONS_PATH) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return []


def save_session(entry):
    sessions = load_sessions()
    sessions.append(entry)
    with open(SESSIONS_PATH, "w") as f:
        json.dump(sessions, f, indent=1)


# ---------- shared tool helpers ----------

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=1)


def get_listings(sources, item_id):
    """All (price, qty) listings for an item across every auction house, cheapest first."""
    out = []
    for _label, book in sources:
        out.extend(book.get(item_id, []))
    return sorted(out)


def known_names():
    """item_id -> name for everything on the watchlist or looked up before."""
    names = {}
    for e in load_json(ITEM_CACHE_PATH, {}).values():
        names[e["id"]] = e["name"]
    for e in load_watchlist():
        names[e["id"]] = e["name"]
    return names


def history_stats(game, item_id, days=7, before_ts=None):
    rows = price_history(game, item_id, time.time() - days * 86400)
    if before_ts is not None:
        rows = [r for r in rows if r[0] < before_ts]
    if not rows:
        return None
    mk = [r[2] for r in rows]
    return {"points": len(rows), "median_market": statistics.median(mk),
            "avg_market": sum(mk) / len(mk),
            "median_qty": statistics.median([r[3] for r in rows]),
            "span_days": (rows[-1][0] - rows[0][0]) / 86400}


# ---------- sell-price helper ----------

def sell_advice(api, query, my_qty=None, item=None):
    """item = {'id', 'name'} skips the name lookup (used when the item was picked from a list)."""
    item = item or resolve_cached(api, query)
    if not item:
        return None
    sources = get_sources(api)
    ts = api.snapshot_time
    hist = history_stats(api.game, item["id"], 7, before_ts=ts)
    lst = get_listings(sources, item["id"])
    res = {"item": item, "hist": hist, "my_qty": my_qty, "listed": bool(lst), "ts": ts}
    if not lst:
        return res
    s = summarize(lst)
    record_history(api.game, ts, [{"id": item["id"], "found": True, **s}])

    ladder, cum = [], 0
    for price, qty in lst:
        cum += qty
        if ladder and ladder[-1][0] == price:
            ladder[-1] = (price, ladder[-1][1] + qty, cum)
        else:
            ladder.append((price, qty, cum))
    total = cum

    # A tiny batch priced well under everyone else: don't race it to the bottom.
    target, outlier = ladder[0][0], None
    if len(ladder) > 1:
        p0, q0, _ = ladder[0]
        p1 = ladder[1][0]
        if q0 <= max(5, total * 0.03) and p0 < p1 * 0.9:
            outlier = {"price": p0, "qty": q0, "next": p1}
            target = p1
    suggested = max(1, target - 1)

    flood = None
    if hist and hist["points"] >= 6 and hist["median_qty"]:
        flood = total / hist["median_qty"]
    vs_usual = None
    if hist and hist["points"] >= 6 and hist["median_market"]:
        vs_usual = (s["cheap10"] - hist["median_market"]) / hist["median_market"] * 100

    res.update({**s, "ladder": ladder[:10], "suggested": suggested, "outlier": outlier,
                "flood": flood, "vs_usual": vs_usual,
                "ahead": sum(q for p, q in lst if p < suggested)})
    if my_qty:
        res["payout"] = suggested * my_qty * (1 - AH_CUT)
    return res


# ---------- best time to sell ----------

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOUR_BLOCKS = ["12-3 AM", "3-6 AM", "6-9 AM", "9 AM-12 PM", "12-3 PM", "3-6 PM", "6-9 PM", "9 PM-12 AM"]


def _relative(ts, mk, window):
    """Each price divided by the average price in a window centred on it (removes trends)."""
    out, half, n = [], window / 2, len(ts)
    lo = hi = 0
    total = 0
    for i, t in enumerate(ts):
        while hi < n and ts[hi] <= t + half:
            total += mk[hi]
            hi += 1
        while ts[lo] < t - half:
            total -= mk[lo]
            lo += 1
        base = total / (hi - lo)
        out.append(mk[i] / base if base else 1.0)
    return out


def sell_timing(game, item_id, days=30):
    rows = price_history(game, item_id, time.time() - days * 86400)
    res = {"points": len(rows), "span_days": 0, "weekdays": None, "hours": None}
    if len(rows) < 2:
        return res
    ts = [r[0] for r in rows]
    mk = [r[2] for r in rows]
    res["span_days"] = (ts[-1] - ts[0]) / 86400

    def group(rel, key_fn, n_keys):
        sums, counts = [0.0] * n_keys, [0] * n_keys
        for t, r in zip(ts, rel):
            k = key_fn(datetime.fromtimestamp(t))
            sums[k] += (r - 1) * 100
            counts[k] += 1
        return [(sums[k] / counts[k] if counts[k] else None, counts[k]) for k in range(n_keys)]

    if res["span_days"] >= 2 and len(rows) >= 24:
        res["hours"] = group(_relative(ts, mk, 86400), lambda d: d.hour // 3, 8)
    if res["span_days"] >= 7 and len(rows) >= 48:
        res["weekdays"] = group(_relative(ts, mk, 7 * 86400), lambda d: d.weekday(), 7)
    return res


# ---------- flip finder ----------

def find_flips(api, threshold=0.15):
    """Items listed well below their usual (7-day median) price right now."""
    names = known_names()
    sources = get_sources(api)
    ts = api.snapshot_time
    flips, skipped = [], []
    for item_id, name in sorted(names.items(), key=lambda kv: kv[1]):
        hist = history_stats(api.game, item_id, 7, before_ts=ts)
        if not hist or hist["points"] < 12:
            skipped.append(name)
            continue
        lst = get_listings(sources, item_id)
        if not lst:
            continue
        typical = hist["median_market"]
        resale = typical * (1 - AH_CUT)
        cheap = [(p, q) for p, q in lst if p <= typical * (1 - threshold)]
        profit = sum((resale - p) * q for p, q in cheap)
        if not cheap or profit <= 0:
            continue
        flips.append({"id": item_id, "name": name, "lowest": lst[0][0], "typical": typical,
                      "discount": (1 - lst[0][0] / typical) * 100,
                      "units": sum(q for _, q in cheap), "cost": sum(p * q for p, q in cheap),
                      "profit": profit})
    flips.sort(key=lambda f: -f["profit"])
    return {"flips": flips, "skipped": skipped, "ts": ts}


# ---------- crafting profit ----------

RECIPES_PATH = os.path.join(HERE, "recipes.json")


def parse_reagents(text):
    """Lines like '2 Raw Mackerel' or '1 Mild Spices @ 10c' (fixed/vendor price)
    -> list of (qty, query, fixed_price_or_None). Raises ValueError on a bad price."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        fixed = None
        if "@" in s:
            s, price = s.rsplit("@", 1)
            fixed = parse_gold(price)
        parsed = parse_catch(s)
        if parsed:
            qty, query = parsed[0]
            out.append((qty, query, fixed))
    return out


def craft_profit(api, recipes):
    sources = get_sources(api)
    results = []
    for r in recipes:
        res = {"name": r["name"], "errors": [], "parts": [], "ok": False}
        results.append(res)
        try:
            reagents = parse_reagents(r.get("reagents", ""))
        except ValueError as e:
            res["errors"].append(str(e))
            continue
        prod = resolve_cached(api, r["makes"])
        if not prod:
            res["errors"].append(f'Couldn\'t find the crafted item "{r["makes"]}".')
            continue
        res["product"] = prod
        makes = r.get("makes_qty", 1) or 1
        ps = item_summary(sources, prod["id"])
        if not ps:
            res["errors"].append(f"{prod['name']} isn't listed on the auction house right now.")
        cost_ah = cost_fixed = 0
        missing = False
        for qty, query, fixed in reagents:
            if fixed is not None:
                cost_fixed += fixed * qty
                res["parts"].append({"name": query, "qty": qty, "each": fixed, "how": "set price"})
                continue
            it = resolve_cached(api, query)
            if not it:
                res["errors"].append(f'Couldn\'t find reagent "{query}".')
                missing = True
                continue
            s = item_summary(sources, it["id"])
            if not s:
                res["errors"].append(f"{it['name']} isn't on the AH - add a price like "
                                     f"\"{qty} {it['name']} @ 10c\" if you buy it from a vendor.")
                missing = True
                continue
            cost_ah += s["cheap10"] * qty
            res["parts"].append({"id": it["id"], "name": it["name"], "qty": qty,
                                 "each": s["cheap10"], "how": "AH"})
        if not ps or missing:
            continue
        sell = ps["cheap10"] * makes * (1 - AH_CUT)
        cost = cost_ah + cost_fixed
        res.update({"ok": True, "makes": makes, "product_each": ps["cheap10"], "cost": cost,
                    "sell": sell, "profit": sell - cost,
                    "margin": (sell - cost) / cost * 100 if cost else None,
                    # if you already own the AH mats, the alternative is selling them raw
                    "vs_raw": sell - (cost_ah * (1 - AH_CUT) + cost_fixed)})
    return results


# ---------- fishing spot planner ----------

SPOTS_PATH = os.path.join(HERE, "fishing_spots.json")


def parse_drops(text):
    """Lines like '45% Raw Mackerel', 'Raw Mackerel 45%' or 'Raw Mackerel 45' -> [(share, query)]."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = (re.match(r"^(\d+(?:\.\d+)?)\s*%?\s+(.+)$", s)
             or None)
        if m:
            out.append((float(m.group(1)), m.group(2).strip()))
            continue
        m = re.match(r"^(.+?)\s+(\d+(?:\.\d+)?)\s*%?$", s)
        if m:
            out.append((float(m.group(2)), m.group(1).strip()))
            continue
        raise ValueError(f'Can\'t read "{s}". Use a line like "45% Raw Slitherskin Mackerel".')
    return out


def plan_spots(api, spots):
    sources = get_sources(api)
    results = []
    for sp in spots:
        res = {"name": sp["name"], "errors": [], "parts": [], "ok": False}
        results.append(res)
        try:
            drops = parse_drops(sp.get("drops", ""))
        except ValueError as e:
            res["errors"].append(str(e))
            continue
        cph = sp.get("catches_per_hour") or 0
        total_share = sum(sh for sh, _ in drops)
        if not drops or not total_share:
            res["errors"].append("Add what this spot drops (e.g. 45% Raw Slitherskin Mackerel).")
            continue
        if not cph:
            res["errors"].append("Add catches per hour.")
            continue
        value = 0
        for share, query in drops:
            it = resolve_cached(api, query)
            if not it:
                res["errors"].append(f'Couldn\'t find "{query}".')
                continue
            s = item_summary(sources, it["id"])
            each = s["cheap10"] if s else 0
            frac = share / total_share
            value += frac * each
            res["parts"].append({"id": it["id"], "name": it["name"], "share": frac * 100,
                                 "each": each, "listed": bool(s)})
        res.update({"ok": True, "cph": cph, "per_catch": value,
                    "gph": cph * value * (1 - AH_CUT),
                    "normalized": abs(total_share - 100) > 0.5})
    results.sort(key=lambda r: -(r.get("gph") or -1))
    return results


def spot_from_sessions(spot_name):
    """Build catches/hour and a drop table from saved sessions at a spot (needs minutes)."""
    sess = [s for s in load_sessions()
            if s.get("spot", "").strip().lower() == spot_name.strip().lower() and s.get("minutes")]
    if not sess:
        return None
    minutes = sum(s["minutes"] for s in sess)
    counts = {}
    for s in sess:
        for it in s["items"]:
            counts[it["name"]] = counts.get(it["name"], 0) + it["qty"]
    total = sum(counts.values())
    if not total:
        return None
    drops = "\n".join(f"{c / total * 100:.1f}% {n}"
                      for n, c in sorted(counts.items(), key=lambda kv: -kv[1]))
    return {"catches_per_hour": round(total / minutes * 60, 1), "drops": drops,
            "sessions": len(sess), "minutes": minutes}


# ---------- professions (Blizzard profession and recipe data) ----------

GATHERING = {"Herbalism", "Mining", "Skinning", "Fishing", "Archaeology"}
DEFAULT_PROFESSIONS = ["Alchemy", "Blacksmithing", "Cooking", "Enchanting", "Engineering", "First Aid",
                       "Leatherworking", "Tailoring", "Fishing", "Herbalism", "Mining", "Skinning"]
# which auction-house subcategory holds each profession's materials (matched by name)
MATERIAL_KEYWORDS = {"Mining": ["Metal"], "Herbalism": ["Herb"], "Skinning": ["Leather"],
                     "Fishing": ["Cooking", "Meat", "Fish"], "Alchemy": ["Herb"], "Blacksmithing": ["Metal"],
                     "Cooking": ["Cooking", "Meat"], "Enchanting": ["Enchanting"],
                     "Engineering": ["Parts", "Metal"], "Leatherworking": ["Leather"],
                     "Tailoring": ["Cloth"], "First Aid": ["Cloth"], "Jewelcrafting": ["Jewelcrafting", "Gem"],
                     "Inscription": ["Inscription", "Ink", "Herb"]}
RECIPE_SECONDS = 7 * 86400


def _cache_json(api, name, build, seconds=RECIPE_SECONDS):
    path = os.path.join(CACHE_DIR, f"{api.game}_{api.region}_{name}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < seconds:
        return load_json(path, None)
    data = build()
    if data is not None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        save_json(path, data)
    return data


def get_professions(api):
    """[{'id', 'name', 'gathering'}] from Blizzard, or None if this game has no profession data."""
    def build():
        try:
            idx = api.get("/data/wow/profession/index", "static")
        except ApiError:
            return None
        out = [{"id": p["id"], "name": _loc(p.get("name"))} for p in idx.get("professions", [])]
        return out or None
    profs = _cache_json(api, "professions", build)
    if not profs:
        return None
    for p in profs:
        p["gathering"] = p["name"] in GATHERING
    return sorted(profs, key=lambda p: p["name"])


def profession_tiers(api, prof_id):
    """Skill tiers (e.g. one per expansion) for a profession. Empty list if none."""
    def build():
        try:
            d = api.get(f"/data/wow/profession/{prof_id}", "static")
        except ApiError:
            return []
        return [{"id": t["id"], "name": _loc(t.get("name"))} for t in d.get("skill_tiers", [])]
    return _cache_json(api, f"prof_{prof_id}_tiers", build) or []


def tier_recipes(api, prof_id, tier_id, progress=None):
    """Every recipe in a skill tier with what it makes and its reagents. Cached for a week."""
    def build():
        d = api.get(f"/data/wow/profession/{prof_id}/skill-tier/{tier_id}", "static")
        refs = [(_loc(cat.get("name")), r["id"], _loc(r.get("name")))
                for cat in d.get("categories", []) for r in cat.get("recipes", [])]
        out = []
        for i, (cat, rid, rname) in enumerate(refs):
            if progress:
                progress(i, len(refs))
            try:
                rd = api.get(f"/data/wow/recipe/{rid}", "static")
            except ApiError:
                continue
            item = rd.get("crafted_item") or rd.get("alliance_crafted_item") or rd.get("horde_crafted_item")
            if not item:
                continue                      # e.g. enchants that don't make a sellable item
            cq = rd.get("crafted_quantity") or {}
            makes = cq.get("value") or (cq.get("minimum", 1) + cq.get("maximum", 1)) / 2 or 1
            reagents = [{"id": x["reagent"]["id"], "name": _loc(x["reagent"].get("name")),
                         "qty": x.get("quantity", 1)} for x in rd.get("reagents", []) if x.get("reagent")]
            out.append({"id": rid, "name": _loc(rd.get("name")) or rname, "category": cat,
                        "item_id": item["id"], "item_name": _loc(item.get("name")),
                        "makes": makes, "reagents": reagents})
        return out
    return _cache_json(api, f"recipes_{prof_id}_{tier_id}", build)


def vendor_price(api, item_id):
    """What a vendor charges for an item (Blizzard's purchase price). 0 if unknown."""
    info = cached_info(api.game, item_id)
    if "buy" not in info:
        try:
            info = remember_info(api.game, item_id, api.get(f"/data/wow/item/{item_id}", "static"))
        except ApiError:
            return 0
    return info.get("buy") or 0


def price_recipes(api, recipes):
    """Price every recipe at today's AH prices. Reagents nobody sells on the AH fall back
    to the vendor price; recipes whose item isn't listed get no sell price."""
    sources = get_sources(api)
    summ = {}

    def summary(item_id):
        if item_id not in summ:
            summ[item_id] = item_summary(sources, item_id)
        return summ[item_id]

    rows = []
    for r in recipes:
        ps = summary(r["item_id"])
        cost_ah = cost_v = 0
        parts, missing = [], []
        for rg in r["reagents"]:
            s = summary(rg["id"])
            if s:
                each, how = s["cheap10"], "AH"
                cost_ah += each * rg["qty"]
            else:
                each = vendor_price(api, rg["id"])
                how = "vendor" if each else None
                if each:
                    cost_v += each * rg["qty"]
                else:
                    missing.append(rg["name"])
            parts.append({**rg, "each": each, "how": how})
        row = {**r, "parts": parts, "missing": missing, "cost": cost_ah + cost_v,
               "listed": ps["quantity"] if ps else 0, "each": ps["cheap10"] if ps else None,
               "sell": None, "profit": None, "margin": None, "vs_raw": None}
        if ps and not missing:
            sell = ps["cheap10"] * r["makes"] * (1 - AH_CUT)
            row.update(sell=sell, profit=sell - row["cost"],
                       margin=(sell - row["cost"]) / row["cost"] * 100 if row["cost"] else None,
                       vs_raw=sell - (cost_ah * (1 - AH_CUT) + cost_v))
        rows.append(row)
    save_info()
    return {"rows": rows, "ts": api.snapshot_time}


def find_material_category(api, profession):
    """(class_id, subclass_id, class_name, sub_name) of the AH category holding a profession's
    materials, preferring Trade Goods. None if nothing matches."""
    words = [w.lower() for w in MATERIAL_KEYWORDS.get(profession, [])]
    cats = get_categories(api)
    cats = sorted(cats, key=lambda c: c["name"] != "Trade Goods")
    for w in words:
        for c in cats:
            for sc in c["subs"]:
                if w in (sc["name"] or "").lower():
                    return c["id"], sc["id"], c["name"], sc["name"]
    return None


def material_prices(api, profession):
    found = find_material_category(api, profession)
    if not found:
        return None
    res = browse_category(api, *found)
    res["category"] = found
    return res


# ---------- profession leveling guides ----------
# Written for this app from Classic WoW (patch 1.12-era) leveling paths. WoW: Forever may differ,
# so craft counts are approximate and every guide can be customised (see export_guide).
# Each step is a skill range with one or more options (branches).
#   crafting option:  {"name", "crafts": [(recipe, times, [(material, qty per craft), ...], product)], "note"}
#                     product = item the craft makes (None for enchants) - used to value what you can sell back
#   gathering option: {"name", "gathers": [item, ...], "note"}

def _c(recipe, times, mats, product="same"):
    return (recipe, times, mats, recipe if product == "same" else product)


GUIDES = {
    "First Aid": {
        "kind": "craft",
        "intro": "The cheapest profession to level: bandages from cloth you pick up while questing. "
                 "Every character can learn it alongside two main professions.",
        "trainers": "Expert (to 225): buy the book Expert First Aid - Under Wraps from Deneb Walker "
                    "(Stromgarde, Arathi Highlands) or Balai Lok'Wein (Brackenwall Village, Dustwallow Marsh) at 125+. "
                    "Artisan (to 300): the quest Triage at 225 skill and level 35, from Doctor Gustaf VanHowzen "
                    "(Theramore) or Doctor Gregory Victor (Hammerfall).",
        "steps": [
            {"range": (1, 40), "options": [
                {"name": "Linen Bandage", "crafts": [_c("Linen Bandage", 45, [("Linen Cloth", 1)])]}]},
            {"range": (40, 80), "options": [
                {"name": "Heavy Linen Bandage", "crafts": [_c("Heavy Linen Bandage", 45, [("Linen Cloth", 2)])]}]},
            {"range": (80, 115), "options": [
                {"name": "Wool Bandage", "crafts": [_c("Wool Bandage", 40, [("Wool Cloth", 1)])]}]},
            {"range": (115, 150), "options": [
                {"name": "Heavy Wool Bandage", "crafts": [_c("Heavy Wool Bandage", 40, [("Wool Cloth", 2)])],
                 "note": "Buy the Expert First Aid book before you reach 150."}]},
            {"range": (150, 180), "options": [
                {"name": "Silk Bandage", "crafts": [_c("Silk Bandage", 35, [("Silk Cloth", 1)])]}]},
            {"range": (180, 210), "options": [
                {"name": "Heavy Silk Bandage", "crafts": [_c("Heavy Silk Bandage", 35, [("Silk Cloth", 2)])]},
                {"name": "Keep making Silk Bandages", "crafts": [_c("Silk Bandage", 50, [("Silk Cloth", 1)])],
                 "note": "Uses less cloth per craft, but skill-ups get slower (green) so you need more crafts."}]},
            {"range": (210, 240), "options": [
                {"name": "Mageweave Bandage", "crafts": [_c("Mageweave Bandage", 35, [("Mageweave Cloth", 1)])],
                 "note": "Do the Triage quest at 225 to unlock Artisan."}]},
            {"range": (240, 260), "options": [
                {"name": "Heavy Mageweave Bandage", "crafts": [_c("Heavy Mageweave Bandage", 25, [("Mageweave Cloth", 2)])]},
                {"name": "Keep making Mageweave Bandages", "crafts": [_c("Mageweave Bandage", 35, [("Mageweave Cloth", 1)])],
                 "note": "Cheaper per craft; expect some green skill-ups."}]},
            {"range": (260, 290), "options": [
                {"name": "Runecloth Bandage", "crafts": [_c("Runecloth Bandage", 35, [("Runecloth", 1)])]}]},
            {"range": (290, 300), "options": [
                {"name": "Heavy Runecloth Bandage", "crafts": [_c("Heavy Runecloth Bandage", 15, [("Runecloth", 2)])]}]},
        ]},

    "Cooking": {
        "kind": "craft",
        "intro": "Two ways up: a meat path from beasts you kill while questing, or a fish path that pairs "
                 "perfectly with Fishing. Mix and match per bracket - pick whatever is cheapest or already in your bags.",
        "trainers": "Journeyman at 50 (level 10). Expert: buy the Expert Cookbook (about 1g) from Shandrina "
                    "(Ashenvale) or Wulan (Desolace) at 150. Artisan: at 225 and level 35, Dirge Quikcleave in "
                    "Gadgetzan wants 12 Giant Egg, 10 Tangy Clam Meat and 20 Alterac Swiss. Fish recipes are sold "
                    "by fishing supply vendors.",
        "steps": [
            {"range": (1, 50), "options": [
                {"name": "Charred Wolf Meat", "crafts": [_c("Charred Wolf Meat", 55, [("Stringy Wolf Meat", 1)])]},
                {"name": "Roasted Boar Meat", "crafts": [_c("Roasted Boar Meat", 55, [("Chunk of Boar Meat", 1)])]},
                {"name": "Fish: Brilliant Smallfish", "crafts": [_c("Brilliant Smallfish", 55, [("Raw Brilliant Smallfish", 1)])]}]},
            {"range": (50, 75), "options": [
                {"name": "Smoked Bear Meat", "crafts": [_c("Smoked Bear Meat", 25, [("Bear Meat", 1)])]},
                {"name": "Fish: Longjaw Mud Snapper", "crafts": [_c("Longjaw Mud Snapper", 25, [("Raw Longjaw Mud Snapper", 1)])]}]},
            {"range": (75, 100), "options": [
                {"name": "Crab Cake", "crafts": [_c("Crab Cake", 25, [("Crawler Meat", 1), ("Mild Spices", 1)])]},
                {"name": "Cooked Crab Claw", "crafts": [_c("Cooked Crab Claw", 25, [("Crawler Claw", 1), ("Mild Spices", 1)])]},
                {"name": "Fish: Longjaw Mud Snapper", "crafts": [_c("Longjaw Mud Snapper", 30, [("Raw Longjaw Mud Snapper", 1)])]}]},
            {"range": (100, 150), "options": [
                {"name": "Seasoned Wolf Kabob", "crafts": [_c("Seasoned Wolf Kabob", 50, [("Lean Wolf Flank", 2), ("Stormwind Seasoning Herbs", 1)])]},
                {"name": "Curiously Tasty Omelet", "crafts": [_c("Curiously Tasty Omelet", 50, [("Raptor Egg", 1), ("Hot Spices", 1)])]},
                {"name": "Fish: Bristle Whisker Catfish", "crafts": [_c("Bristle Whisker Catfish", 55, [("Raw Bristle Whisker Catfish", 1)])]}],
             "note": "Buy the Expert Cookbook before 150."},
            {"range": (150, 175), "options": [
                {"name": "Curiously Tasty Omelet", "crafts": [_c("Curiously Tasty Omelet", 25, [("Raptor Egg", 1), ("Hot Spices", 1)])]},
                {"name": "Hot Lion Chops", "crafts": [_c("Hot Lion Chops", 25, [("Lion Meat", 1), ("Hot Spices", 1)])]},
                {"name": "Fish: Bristle Whisker Catfish", "crafts": [_c("Bristle Whisker Catfish", 30, [("Raw Bristle Whisker Catfish", 1)])]}]},
            {"range": (175, 200), "options": [
                {"name": "Soothing Turtle Bisque", "crafts": [_c("Soothing Turtle Bisque", 25, [("Turtle Meat", 1), ("Soothing Spices", 1)])]},
                {"name": "Roast Raptor", "crafts": [_c("Roast Raptor", 25, [("Raptor Flank", 1), ("Hot Spices", 1)])]},
                {"name": "Fish: Mithril Head Trout", "crafts": [_c("Mithril Head Trout", 25, [("Raw Mithril Head Trout", 1)])]}]},
            {"range": (200, 225), "options": [
                {"name": "Spider Sausage", "crafts": [_c("Spider Sausage", 25, [("White Spider Meat", 2)])]},
                {"name": "Roast Raptor", "crafts": [_c("Roast Raptor", 25, [("Raptor Flank", 1), ("Hot Spices", 1)])]},
                {"name": "Fish: Mithril Head Trout", "crafts": [_c("Mithril Head Trout", 25, [("Raw Mithril Head Trout", 1)])]}],
             "note": "At 225 (level 35) do Dirge Quikcleave's quest in Gadgetzan for Artisan."},
            {"range": (225, 275), "options": [
                {"name": "Monster Omelet", "crafts": [_c("Monster Omelet", 50, [("Giant Egg", 1), ("Soothing Spices", 2)])]},
                {"name": "Tender Wolf Steak", "crafts": [_c("Tender Wolf Steak", 50, [("Tender Wolf Meat", 1), ("Soothing Spices", 1)])]},
                {"name": "Fish: Yellowtail, then Sunscale Salmon", "crafts": [
                    _c("Spotted Yellowtail", 25, [("Raw Spotted Yellowtail", 1)]),
                    _c("Poached Sunscale Salmon", 25, [("Raw Sunscale Salmon", 1)])],
                 "note": "Both fish recipes are sold by Gikkix on the beach north-east of Gadgetzan."}]},
            {"range": (275, 300), "options": [
                {"name": "Smoked Desert Dumplings", "crafts": [_c("Smoked Desert Dumplings", 25, [("Sandworm Meat", 1), ("Soothing Spices", 1)])],
                 "note": "Recipe comes from the Desert Recipe quest chain in Silithus."},
                {"name": "Fish: Mightfish Steak", "crafts": [_c("Mightfish Steak", 25, [("Large Raw Mightfish", 1), ("Hot Spices", 1), ("Soothing Spices", 1)])],
                 "note": "Recipe sold in Feralas (Sheendra Tallgrass / Vivianna)."}]},
        ]},

    "Tailoring": {
        "kind": "craft",
        "intro": "Cloth comes from humanoid mobs, so tailoring levels nicely while you quest. "
                 "Bolts made early are used again in later steps - make extras.",
        "trainers": "Expert at 125-150: Georgio Bolero (Stormwind) or Josef Gregorian (Undercity). "
                    "Artisan at 225 (level 35): Timothy Worthington (Theramore, Dustwallow Marsh) or Daryl Stack "
                    "(Tarren Mill, Hillsbrad Foothills). Thread, dyes and bleach come from trade supply vendors.",
        "steps": [
            {"range": (1, 50), "options": [
                {"name": "Bolt of Linen Cloth", "crafts": [_c("Bolt of Linen Cloth", 60, [("Linen Cloth", 2)])],
                 "note": "Keep the bolts - the next two steps use them."}]},
            {"range": (50, 75), "options": [
                {"name": "Linen Bag, then Reinforced Linen Cape", "crafts": [
                    _c("Linen Bag", 20, [("Bolt of Linen Cloth", 3), ("Coarse Thread", 3)]),
                    _c("Reinforced Linen Cape", 5, [("Bolt of Linen Cloth", 2), ("Coarse Thread", 3)])],
                 "note": "Linen Bags sell well to new players."}]},
            {"range": (75, 105), "options": [
                {"name": "Bolt of Woolen Cloth", "crafts": [_c("Bolt of Woolen Cloth", 40, [("Wool Cloth", 3)])]}]},
            {"range": (105, 125), "options": [
                {"name": "Gray Woolen Shirt, then Double-stitched Shoulders", "crafts": [
                    _c("Gray Woolen Shirt", 5, [("Bolt of Woolen Cloth", 2), ("Fine Thread", 1), ("Gray Dye", 1)]),
                    _c("Double-stitched Woolen Shoulders", 15, [("Bolt of Woolen Cloth", 3), ("Fine Thread", 2)])]}]},
            {"range": (125, 145), "options": [
                {"name": "Bolt of Silk Cloth", "crafts": [_c("Bolt of Silk Cloth", 40, [("Silk Cloth", 4)])],
                 "note": "Silk bolts are used all the way to 215 - make plenty."}]},
            {"range": (145, 175), "options": [
                {"name": "Azure Silk Hood, Silk Headband, Formal White Shirt", "crafts": [
                    _c("Azure Silk Hood", 15, [("Bolt of Silk Cloth", 2), ("Fine Thread", 1), ("Blue Dye", 2)]),
                    _c("Silk Headband", 10, [("Bolt of Silk Cloth", 3), ("Fine Thread", 2)]),
                    _c("Formal White Shirt", 5, [("Bolt of Silk Cloth", 3), ("Bleach", 2), ("Fine Thread", 1)])]}]},
            {"range": (175, 185), "options": [
                {"name": "Bolt of Mageweave", "crafts": [_c("Bolt of Mageweave", 10, [("Mageweave Cloth", 5)])]}]},
            {"range": (185, 215), "options": [
                {"name": "Crimson Silk Vest, then Pantaloons", "crafts": [
                    _c("Crimson Silk Vest", 15, [("Bolt of Silk Cloth", 4), ("Fine Thread", 2), ("Red Dye", 2)]),
                    _c("Crimson Silk Pantaloons", 15, [("Bolt of Silk Cloth", 4), ("Red Dye", 2), ("Silken Thread", 2)])]}]},
            {"range": (215, 250), "options": [
                {"name": "Black Mageweave Leggings, Gloves, Headband", "crafts": [
                    _c("Black Mageweave Leggings", 5, [("Bolt of Mageweave", 2), ("Silken Thread", 3)]),
                    _c("Black Mageweave Gloves", 10, [("Bolt of Mageweave", 2), ("Heavy Silken Thread", 2)]),
                    _c("Black Mageweave Headband", 20, [("Bolt of Mageweave", 3), ("Heavy Silken Thread", 2)])],
                 "note": "Visit the Artisan trainer at 225."}]},
            {"range": (250, 260), "options": [
                {"name": "Bolt of Runecloth", "crafts": [_c("Bolt of Runecloth", 30, [("Runecloth", 5)])],
                 "note": "Runecloth bolts are used for the rest of the guide."}]},
            {"range": (260, 280), "options": [
                {"name": "Runecloth Belt", "crafts": [_c("Runecloth Belt", 20, [("Bolt of Runecloth", 3), ("Rune Thread", 1)])]},
                {"name": "Runecloth Bag", "crafts": [_c("Runecloth Bag", 20, [("Bolt of Runecloth", 5), ("Rugged Leather", 2), ("Rune Thread", 1)])],
                 "note": "Costs more, but Runecloth Bags usually sell well."}]},
            {"range": (280, 300), "options": [
                {"name": "Runecloth Gloves", "crafts": [_c("Runecloth Gloves", 20, [("Bolt of Runecloth", 3), ("Rugged Leather", 3), ("Rune Thread", 1)])]},
                {"name": "Runecloth Bag", "crafts": [_c("Runecloth Bag", 25, [("Bolt of Runecloth", 5), ("Rugged Leather", 2), ("Rune Thread", 1)])]}]},
        ]},

    "Alchemy": {
        "kind": "craft",
        "intro": "Pairs with Herbalism. Many steps make potions people actually buy, so you can often "
                 "sell your leveling crafts back and level for close to free.",
        "trainers": "Expert at 150: Ainethil (Darnassus) or Doctor Herbert Halsey (Undercity). Artisan at 225 "
                    "(level 35): Kylanna Windwhisper (Feathermoon, Feralas) or Rogvar (Stonard, Swamp of Sorrows). "
                    "Vials come from trade supply vendors. Recipe: Major Healing Potion is sold by Evie Whirlbrew in Everlook.",
        "steps": [
            {"range": (1, 60), "options": [
                {"name": "Minor Healing Potion", "crafts": [_c("Minor Healing Potion", 60, [("Peacebloom", 1), ("Silverleaf", 1), ("Empty Vial", 1)])],
                 "note": "Keep about 50 - the next step upgrades them."}]},
            {"range": (60, 110), "options": [
                {"name": "Lesser Healing Potion, then Elixir of Wisdom", "crafts": [
                    _c("Lesser Healing Potion", 50, [("Minor Healing Potion", 1), ("Briarthorn", 1)]),
                    _c("Elixir of Wisdom", 5, [("Mageroyal", 1), ("Briarthorn", 2), ("Empty Vial", 1)])]}]},
            {"range": (110, 140), "options": [
                {"name": "Healing Potion", "crafts": [_c("Healing Potion", 30, [("Bruiseweed", 1), ("Briarthorn", 1), ("Leaded Vial", 1)])]}]},
            {"range": (140, 155), "options": [
                {"name": "Lesser Mana Potion", "crafts": [_c("Lesser Mana Potion", 15, [("Mageroyal", 1), ("Stranglekelp", 1), ("Empty Vial", 1)])],
                 "note": "Train Expert at 150."}]},
            {"range": (155, 185), "options": [
                {"name": "Greater Healing Potion, then Mana Potion", "crafts": [
                    _c("Greater Healing Potion", 20, [("Liferoot", 1), ("Kingsblood", 1), ("Leaded Vial", 1)]),
                    _c("Mana Potion", 10, [("Stranglekelp", 1), ("Kingsblood", 1), ("Leaded Vial", 1)])]},
                {"name": "Greater Healing Potion only", "crafts": [
                    _c("Greater Healing Potion", 35, [("Liferoot", 1), ("Kingsblood", 1), ("Leaded Vial", 1)])],
                 "note": "Simpler shopping list; a few more crafts as it turns green."}]},
            {"range": (185, 215), "options": [
                {"name": "Elixir of Agility, then Greater Defense", "crafts": [
                    _c("Elixir of Agility", 20, [("Stranglekelp", 1), ("Goldthorn", 1), ("Leaded Vial", 1)]),
                    _c("Elixir of Greater Defense", 10, [("Wild Steelbloom", 1), ("Goldthorn", 1), ("Leaded Vial", 1)])]}]},
            {"range": (215, 250), "options": [
                {"name": "Superior Healing, then Elixir of Greater Intellect", "crafts": [
                    _c("Superior Healing Potion", 25, [("Sungrass", 1), ("Khadgar's Whisker", 1), ("Crystal Vial", 1)]),
                    _c("Elixir of Greater Intellect", 10, [("Khadgar's Whisker", 1), ("Blindweed", 1), ("Crystal Vial", 1)])]},
                {"name": "Superior Healing Potion all the way", "crafts": [
                    _c("Superior Healing Potion", 40, [("Sungrass", 1), ("Khadgar's Whisker", 1), ("Crystal Vial", 1)])],
                 "note": "Good if Blindweed is expensive."}]},
            {"range": (250, 270), "options": [
                {"name": "Elixir of Detect Demon", "crafts": [_c("Elixir of Detect Demon", 20, [("Gromsblood", 2), ("Crystal Vial", 1)])]}]},
            {"range": (270, 285), "options": [
                {"name": "Elixir of the Sages", "crafts": [_c("Elixir of the Sages", 15, [("Dreamfoil", 1), ("Plaguebloom", 2), ("Crystal Vial", 1)])]}]},
            {"range": (285, 300), "options": [
                {"name": "Major Healing Potion", "crafts": [_c("Major Healing Potion", 20, [("Golden Sansam", 2), ("Mountain Silversage", 1), ("Crystal Vial", 1)])],
                 "note": "Recipe sold by Evie Whirlbrew in Everlook (Winterspring)."}]},
        ]},

    "Blacksmithing": {
        "kind": "craft",
        "intro": "Pairs with Mining. Grinding and sharpening stones are cheap early skill-ups; "
                 "save some grinding stones because later recipes use them.",
        "trainers": "Expert at 150: Bengus Deepforge (Ironforge) or Saru Steelfury (Orgrimmar). Artisan at 225 "
                    "(level 35): Brikk Keencraft (Booty Bay). Plans: Mithril Scale Bracers are sold by Harggan "
                    "(The Hinterlands) or Gharash (Swamp of Sorrows) - limited supply.",
        "steps": [
            {"range": (1, 25), "options": [
                {"name": "Rough Sharpening Stone", "crafts": [_c("Rough Sharpening Stone", 30, [("Rough Stone", 1)])]}]},
            {"range": (25, 65), "options": [
                {"name": "Rough Grinding Stone", "crafts": [_c("Rough Grinding Stone", 50, [("Rough Stone", 2)])]}]},
            {"range": (65, 90), "options": [
                {"name": "Coarse Sharpening Stone, then Grinding Stone", "crafts": [
                    _c("Coarse Sharpening Stone", 16, [("Coarse Stone", 1)]),
                    _c("Coarse Grinding Stone", 20, [("Coarse Stone", 2)])],
                 "note": "Save about 20 Coarse Grinding Stones for 145-155."}]},
            {"range": (90, 100), "options": [
                {"name": "Runed Copper Belt", "crafts": [_c("Runed Copper Belt", 10, [("Copper Bar", 10)])]}]},
            {"range": (100, 125), "options": [
                {"name": "Rough Bronze Leggings", "crafts": [_c("Rough Bronze Leggings", 25, [("Bronze Bar", 6)])]}]},
            {"range": (125, 155), "options": [
                {"name": "Heavy Grinding Stone, then Patterned Bronze Bracers", "crafts": [
                    _c("Heavy Grinding Stone", 35, [("Heavy Stone", 3)]),
                    _c("Patterned Bronze Bracers", 10, [("Bronze Bar", 5), ("Coarse Grinding Stone", 2)])],
                 "note": "Train Expert at 150. Keep extra Heavy Grinding Stones for 155-200."}]},
            {"range": (155, 190), "options": [
                {"name": "Green Iron Leggings, then Bracers", "crafts": [
                    _c("Green Iron Leggings", 10, [("Iron Bar", 8), ("Heavy Grinding Stone", 1), ("Green Dye", 1)]),
                    _c("Green Iron Bracers", 25, [("Iron Bar", 6), ("Green Dye", 1)])]}]},
            {"range": (190, 210), "options": [
                {"name": "Golden Scale Bracers, then Solid Sharpening Stone", "crafts": [
                    _c("Golden Scale Bracers", 10, [("Steel Bar", 5), ("Heavy Grinding Stone", 2)]),
                    _c("Solid Sharpening Stone", 20, [("Solid Stone", 1)])]}]},
            {"range": (210, 225), "options": [
                {"name": "Heavy Mithril Gauntlet", "crafts": [_c("Heavy Mithril Gauntlet", 15, [("Mithril Bar", 6), ("Mageweave Cloth", 4)])],
                 "note": "Train Artisan at 225."}]},
            {"range": (225, 250), "options": [
                {"name": "Mithril Scale Bracers, then Mithril Coif", "crafts": [
                    _c("Mithril Scale Bracers", 11, [("Mithril Bar", 8), ("Citrine", 2)]),
                    _c("Mithril Coif", 14, [("Mithril Bar", 10), ("Mageweave Cloth", 6)])],
                 "note": "Needs the Mithril Scale Bracers plans (limited-supply vendor)."},
                {"name": "Mithril Coif all the way", "crafts": [_c("Mithril Coif", 28, [("Mithril Bar", 10), ("Mageweave Cloth", 6)])],
                 "note": "No hard-to-get plans, but more Mithril."}]},
            {"range": (250, 260), "options": [
                {"name": "Dense Sharpening Stone", "crafts": [_c("Dense Sharpening Stone", 20, [("Dense Stone", 1)])]}]},
            {"range": (260, 300), "options": [
                {"name": "Thorium Bracers, then Imperial Plate Bracers", "crafts": [
                    _c("Thorium Bracers", 16, [("Thorium Bar", 12), ("Blue Power Crystal", 4)]),
                    _c("Imperial Plate Bracers", 26, [("Thorium Bar", 20), ("Star Ruby", 1)])]},
                {"name": "Imperial Plate Bracers all the way", "crafts": [
                    _c("Imperial Plate Bracers", 40, [("Thorium Bar", 20), ("Star Ruby", 1)])],
                 "note": "Skips the Power Crystals if they're scarce."}]},
        ]},

    "Leatherworking": {
        "kind": "craft",
        "intro": "Pairs with Skinning. Armor kits are the cheap filler; the Nightscape and Wicked Leather "
                 "pieces carry you to 300.",
        "trainers": "Expert at 150: Telonis (Darnassus) or Una (Thunder Bluff). Artisan at 225 (level 35): "
                    "Wark Nightsky (The Hinterlands) or Hahrana Ironhide (Camp Mojache, Feralas). Thread, dyes "
                    "and salt come from leatherworking supply vendors.",
        "steps": [
            {"range": (1, 45), "options": [
                {"name": "Light Armor Kit", "crafts": [_c("Light Armor Kit", 50, [("Light Leather", 1)])]}]},
            {"range": (45, 100), "options": [
                {"name": "Handstitched Cloak, then Embossed Gloves", "crafts": [
                    _c("Handstitched Leather Cloak", 16, [("Light Leather", 2), ("Coarse Thread", 1)]),
                    _c("Embossed Leather Gloves", 45, [("Light Leather", 3), ("Coarse Thread", 2)])],
                 "note": "Train Journeyman around 50."}]},
            {"range": (100, 125), "options": [
                {"name": "Fine Leather Belt", "crafts": [_c("Fine Leather Belt", 28, [("Light Leather", 6), ("Coarse Thread", 2)])]}]},
            {"range": (125, 155), "options": [
                {"name": "Dark Leather Boots, then Pants", "crafts": [
                    _c("Dark Leather Boots", 16, [("Medium Leather", 4), ("Fine Thread", 2), ("Gray Dye", 1)]),
                    _c("Dark Leather Pants", 22, [("Medium Leather", 12), ("Fine Thread", 1), ("Gray Dye", 1)])],
                 "note": "Train Expert at 150."}]},
            {"range": (155, 180), "options": [
                {"name": "Hillman's Gloves, then Heavy Armor Kit", "crafts": [
                    _c("Hillman's Leather Gloves", 10, [("Medium Leather", 14), ("Fine Thread", 4)]),
                    _c("Heavy Armor Kit", 15, [("Heavy Leather", 5), ("Fine Thread", 1)])]}]},
            {"range": (180, 205), "options": [
                {"name": "Barbaric Shoulders, Guardian Gloves, Dusky Bracers", "crafts": [
                    _c("Barbaric Shoulders", 10, [("Heavy Leather", 8), ("Cured Heavy Hide", 1), ("Fine Thread", 2)]),
                    _c("Guardian Gloves", 10, [("Heavy Leather", 4), ("Cured Heavy Hide", 1), ("Silken Thread", 1)]),
                    _c("Dusky Bracers", 5, [("Heavy Leather", 16), ("Black Dye", 1), ("Silken Thread", 2)])]}]},
            {"range": (205, 225), "options": [
                {"name": "Thick Armor Kit", "crafts": [_c("Thick Armor Kit", 20, [("Thick Leather", 5), ("Silken Thread", 1)])],
                 "note": "Keep 6 for the Artisan quest."},
                {"name": "Nightscape Headband", "crafts": [_c("Nightscape Headband", 20, [("Thick Leather", 5), ("Silken Thread", 2)])],
                 "note": "Keep 2 for the Artisan quest."}]},
            {"range": (225, 265), "options": [
                {"name": "Nightscape Headband, Pants, Boots", "crafts": [
                    _c("Nightscape Headband", 10, [("Thick Leather", 5), ("Silken Thread", 2)]),
                    _c("Nightscape Pants", 15, [("Thick Leather", 14), ("Silken Thread", 4)]),
                    _c("Nightscape Boots", 15, [("Thick Leather", 16), ("Silken Thread", 2)])]}]},
            {"range": (265, 300), "options": [
                {"name": "Wicked Leather Bracers, then Headband", "crafts": [
                    _c("Wicked Leather Bracers", 20, [("Rugged Leather", 8), ("Black Dye", 1), ("Rune Thread", 1)]),
                    _c("Wicked Leather Headband", 15, [("Rugged Leather", 12), ("Black Dye", 1), ("Rune Thread", 1)])]}]},
        ]},

    "Engineering": {
        "kind": "craft",
        "intro": "Pairs with Mining. Lots of the leveling crafts are parts that later recipes use, so "
                 "keep what you make. You also need a Blacksmith Hammer and an Arclight Spanner.",
        "trainers": "Expert at 150: Springspindle Fizzlegear (Ironforge) or Roxxik (Orgrimmar). Artisan at 225 "
                    "(level 35): Buzzek Bracketswing (Gadgetzan). Buy a Blacksmith Hammer from a blacksmithing supplier.",
        "steps": [
            {"range": (1, 30), "options": [
                {"name": "Rough Blasting Powder", "crafts": [_c("Rough Blasting Powder", 40, [("Rough Stone", 1)])],
                 "note": "Make about 60 - the bombs at 50-75 use them."}]},
            {"range": (30, 50), "options": [
                {"name": "Handful of Copper Bolts", "crafts": [_c("Handful of Copper Bolts", 30, [("Copper Bar", 1)])]}]},
            {"range": (50, 75), "options": [
                {"name": "Arclight Spanner, then Rough Copper Bombs", "crafts": [
                    _c("Arclight Spanner", 1, [("Copper Bar", 6)]),
                    _c("Rough Copper Bomb", 30, [("Copper Bar", 1), ("Handful of Copper Bolts", 1), ("Rough Blasting Powder", 2), ("Linen Cloth", 1)])]},
                {"name": "Arclight Spanner, then Copper Tubes", "crafts": [
                    _c("Arclight Spanner", 1, [("Copper Bar", 6)]),
                    _c("Copper Tube", 30, [("Copper Bar", 2), ("Weak Flux", 1)])],
                 "note": "Copper Tubes are needed for later gadgets."}]},
            {"range": (75, 100), "options": [
                {"name": "Coarse Blasting Powder, then Coarse Dynamite", "crafts": [
                    _c("Coarse Blasting Powder", 20, [("Coarse Stone", 1)]),
                    _c("Coarse Dynamite", 20, [("Coarse Blasting Powder", 1), ("Linen Cloth", 1)])]}]},
            {"range": (100, 125), "options": [
                {"name": "Clockwork Box", "crafts": [_c("Clockwork Box", 25, [("Bronze Bar", 1), ("Handful of Copper Bolts", 2)])]},
                {"name": "Bronze Tube", "crafts": [_c("Bronze Tube", 25, [("Bronze Bar", 2), ("Weak Flux", 1)])]}]},
            {"range": (125, 150), "options": [
                {"name": "Heavy Blasting Powder, then Whirring Bronze Gizmo", "crafts": [
                    _c("Heavy Blasting Powder", 15, [("Heavy Stone", 1)]),
                    _c("Whirring Bronze Gizmo", 15, [("Bronze Bar", 2), ("Wool Cloth", 1)])],
                 "note": "Train Expert at 150. Keep the powder and gizmos for Explosive Sheep."}]},
            {"range": (150, 175), "options": [
                {"name": "Bronze Framework, then Explosive Sheep", "crafts": [
                    _c("Bronze Framework", 15, [("Bronze Bar", 2), ("Medium Leather", 1), ("Wool Cloth", 1)]),
                    _c("Explosive Sheep", 15, [("Heavy Blasting Powder", 2), ("Whirring Bronze Gizmo", 1), ("Bronze Framework", 1), ("Wool Cloth", 2)])]},
                {"name": "Iron Strut", "crafts": [_c("Iron Strut", 25, [("Iron Bar", 2)])],
                 "note": "One simple recipe instead of a parts chain."}]},
            {"range": (175, 200), "options": [
                {"name": "Solid Blasting Powder, then Mithril Tube", "crafts": [
                    _c("Solid Blasting Powder", 25, [("Solid Stone", 2)]),
                    _c("Mithril Tube", 7, [("Mithril Bar", 3)])],
                 "note": "Make about 60 Solid Blasting Powder - triggers use it next."}]},
            {"range": (200, 250), "options": [
                {"name": "Unstable Trigger, then Mithril Casing", "crafts": [
                    _c("Unstable Trigger", 20, [("Mithril Bar", 1), ("Mageweave Cloth", 1), ("Solid Blasting Powder", 1)]),
                    _c("Mithril Casing", 40, [("Mithril Bar", 3)])],
                 "note": "Train Artisan at 225."}]},
            {"range": (250, 260), "options": [
                {"name": "Dense Blasting Powder", "crafts": [_c("Dense Blasting Powder", 20, [("Dense Stone", 2)])]}]},
            {"range": (260, 300), "options": [
                {"name": "Thorium Widget, then Thorium Tube", "crafts": [
                    _c("Thorium Widget", 25, [("Thorium Bar", 3), ("Runecloth", 1)]),
                    _c("Thorium Tube", 20, [("Thorium Bar", 6)])]},
                {"name": "Thorium Widget, then Thorium Shells", "crafts": [
                    _c("Thorium Widget", 25, [("Thorium Bar", 3), ("Runecloth", 1)]),
                    _c("Thorium Shells", 25, [("Thorium Bar", 2), ("Dense Blasting Powder", 1)])],
                 "note": "Shells use less Thorium per craft and sell to hunters."}]},
        ]},

    "Enchanting": {
        "kind": "craft",
        "intro": "Materials come from disenchanting green items (or the AH). Enchants aren't items, so you "
                 "can't sell your leveling crafts - but you can offer them in trade chat for tips. Each tier "
                 "needs a new runed rod.",
        "trainers": "Expert at 150 from the enchanting trainers in the capital cities. Artisan at 225 "
                    "(level 35): Annora, inside the Uldaman dungeon. Formulas for Lesser Strength and Minor Agility are sold by "
                    "Dalria (Ashenvale) or Kulwia (Stonetalon) - limited supply. Copper Rod and Simple Wood "
                    "come from vendors.",
        "steps": [
            {"range": (1, 2), "options": [
                {"name": "Runed Copper Rod", "crafts": [_c("Runed Copper Rod", 1, [("Copper Rod", 1), ("Strange Dust", 1), ("Lesser Magic Essence", 1)])]}]},
            {"range": (2, 90), "options": [
                {"name": "Enchant Bracer - Minor Health", "crafts": [_c("Enchant Bracer - Minor Health", 105, [("Strange Dust", 1)], None)]}]},
            {"range": (90, 110), "options": [
                {"name": "Minor Stamina, Runed Silver Rod, Greater Magic Wand", "crafts": [
                    _c("Enchant Bracer - Minor Stamina", 10, [("Strange Dust", 3)], None),
                    _c("Runed Silver Rod", 1, [("Silver Rod", 1), ("Strange Dust", 6), ("Greater Magic Essence", 3), ("Shadowgem", 1)]),
                    _c("Greater Magic Wand", 10, [("Simple Wood", 1), ("Greater Magic Essence", 1)])]},
                {"name": "Minor Stamina all the way (to 110)", "crafts": [
                    _c("Enchant Bracer - Minor Stamina", 20, [("Strange Dust", 3)], None),
                    _c("Runed Silver Rod", 1, [("Silver Rod", 1), ("Strange Dust", 6), ("Greater Magic Essence", 3), ("Shadowgem", 1)])],
                 "note": "Better when Strange Dust is cheap and Greater Magic Essence isn't."}]},
            {"range": (110, 155), "options": [
                {"name": "Cloak - Minor Agility, then Bracer - Lesser Stamina", "crafts": [
                    _c("Enchant Cloak - Minor Agility", 25, [("Lesser Astral Essence", 1)], None),
                    _c("Enchant Bracer - Lesser Stamina", 20, [("Soul Dust", 2)], None)],
                 "note": "Minor Agility formula is a limited-supply vendor item."}]},
            {"range": (155, 180), "options": [
                {"name": "Runed Golden Rod, then Bracer - Lesser Strength", "crafts": [
                    _c("Runed Golden Rod", 1, [("Golden Rod", 1), ("Iridescent Pearl", 1), ("Greater Astral Essence", 2), ("Soul Dust", 2)]),
                    _c("Enchant Bracer - Lesser Strength", 25, [("Soul Dust", 2)], None)]}]},
            {"range": (180, 225), "options": [
                {"name": "Bracer - Strength, Runed Truesilver Rod, Cloak - Greater Defense", "crafts": [
                    _c("Enchant Bracer - Strength", 50, [("Vision Dust", 1)], None),
                    _c("Runed Truesilver Rod", 1, [("Truesilver Rod", 1), ("Black Pearl", 1), ("Greater Mystic Essence", 2), ("Vision Dust", 2)]),
                    _c("Enchant Cloak - Greater Defense", 5, [("Vision Dust", 3)], None)]}]},
            {"range": (225, 255), "options": [
                {"name": "Boots - Stamina, Chest - Superior Health, Boots - Agility", "crafts": [
                    _c("Enchant Boots - Stamina", 10, [("Vision Dust", 5)], None),
                    _c("Enchant Chest - Superior Health", 10, [("Vision Dust", 6)], None),
                    _c("Enchant Boots - Agility", 10, [("Greater Nether Essence", 2)], None)]}]},
            {"range": (255, 300), "options": [
                {"name": "Bracer - Greater Strength, then Shield - Greater Stamina", "crafts": [
                    _c("Enchant Bracer - Greater Strength", 5, [("Dream Dust", 2), ("Greater Nether Essence", 1)], None),
                    _c("Enchant Shield - Greater Stamina", 45, [("Dream Dust", 10)], None)],
                 "note": "A Runed Arcanite Rod (sold in Moonglade) is needed for top-end enchants, not for leveling."}]},
        ]},

    "Mining": {
        "kind": "gather",
        "intro": "Each new ore unlocks at a set skill; mine whatever you can while you level, then move "
                 "zones as the nodes turn grey. Smelting bars levels Mining too.",
        "trainers": "Journeyman at 50, Expert at 125 (level 20), Artisan at 200 (level 35) from any mining "
                    "trainer. Tin unlocks at 65, Silver 75, Iron 125, Gold 155, Mithril 175, Truesilver 230, "
                    "Small Thorium 245, Rich Thorium 275.",
        "steps": [
            {"range": (1, 65), "options": [
                {"name": "Alliance: Elwynn Forest, Dun Morogh, Darkshore", "gathers": ["Copper Ore", "Rough Stone"],
                 "note": "Copper sits along the hills and mine entrances. Smelt Copper Bars for easy extra points."},
                {"name": "Horde: Durotar, Mulgore, Tirisfal Glades", "gathers": ["Copper Ore", "Rough Stone"],
                 "note": "Durotar's coastal cliffs and canyons are dense with copper."}]},
            {"range": (65, 125), "options": [
                {"name": "Alliance: Redridge, Wetlands, Westfall hills", "gathers": ["Tin Ore", "Copper Ore", "Coarse Stone", "Silver Ore"]},
                {"name": "Horde: The Barrens, Stonetalon, Hillsbrad", "gathers": ["Tin Ore", "Copper Ore", "Coarse Stone", "Silver Ore"]}]},
            {"range": (125, 175), "options": [
                {"name": "Arathi Highlands / Desolace", "gathers": ["Iron Ore", "Gold Ore", "Heavy Stone", "Tin Ore"],
                 "note": "Both factions. Loop the zone edges."},
                {"name": "Thousand Needles / Stranglethorn Vale", "gathers": ["Iron Ore", "Gold Ore", "Heavy Stone"],
                 "note": "Watch for the opposite faction in Stranglethorn."}]},
            {"range": (175, 250), "options": [
                {"name": "Badlands / Searing Gorge", "gathers": ["Mithril Ore", "Truesilver Ore", "Solid Stone", "Iron Ore"],
                 "note": "Very dense in Mithril; Truesilver from 230."},
                {"name": "Tanaris / Hinterlands / Felwood", "gathers": ["Mithril Ore", "Truesilver Ore", "Solid Stone"]}]},
            {"range": (250, 300), "options": [
                {"name": "Un'Goro Crater", "gathers": ["Thorium Ore", "Dense Stone", "Mithril Ore"],
                 "note": "Lots of Small Thorium around the edges and caves."},
                {"name": "Burning Steppes / Winterspring / Eastern Plaguelands", "gathers": ["Thorium Ore", "Dense Stone", "Truesilver Ore"],
                 "note": "Rich Thorium from 275."}]},
        ]},

    "Herbalism": {
        "kind": "gather",
        "intro": "Herbs grow in specific terrain - learn what each looks like on the minimap and route "
                 "through the zones where several overlap.",
        "trainers": "Journeyman at 50, Expert at 125 (level 20), Artisan at 200 (level 35). Mageroyal 50, "
                    "Briarthorn 70, Bruiseweed 100, Wild Steelbloom 115, Kingsblood 125, Liferoot 150, "
                    "Goldthorn 170, Khadgar's Whisker 185, Sungrass 230, Gromsblood 250, Dreamfoil 270, "
                    "Mountain Silversage 280, Plaguebloom 285, Black Lotus 300.",
        "steps": [
            {"range": (1, 70), "options": [
                {"name": "Any starting zone", "gathers": ["Peacebloom", "Silverleaf", "Earthroot", "Mageroyal"],
                 "note": "Elwynn, Dun Morogh, Teldrassil, Durotar, Mulgore, Tirisfal - all good."}]},
            {"range": (70, 125), "options": [
                {"name": "Alliance: Darkshore, Loch Modan, Redridge", "gathers": ["Briarthorn", "Mageroyal", "Bruiseweed", "Stranglekelp"]},
                {"name": "Horde: The Barrens, Silverpine Forest", "gathers": ["Briarthorn", "Mageroyal", "Bruiseweed", "Stranglekelp"]}]},
            {"range": (125, 170), "options": [
                {"name": "Hillsbrad Foothills / Wetlands", "gathers": ["Kingsblood", "Wild Steelbloom", "Liferoot", "Bruiseweed"]},
                {"name": "Ashenvale / Stonetalon / Thousand Needles", "gathers": ["Kingsblood", "Wild Steelbloom", "Liferoot"]}]},
            {"range": (170, 230), "options": [
                {"name": "Arathi Highlands / Stranglethorn Vale", "gathers": ["Goldthorn", "Fadeleaf", "Khadgar's Whisker", "Kingsblood"]},
                {"name": "Feralas / Dustwallow Marsh / Hinterlands", "gathers": ["Goldthorn", "Khadgar's Whisker", "Purple Lotus", "Firebloom"]}]},
            {"range": (230, 300), "options": [
                {"name": "Un'Goro Crater / Felwood", "gathers": ["Sungrass", "Golden Sansam", "Dreamfoil", "Gromsblood"],
                 "note": "Felwood also has Plaguebloom from 285."},
                {"name": "Plaguelands / Winterspring / Burning Steppes", "gathers": ["Mountain Silversage", "Plaguebloom", "Icecap", "Dreamfoil"]}]},
        ]},

    "Skinning": {
        "kind": "gather",
        "intro": "You can skin a beast if your skill is at least its level x 5 (or up to level 10 for low "
                 "mobs). Skin everything you kill while questing - it levels almost on its own.",
        "trainers": "Journeyman at 50, Expert at 125 (level 20), Artisan at 200 (level 35) from any skinning trainer.",
        "steps": [
            {"range": (1, 75), "options": [
                {"name": "Starting zones, then Westfall / Barrens", "gathers": ["Light Leather", "Ruined Leather Scraps", "Light Hide"]}]},
            {"range": (75, 150), "options": [
                {"name": "Alliance: Redridge, Wetlands, Duskwood", "gathers": ["Medium Leather", "Light Leather", "Medium Hide"]},
                {"name": "Horde: Stonetalon, Hillsbrad, Thousand Needles", "gathers": ["Medium Leather", "Light Leather", "Medium Hide"]}]},
            {"range": (150, 225), "options": [
                {"name": "Arathi Highlands / Stranglethorn Vale", "gathers": ["Heavy Leather", "Thick Leather", "Heavy Hide"]},
                {"name": "Desolace / Dustwallow Marsh / Badlands", "gathers": ["Heavy Leather", "Thick Leather"]}]},
            {"range": (225, 300), "options": [
                {"name": "Feralas / Tanaris / Hinterlands", "gathers": ["Thick Leather", "Rugged Leather", "Thick Hide"]},
                {"name": "Un'Goro Crater / Winterspring / Burning Steppes", "gathers": ["Rugged Leather", "Thick Leather", "Rugged Hide"],
                 "note": "Un'Goro devilsaurs drop valuable Devilsaur Leather."}]},
        ]},

    "Fishing": {
        "kind": "gather",
        "intro": "Fishing goes by catches, not zones - each catch is a skill-up chance. Fish in waters "
                 "where you rarely fish up junk, and cook what you catch for Cooking skill too.",
        "trainers": "Journeyman at 50. Expert: buy Expert Fishing - The Bass and You from Old Man Heming "
                    "(Booty Bay) at 125+. Artisan at 225 (level 35): Nat Pagle's quest in Dustwallow Marsh.",
        "steps": [
            {"range": (1, 75), "options": [
                {"name": "Capital cities and starting zones", "gathers": ["Raw Brilliant Smallfish", "Raw Slitherskin Mackerel", "Raw Longjaw Mud Snapper"],
                 "note": "Stormwind canals, Ironforge, Orgrimmar, Darnassus - safe and close to the trainer."}]},
            {"range": (75, 150), "options": [
                {"name": "Westfall / Darkshore / Loch Modan", "gathers": ["Raw Longjaw Mud Snapper", "Raw Bristle Whisker Catfish", "Oily Blackmouth"]},
                {"name": "The Barrens / Silverpine Forest", "gathers": ["Raw Longjaw Mud Snapper", "Raw Bristle Whisker Catfish", "Oily Blackmouth"]}]},
            {"range": (150, 225), "options": [
                {"name": "Desolace / Stranglethorn Vale coast", "gathers": ["Raw Bristle Whisker Catfish", "Raw Rockscale Cod", "Firefin Snapper"]},
                {"name": "Arathi Highlands / Dustwallow Marsh", "gathers": ["Raw Mithril Head Trout", "Raw Bristle Whisker Catfish", "Oily Blackmouth"]}]},
            {"range": (225, 300), "options": [
                {"name": "Tanaris / Feralas coast", "gathers": ["Raw Spotted Yellowtail", "Raw Glossy Mightfish", "Large Raw Mightfish"]},
                {"name": "Winterspring / Azshara / Un'Goro", "gathers": ["Raw Nightfin Snapper", "Raw Sunscale Salmon", "Winter Squid", "Raw Whitescale Salmon"],
                 "note": "Nightfin Snapper and Sunscale Salmon only bite at certain times of day."}]},
        ]},
}

GUIDES_DIR = os.path.join(HERE, "guides")
PROGRESS_PATH = os.path.join(HERE, "guide_progress.json")


def load_guide(profession):
    """A customised copy (guides/<Profession>.json) wins over the built-in guide."""
    path = os.path.join(GUIDES_DIR, f"{profession}.json")
    if os.path.exists(path):
        g = load_json(path, None)
        if g:
            g["custom"] = True
            return g
    g = GUIDES.get(profession)
    return json.loads(json.dumps(g)) if g else None       # deep copy; tuples become lists


def export_guide(profession):
    """Write the guide to guides/<Profession>.json for editing. Returns the path."""
    os.makedirs(GUIDES_DIR, exist_ok=True)
    path = os.path.join(GUIDES_DIR, f"{profession}.json")
    if not os.path.exists(path):
        g = load_guide(profession) or {"kind": "craft", "intro": "", "trainers": "", "steps": []}
        g.pop("custom", None)
        with open(path, "w") as f:
            json.dump(g, f, indent=2)
    return path


def guide_item_names(guide):
    names = set()
    for step in guide.get("steps", []):
        for opt in step.get("options", []):
            for recipe, times, mats, product in opt.get("crafts", []):
                names.update(m for m, _q in mats)
                if product:
                    names.add(product)
            names.update(opt.get("gathers", []))
    return sorted(names)


def guide_prices(api, guide):
    """name -> {'id', 'each', 'how' ('AH' / 'vendor' / None), 'listed'} at today's prices."""
    names = guide_item_names(guide)
    sources = get_sources(api)
    out = {}
    for name in names:
        e = resolve_cached(api, name)
        if not e:
            out[name] = {"id": None, "each": None, "how": None, "listed": 0}
            continue
        s = item_summary(sources, e["id"])
        if s:
            out[name] = {"id": e["id"], "each": s["cheap10"], "how": "AH", "listed": s["quantity"]}
        else:
            vp = vendor_price(api, e["id"])
            out[name] = {"id": e["id"], "each": vp or None, "how": "vendor" if vp else None, "listed": 0}
    save_info()
    return {"prices": out, "ts": api.snapshot_time}


def option_cost(opt, prices):
    """(materials cost, value of the crafts if sold, list of unpriced materials) for one option."""
    cost = value = 0
    missing = []
    for recipe, times, mats, product in opt.get("crafts", []):
        for m, q in mats:
            p = prices.get(m) or {}
            if p.get("each") is None:
                missing.append(m)
            else:
                cost += p["each"] * q * times
        if product:
            p = prices.get(product) or {}
            if p.get("how") == "AH":
                value += p["each"] * times * (1 - AH_CUT)
    return cost, value, sorted(set(missing))


def option_value(opt, prices):
    """Average market value of what a gathering option yields (per item)."""
    vals = [prices[g]["each"] for g in opt.get("gathers", []) if (prices.get(g) or {}).get("how") == "AH"]
    return sum(vals) / len(vals) if vals else None


def load_progress():
    return load_json(PROGRESS_PATH, {})


def save_progress(data):
    save_json(PROGRESS_PATH, data)


# ---------- characters and gear upgrades ----------
# WoW: Forever looks characters up by "firstname-surname" (no realm); retail uses realm/name.
# Characters appear in the API from level 10, after logging out once.

ARMOR, WEAPON = 4, 2
# equipment slot -> [(item class, [inventory types])]
SLOT_SEARCH = {
    "HEAD": [(ARMOR, ["HEAD"])], "NECK": [(ARMOR, ["NECK"])], "SHOULDER": [(ARMOR, ["SHOULDER"])],
    "CHEST": [(ARMOR, ["CHEST", "ROBE"])], "WAIST": [(ARMOR, ["WAIST"])], "LEGS": [(ARMOR, ["LEGS"])],
    "FEET": [(ARMOR, ["FEET"])], "WRIST": [(ARMOR, ["WRIST"])], "HANDS": [(ARMOR, ["HAND"])],
    "FINGER_1": [(ARMOR, ["FINGER"])], "FINGER_2": [(ARMOR, ["FINGER"])],
    "TRINKET_1": [(ARMOR, ["TRINKET"])], "TRINKET_2": [(ARMOR, ["TRINKET"])], "BACK": [(ARMOR, ["CLOAK"])],
    "MAIN_HAND": [(WEAPON, ["WEAPON", "WEAPONMAINHAND", "TWOHWEAPON"])],
    "OFF_HAND": [(ARMOR, ["SHIELD", "HOLDABLE"]), (WEAPON, ["WEAPON", "WEAPONOFFHAND"])],
    "RANGED": [(WEAPON, ["RANGED", "RANGEDRIGHT", "THROWN"])],
}
SLOT_NAMES = {"HEAD": "Head", "NECK": "Neck", "SHOULDER": "Shoulder", "CHEST": "Chest", "WAIST": "Waist",
              "LEGS": "Legs", "FEET": "Feet", "WRIST": "Wrist", "HANDS": "Hands", "FINGER_1": "Ring 1",
              "FINGER_2": "Ring 2", "TRINKET_1": "Trinket 1", "TRINKET_2": "Trinket 2", "BACK": "Back",
              "MAIN_HAND": "Main hand", "OFF_HAND": "Off hand", "RANGED": "Ranged"}
BODY_ARMOR_SLOTS = {"HEAD", "SHOULDER", "CHEST", "WAIST", "LEGS", "FEET", "WRIST", "HANDS"}

# Classic armor (cloth 1, leather 2, mail 3, plate 4) and weapon skills (subclass ids) per class.
CLOTH, LEATHER, MAIL, PLATE, SHIELD_SUB = 1, 2, 3, 4, 6
AXE1, AXE2, BOW, GUN, MACE1, MACE2, POLEARM, SWORD1, SWORD2 = 0, 1, 2, 3, 4, 5, 6, 7, 8
STAFF, FIST, DAGGER, THROWN, XBOW, WAND = 10, 13, 15, 16, 18, 19
CLASS_GEAR = {
    "Warrior": {"armor": (MAIL, PLATE), "shield": True, "dual": True,
                "weapons": {AXE1, AXE2, BOW, GUN, MACE1, MACE2, POLEARM, SWORD1, SWORD2, STAFF, FIST, DAGGER, THROWN, XBOW}},
    "Paladin": {"armor": (MAIL, PLATE), "shield": True, "dual": False,
                "weapons": {AXE1, AXE2, MACE1, MACE2, POLEARM, SWORD1, SWORD2}},
    "Hunter": {"armor": (LEATHER, MAIL), "shield": False, "dual": True,
               "weapons": {AXE1, AXE2, BOW, GUN, POLEARM, SWORD1, SWORD2, STAFF, FIST, DAGGER, THROWN, XBOW}},
    "Rogue": {"armor": (LEATHER, LEATHER), "shield": False, "dual": True,
              "weapons": {BOW, GUN, MACE1, SWORD1, FIST, DAGGER, THROWN, XBOW}},
    "Priest": {"armor": (CLOTH, CLOTH), "shield": False, "dual": False, "weapons": {MACE1, STAFF, DAGGER, WAND}},
    "Mage": {"armor": (CLOTH, CLOTH), "shield": False, "dual": False, "weapons": {SWORD1, STAFF, DAGGER, WAND}},
    "Warlock": {"armor": (CLOTH, CLOTH), "shield": False, "dual": False, "weapons": {SWORD1, STAFF, DAGGER, WAND}},
    "Shaman": {"armor": (LEATHER, MAIL), "shield": True, "dual": False,
               "weapons": {AXE1, AXE2, MACE1, MACE2, STAFF, FIST, DAGGER}},
    "Druid": {"armor": (LEATHER, LEATHER), "shield": False, "dual": False,
              "weapons": {MACE1, MACE2, STAFF, FIST, DAGGER}},
}

# Rough leveling stat weights. DPS = weapon damage per second (melee), RDPS = ranged weapon DPS.
STAT_PRESETS = {
    "Warrior": {"Damage (Arms / Fury)": {"STRENGTH": 1.0, "AGILITY": 0.6, "STAMINA": 0.4, "DPS": 3.0, "ARMOR": 0.01, "RDPS": 0.3},
                "Tank (Protection)": {"STAMINA": 1.0, "AGILITY": 0.6, "STRENGTH": 0.5, "ARMOR": 0.06, "DPS": 1.0}},
    "Paladin": {"Retribution": {"STRENGTH": 1.0, "AGILITY": 0.5, "STAMINA": 0.4, "INTELLECT": 0.3, "DPS": 3.0, "ARMOR": 0.01},
                "Holy": {"INTELLECT": 1.0, "SPIRIT": 0.4, "STAMINA": 0.3},
                "Protection": {"STAMINA": 1.0, "STRENGTH": 0.5, "AGILITY": 0.4, "INTELLECT": 0.3, "ARMOR": 0.06, "DPS": 1.0}},
    "Hunter": {"Damage": {"AGILITY": 1.0, "STAMINA": 0.4, "INTELLECT": 0.3, "STRENGTH": 0.1, "RDPS": 4.0, "DPS": 0.5}},
    "Rogue": {"Damage": {"AGILITY": 1.0, "STRENGTH": 0.5, "STAMINA": 0.4, "DPS": 3.5}},
    "Priest": {"Healing / Shadow": {"INTELLECT": 1.0, "SPIRIT": 0.7, "STAMINA": 0.4}},
    "Mage": {"Damage": {"INTELLECT": 1.0, "STAMINA": 0.5, "SPIRIT": 0.3}},
    "Warlock": {"Damage": {"STAMINA": 1.0, "INTELLECT": 0.8, "SPIRIT": 0.3}},
    "Shaman": {"Enhancement": {"STRENGTH": 0.8, "AGILITY": 0.6, "INTELLECT": 0.4, "STAMINA": 0.4, "DPS": 3.0},
               "Elemental / Restoration": {"INTELLECT": 1.0, "SPIRIT": 0.4, "STAMINA": 0.4}},
    "Druid": {"Feral (Cat / Bear)": {"AGILITY": 1.0, "STRENGTH": 0.6, "STAMINA": 0.6, "ARMOR": 0.02},
              "Balance / Restoration": {"INTELLECT": 1.0, "SPIRIT": 0.6, "STAMINA": 0.4}},
}
DEFAULT_WEIGHTS = {"STAMINA": 1.0, "STRENGTH": 0.5, "AGILITY": 0.5, "INTELLECT": 0.5, "SPIRIT": 0.3, "DPS": 1.0, "RDPS": 1.0}
CHARACTERS_PATH = os.path.join(HERE, "characters.json")
ITEM_STATS_PATH = os.path.join(HERE, "item_stats.json")


def char_slug(name, surname=None):
    parts = [p.strip().lower() for p in (name, surname) if p and p.strip()]
    return urllib.parse.quote("-".join(parts).replace(" ", "-"))


def _d(x):
    return x if isinstance(x, dict) else {}


def _val(x):
    """A number from {'value': 5}, {'display_string': 'Requires Level 5'}, 5 or '5'."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return x
    if isinstance(x, dict):
        for k in ("value", "display_string", "display"):
            if k in x:
                v = _val(x[k])
                if v is not None:
                    return v
        return None
    if isinstance(x, str):
        m = re.search(r"-?\d+(?:\.\d+)?", x.replace(",", ""))
        return float(m.group()) if m else None
    return None


def _type(x):
    if isinstance(x, dict):
        return x.get("type") or x.get("id")
    return x


INV_ALIASES = {"2HWEAPON": "TWOHWEAPON", "TWO_HAND": "TWOHWEAPON", "HANDS": "HAND", "BACK": "CLOAK",
               "SHOULDERS": "SHOULDER", "WRISTS": "WRIST", "FINGERS": "FINGER", "RANGED_RIGHT": "RANGEDRIGHT",
               "MAINHAND": "WEAPONMAINHAND", "OFFHAND": "WEAPONOFFHAND", "WEAPON_MAIN_HAND": "WEAPONMAINHAND",
               "WEAPON_OFF_HAND": "WEAPONOFFHAND", "ONE_HAND": "WEAPON"}


def norm_inv(x):
    t = _type(x)
    if not isinstance(t, str):
        return None
    t = t.upper().replace("INVTYPE_", "")
    return INV_ALIASES.get(t, t)


def _int(x):
    v = _val(x)
    return int(round(v)) if v is not None else None


def parse_gear(d):
    """Stats, armor, weapon DPS and requirements from an equipped item or an item's preview.
    Tolerates fields arriving as objects, numbers or text."""
    d = _d(d)
    stats = {}
    for st in d.get("stats") or []:
        if not isinstance(st, dict):
            continue
        t = _type(st.get("type"))
        v = _val(st.get("value"))
        if isinstance(t, str) and v is not None:
            stats[t.upper()] = stats.get(t.upper(), 0) + v
    weapon = _d(d.get("weapon"))
    req = _int(_d(d.get("requirements")).get("level"))
    if req is None:
        req = _int(d.get("required_level"))
    sub = d.get("item_subclass")
    q = _type(d.get("quality"))
    return {"stats": stats, "armor": _val(d.get("armor")) or 0, "dps": _val(weapon.get("dps")) or 0,
            "req": req, "ilvl": _int(d.get("level")),
            "sub_id": _d(sub).get("id"), "sub": _loc(_d(sub).get("name")) or (sub if isinstance(sub, str) else None),
            "inv": norm_inv(d.get("inventory_type")),
            "q": q.upper() if isinstance(q, str) else None}


def get_character(api, name, surname=None, realm=None):
    """Profile and equipped gear. Raises ApiError (404 = not found)."""
    if api.game == "forever":
        path = f"/profile/wow/character/{char_slug(name, surname)}"
    else:
        path = f"/profile/wow/character/{char_slug(realm or '')}/{char_slug(name)}"
    prof = api.get(path, "profile")
    try:
        eq = api.get(path + "/equipment", "profile")
    except ApiError:
        eq = {}
    gear = []
    for it in _d(eq).get("equipped_items", []) or []:
        if not isinstance(it, dict):
            continue
        slot = _type(it.get("slot"))
        slot = slot.upper() if isinstance(slot, str) else slot
        g = parse_gear(it)
        g.update({"slot": slot, "slot_name": SLOT_NAMES.get(slot, _loc(_d(it.get("slot")).get("name")) or slot),
                  "id": _d(it.get("item")).get("id") or it.get("id"), "name": _loc(it.get("name"))})
        gear.append(g)
    prof = _d(prof)
    ruleset = prof.get("ruleset") or {}
    return {"name": prof.get("name") or name, "surname": prof.get("surname") or surname or "",
            "realm": _loc(_d(prof.get("realm")).get("name")) or realm or "",
            "ruleset": _loc(ruleset.get("name")) if isinstance(ruleset, dict) else ruleset,
            "level": _int(prof.get("level")) or 0,
            "cls": _loc(_d(prof.get("character_class")).get("name")) or "",
            "race": _loc(_d(prof.get("race")).get("name")) or "",
            "faction": _loc(_d(prof.get("faction")).get("name")) or "",
            "ilvl": prof.get("equipped_item_level") or prof.get("average_item_level"),
            "gear": gear, "game": api.game}


def _member(d, inv_type=None):
    g = parse_gear(d)
    return {"id": d.get("id"), "name": _loc(d.get("name")), "ilvl": g["ilvl"],
            "req": d.get("required_level", g["req"]), "sub_id": g["sub_id"], "q": g["q"],
            "inv": g["inv"] or inv_type, "preview": parse_gear(d["preview_item"]) if d.get("preview_item") else None}


def _search_all(api, params, max_pages):
    out, page = [], 1
    params = {**params, "orderby": "id", "_pageSize": 1000}
    while page <= max_pages:
        try:
            res = api.get("/data/wow/search/item", "static", **params, _page=page)
        except ApiError:
            if page == 1 and params["_pageSize"] == 1000:
                params["_pageSize"] = 100           # some API versions cap the page size
                continue
            break
        out.extend(r.get("data", {}) for r in res.get("results", []))
        if page >= (res.get("pageCount") or 1):
            break
        page += 1
    return out


def class_members(api, item_class):
    """Every armor (4) or weapon (2) item, found by category alone. Cached a week once found."""
    path = os.path.join(CACHE_DIR, f"{api.game}_{api.region}_gearclass_{item_class}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < RECIPE_SECONDS:
        cached = load_json(path, [])
        if cached:
            return cached
    out = [_member(d) for d in _search_all(api, {"item_class.id": item_class}, 20)]
    if out:
        os.makedirs(CACHE_DIR, exist_ok=True)
        save_json(path, out)
    return out


def slot_members(api, item_class, inv_type):
    """Every item of one inventory type. Tries the slot search first, then the whole category
    filtered by slot. Only non-empty results are cached (for a week)."""
    path = os.path.join(CACHE_DIR, f"{api.game}_{api.region}_slot2_{item_class}_{inv_type}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < RECIPE_SECONDS:
        cached = load_json(path, [])
        if cached:
            return cached
    out = [_member(d, inv_type) for d in
           _search_all(api, {"item_class.id": item_class, "inventory_type.type": inv_type}, 10)]
    out = [m for m in out if m["inv"] == inv_type]
    if not out:
        out = [m for m in class_members(api, item_class) if m["inv"] == inv_type]
    if out:
        os.makedirs(CACHE_DIR, exist_ok=True)
        save_json(path, out)
    return out


def item_gear(api, item_id):
    """Full stats for one item (from its preview). Cached permanently."""
    cache = load_json(ITEM_STATS_PATH, {})
    key = f"{api.game}:{item_id}"
    if key in cache:
        return cache[key] if not cache[key].get("missing") else None
    try:
        d = api.get(f"/data/wow/item/{item_id}", "static")
    except ApiError as e:
        if e.code == 404:             # Forever has no data for many Classic-era items
            cache[key] = {"missing": True}
            save_json(ITEM_STATS_PATH, cache)
        return None
    g = parse_gear(d.get("preview_item") or d)
    base = parse_gear(d)
    for k in ("ilvl", "req", "sub_id", "inv", "q"):
        if g.get(k) is None:
            g[k] = base.get(k)
    if g["req"] is None:
        g["req"] = d.get("required_level")
    g["name"] = _loc(d.get("name"))
    g["cls_id"] = (d.get("item_class") or {}).get("id")
    cache[key] = g
    save_json(ITEM_STATS_PATH, cache)
    return g


def ah_gear_pool(api, sources, progress=None, limit=400):
    """Last resort: learn what gear is for sale by reading the listed items themselves.
    Fetches up to `limit` not-yet-known items per scan; everything is cached for next time."""
    cache = load_json(ITEM_STATS_PATH, {})
    ids = set()
    for _label, book in sources:
        ids.update(book)
    skip = {"Trade Goods", "Consumable", "Recipe", "Reagent", "Quest", "Container", "Projectile", "Quiver", "Key"}
    todo = [i for i in ids if f"{api.game}:{i}" not in cache and cached_info(api.game, i).get("cls") not in skip]
    for n, i in enumerate(todo[:limit]):
        if progress and n % 10 == 0:
            progress(n, min(len(todo), limit), "items for sale")
        item_gear(api, i)
    cache = load_json(ITEM_STATS_PATH, {})
    pool = []
    for i in ids:
        g = cache.get(f"{api.game}:{i}")
        if g and not g.get("missing") and g.get("cls_id") in (ARMOR, WEAPON) and g.get("inv"):
            pool.append({"id": i, "name": g.get("name") or f"Item {i}", "ilvl": g.get("ilvl"), "req": g.get("req"),
                         "sub_id": g.get("sub_id"), "q": g.get("q"), "inv": g["inv"], "preview": g,
                         "cls_id": g["cls_id"]})
    unknown = sum(1 for i in ids if (cache.get(f"{api.game}:{i}") or {}).get("missing"))
    return pool, max(0, len(todo) - limit), unknown


NON_GEAR = {"Trade Goods", "Consumable", "Recipe", "Reagent", "Quest", "Container", "Projectile",
            "Quiver", "Key", "Gem", "Miscellaneous", "Glyph", "Battle Pets"}


def gear_from_item(d):
    d = _d(d)
    g = parse_gear(d.get("preview_item") or d)
    base = parse_gear(d)
    for k in ("ilvl", "req", "sub_id", "sub", "inv", "q"):
        if g.get(k) is None:
            g[k] = base.get(k)
    if not g["stats"]:
        g["stats"] = base["stats"]
    g["name"] = _loc(d.get("name"))
    g["cls_id"] = _d(d.get("item_class")).get("id")
    return g


def fetch_items(api, ids, progress=None, workers=8):
    """Look up many items at once (8 in parallel). Results - including 'Blizzard has no data'
    - are remembered permanently, so each item is only ever fetched once."""
    from concurrent.futures import ThreadPoolExecutor
    cache = load_json(ITEM_STATS_PATH, {})
    todo = [i for i in ids if f"{api.game}:{i}" not in cache]

    def one(i):
        try:
            return i, api.get(f"/data/wow/item/{i}", "static"), None
        except ApiError as e:
            return i, None, e.code
        except (SystemExit, Exception):
            return i, None, -1

    done = 0
    if todo:
        with ThreadPoolExecutor(workers) as ex:
            for i, d, code in ex.map(one, todo):
                done += 1
                key = f"{api.game}:{i}"
                if d is not None:
                    try:
                        cache[key] = gear_from_item(d)
                    except Exception:
                        cache[key] = {"missing": True}
                elif code == 404:
                    cache[key] = {"missing": True}
                if progress and (done % 20 == 0 or done == len(todo)):
                    progress(done, len(todo))
                if done % 250 == 0:
                    save_json(ITEM_STATS_PATH, cache)
        save_json(ITEM_STATS_PATH, cache)
    return cache


def gear_index(api, progress=None):
    """Every piece of gear for sale right now, identified (slot, type, level, stats)."""
    sources = get_sources(api)
    ids = set(getattr(api, "gear_ids", None) or [])
    if not ids:                                   # no separate gear list: use everything that isn't known non-gear
        for _l, book in sources:
            ids.update(book)
        ids = {i for i in ids if cached_info(api.game, i).get("cls") not in NON_GEAR}
    cache = fetch_items(api, sorted(ids), progress)
    items, missing, other = [], 0, 0
    for i in ids:
        g = cache.get(f"{api.game}:{i}")
        if not g:
            continue
        if g.get("missing"):
            missing += 1
        elif g.get("cls_id") in (ARMOR, WEAPON) and g.get("inv"):
            items.append({**g, "id": i, "name": g.get("name") or f"Item {i}"})
        else:
            other += 1
    return {"items": items, "listed": len(ids), "missing": missing, "other": other,
            "sources": sources, "ts": api.snapshot_time}


ARMOR_NAMES = {CLOTH: "cloth", LEATHER: "leather", MAIL: "mail", PLATE: "plate"}
WEAPON_NAMES = {AXE1: "one-handed axes", AXE2: "two-handed axes", BOW: "bows", GUN: "guns",
                MACE1: "one-handed maces", MACE2: "two-handed maces", POLEARM: "polearms",
                SWORD1: "one-handed swords", SWORD2: "two-handed swords", STAFF: "staves", FIST: "fist weapons",
                DAGGER: "daggers", THROWN: "thrown weapons", XBOW: "crossbows", WAND: "wands"}
DUAL_WIELD_LEVEL = {"Rogue": 10, "Warrior": 20, "Hunter": 20}      # Classic: when dual wield is learned
WEAPON_INVS = ("WEAPON", "WEAPONMAINHAND", "WEAPONOFFHAND", "TWOHWEAPON", "RANGED", "RANGEDRIGHT", "THROWN")


def check_use(char, slot, m, two_hander=False):
    """(usable, reason) for one item in one slot."""
    if m.get("req") and m["req"] > char["level"]:
        return False, f"needs level {m['req']}"
    rules = CLASS_GEAR.get(char["cls"])
    inv, sub = m.get("inv"), m.get("sub_id")
    if slot == "OFF_HAND" and two_hander:
        return False, "you wield a two-hander"
    if not rules:
        return True, ""
    if inv == "SHIELD" and not rules["shield"]:
        return False, f"{char['cls']}s can't use shields"
    if inv == "HOLDABLE" and char["cls"] not in ("Priest", "Mage", "Warlock", "Druid", "Shaman", "Paladin"):
        return False, "caster off-hand"
    if slot in BODY_ARMOR_SLOTS and sub in ARMOR_NAMES:
        low, high = rules["armor"]
        best = high if char["level"] >= 40 else low
        allowed = {best} | ({best - 1} if best - 1 >= LEATHER else set())
        if sub not in allowed:
            if sub > best:
                return False, f"{ARMOR_NAMES[sub]} - " + ("unlocks at 40" if sub == high else "not your armor")
            return False, f"{ARMOR_NAMES[sub]} - you wear {ARMOR_NAMES[best]}"
    if inv in WEAPON_INVS:
        if sub is not None and sub not in rules["weapons"]:
            return False, f"can't use {WEAPON_NAMES.get(sub, 'this weapon type')}"
        if slot == "OFF_HAND" and inv in ("WEAPON", "WEAPONOFFHAND"):
            if not rules["dual"]:
                return False, "can't dual wield"
            need = DUAL_WIELD_LEVEL.get(char["cls"], 1)
            if char["level"] < need:
                return False, f"dual wield at level {need}"
        if slot == "MAIN_HAND" and inv == "WEAPONOFFHAND":
            return False, "off-hand only"
    return True, ""


def slot_view(char, slot, index, weights, mode=None):
    """Everything for sale that fits a slot, scored against what's equipped."""
    mode = mode or COMPARE_MODES[0]
    equipped = {g["slot"]: g for g in char["gear"]}
    two_hander = (equipped.get("MAIN_HAND") or {}).get("inv") == "TWOHWEAPON"
    cur = equipped.get(slot)
    cur_e = efficiency(cur, weights, slot, mode)
    wanted = {(c, inv) for c, invs in SLOT_SEARCH[slot] for inv in invs}
    rows = []
    for m in index["items"]:
        if (m.get("cls_id"), m.get("inv")) not in wanted or (cur and m["id"] == cur.get("id")):
            continue
        summ = item_summary(index["sources"], m["id"])
        if not summ:
            continue
        ok, why = check_use(char, slot, m, two_hander)
        e = efficiency(m, weights, slot, mode)
        gain = e["eff"] - cur_e["eff"]
        rows.append({"slot": slot, "slot_name": SLOT_NAMES[slot], "id": m["id"], "name": m["name"],
                     "q": m.get("q"), "ilvl": m.get("ilvl"), "req": m.get("req"), "gear": m,
                     "score": e["eff"], "eff": e["eff"], "power": e["power"], "fit": e["fit"], "est": e["est"],
                     "gain": gain, "up_pct": (gain / cur_e["eff"] * 100) if cur_e["eff"] > 0.5 else None,
                     "price": summ["lowest"], "listed": summ["quantity"], "usable": ok, "why": why,
                     "better": ok and gain > 0.01, "per_gold": gain / max(summ["lowest"] / 10000, 0.01)})
    better = [r for r in rows if r["better"]]
    if better:
        max(better, key=lambda r: r["gain"])["biggest"] = True
        max(better, key=lambda r: r["per_gold"])["best_value"] = True
    return rows, cur_e


def best_upgrades(char, index, weights, mode=None, per_slot=3):
    """Top upgrades for every slot (rings and trinkets are only suggested once)."""
    rows, current = [], {}
    for slot in SLOT_SEARCH:
        view, cur_e = slot_view(char, slot, index, weights, mode)
        current[slot] = cur_e
        rows.extend(sorted([r for r in view if r["better"]], key=lambda r: -r["gain"])[:per_slot])
    best = {}
    for r in rows:
        if r["slot"][:-2] in ("FINGER", "TRINKET"):
            k = (r["slot"][:-2], r["id"])
            if k not in best or r["gain"] > best[k]["gain"]:
                best[k] = r
    rows = [r for r in rows if r["slot"][:-2] not in ("FINGER", "TRINKET") or best[(r["slot"][:-2], r["id"])] is r]
    return rows, current


COMPARE_MODES = ["Efficiency (power x fit)", "Stats only", "Item level only"]

# Classic item budget: item level + quality give a "slot value"; the slot scales it.
SLOT_MOD = {"HEAD": 1.0, "CHEST": 1.0, "ROBE": 1.0, "LEGS": 1.0, "TWOHWEAPON": 1.0,
            "SHOULDER": 0.75, "HAND": 0.75, "WAIST": 0.75, "FEET": 0.75,
            "WRIST": 0.5625, "NECK": 0.5625, "CLOAK": 0.5625, "FINGER": 0.5625, "SHIELD": 0.5625,
            "HOLDABLE": 0.5625, "WEAPONOFFHAND": 0.5625, "TRINKET": 0.5625,
            "WEAPON": 0.4219, "WEAPONMAINHAND": 0.4219,
            "RANGED": 0.3164, "RANGEDRIGHT": 0.3164, "THROWN": 0.3164}
SLOT_DEFAULT_INV = {"HEAD": "HEAD", "NECK": "NECK", "SHOULDER": "SHOULDER", "CHEST": "CHEST", "WAIST": "WAIST",
                    "LEGS": "LEGS", "FEET": "FEET", "WRIST": "WRIST", "HANDS": "HAND", "FINGER_1": "FINGER",
                    "FINGER_2": "FINGER", "TRINKET_1": "TRINKET", "TRINKET_2": "TRINKET", "BACK": "CLOAK",
                    "MAIN_HAND": "WEAPON", "OFF_HAND": "SHIELD", "RANGED": "RANGED"}
PRIMARY = ("STRENGTH", "AGILITY", "STAMINA", "INTELLECT", "SPIRIT")
TYPICAL_FIT = 0.5          # assumed share of useful stats when Blizzard doesn't say


def item_power(ilvl, quality, inv, slot=None):
    """Estimated stat points an item carries, from item level, quality and slot (Classic budget formula)."""
    if not ilvl:
        return 0.0
    q = quality or "UNCOMMON"
    if q in ("EPIC", "LEGENDARY", "ARTIFACT"):
        value = (ilvl - 26) / 1.2
    elif q == "RARE":
        value = (ilvl - 0.75) / 1.8
    elif q == "UNCOMMON":
        value = (ilvl - 8) / 2.0
    else:                                  # white/grey items carry few or no stats
        value = (ilvl - 8) / 2.0 * 0.3
    mod = SLOT_MOD.get(inv) or SLOT_MOD.get(SLOT_DEFAULT_INV.get(slot, ""), 0.5625)
    return max(0.0, value * mod)


def efficiency(g, weights, slot, mode=COMPARE_MODES[0]):
    """Efficiency = Power x Fit (in stat points your class values), plus weapon DPS and armor.
    Returns {'eff', 'power', 'fit', 'est'}; est = True when stats were estimated."""
    if not g:
        return {"eff": 0.0, "power": 0.0, "fit": None, "est": False}
    stats = {k: v for k, v in (g.get("stats") or {}).items() if k in PRIMARY and v}
    power = item_power(g.get("ilvl"), g.get("q"), g.get("inv"), slot)
    wmax = max([weights.get(k, 0) for k in PRIMARY] + [0.01])
    extra = weights.get("ARMOR", 0) * (g.get("armor") or 0)
    extra += weights.get("RDPS" if slot == "RANGED" else "DPS", 0) * (g.get("dps") or 0)
    ilvl = g.get("ilvl") or 0
    if stats:
        total = sum(stats.values())
        useful = sum(weights.get(k, 0) * v for k, v in stats.items())
        fit, est = useful / (total * wmax), False
        stat_part = useful
    else:
        fit, est = TYPICAL_FIT, True
        stat_part = power * TYPICAL_FIT * wmax
    if mode == "Item level only":
        eff = ilvl + stat_part * 0.001
    elif mode == "Stats only":
        eff = (0 if est else stat_part) + extra + ilvl * 0.01
    else:
        eff = stat_part + extra + ilvl * 0.01
    return {"eff": eff, "power": power, "fit": fit, "est": est}


def gear_score(g, weights, slot, mode=COMPARE_MODES[0]):
    return efficiency(g, weights, slot, mode)["eff"]


def can_use(char, slot, cand, gear):
    rules = CLASS_GEAR.get(char["cls"])
    inv, sub = cand["inv"], cand["sub_id"]
    if not rules:
        return True
    if inv in ("SHIELD",):
        return rules["shield"] and slot == "OFF_HAND"
    if inv == "HOLDABLE":
        return slot == "OFF_HAND" and char["cls"] in ("Priest", "Mage", "Warlock", "Druid", "Shaman", "Paladin")
    if slot in BODY_ARMOR_SLOTS and sub in (CLOTH, LEATHER, MAIL, PLATE):
        low, high = rules["armor"]
        best = high if char["level"] >= 40 else low
        # your best armor type, plus one step down - but never cloth for leather/mail/plate wearers
        allowed = {best} | ({best - 1} if best - 1 >= LEATHER else set())
        return sub in allowed
    if inv in ("WEAPON", "WEAPONMAINHAND", "WEAPONOFFHAND", "TWOHWEAPON", "RANGED", "RANGEDRIGHT", "THROWN"):
        if sub is not None and sub not in rules["weapons"]:
            return False
        if slot == "OFF_HAND" and inv in ("WEAPON", "WEAPONOFFHAND"):
            return rules["dual"]
        if slot == "OFF_HAND":
            return False
        if slot == "MAIN_HAND" and inv == "WEAPONOFFHAND":
            return False
    return True


def find_upgrades(api, char, focus=None, max_price=None, progress=None, per_slot=5, check=40,
                  mode=COMPARE_MODES[0], only=None):
    """Best AH upgrades per slot for a character. Also returns a per-slot breakdown of how many
    items were known / for sale / usable / better, so an empty result can be explained."""
    weights = (STAT_PRESETS.get(char["cls"], {}).get(focus)
               or next(iter(STAT_PRESETS.get(char["cls"], {}).values()), DEFAULT_WEIGHTS))
    sources = get_sources(api)
    equipped = {g["slot"]: g for g in char["gear"]}
    two_hander = (equipped.get("MAIN_HAND") or {}).get("inv") == "TWOHWEAPON"
    slots = [s for s in SLOT_SEARCH if not (s == "OFF_HAND" and two_hander)]
    if only:
        slots = [s for s in slots if s in only]
    rows, current, diag = [], {}, []
    pool, pool_left, used_pool, unknown = None, 0, False, 0
    for n, slot in enumerate(slots):
        if progress:
            progress(n, len(slots), SLOT_NAMES[slot])
        cur = equipped.get(slot)
        cur_e = efficiency(cur, weights, slot, mode) if cur else efficiency(None, weights, slot, mode)
        cur_score = cur_e["eff"]
        current[slot] = {"item": cur, "score": cur_score, **cur_e}
        members = []
        for item_class, inv_types in SLOT_SEARCH[slot]:
            for inv in inv_types:
                members.extend(slot_members(api, item_class, inv))
        if not members:                                    # search found nothing: read the AH itself
            if pool is None:
                pool, pool_left, unknown = ah_gear_pool(api, sources, progress)
                used_pool = True
            wanted = {(c, inv) for c, invs in SLOT_SEARCH[slot] for inv in invs}
            members = [m for m in pool if (m["cls_id"], m["inv"]) in wanted]
        d = {"slot": SLOT_NAMES[slot], "slot_key": slot, "known": len(members), "for_sale": 0, "usable": 0,
             "better": 0, "no_data": 0}
        cands = []
        seen = set()
        for m in members:
            if m["id"] in seen:
                continue
            seen.add(m["id"])
            summ = item_summary(sources, m["id"])
            if not summ:
                continue
            d["for_sale"] += 1
            if m["req"] is not None and m["req"] > char["level"]:
                continue
            if m["q"] == "POOR" or (cur and m["id"] == cur.get("id")):
                continue
            if not can_use(char, slot, m, cur):
                continue
            if max_price and summ["lowest"] > max_price:
                continue
            d["usable"] += 1
            cands.append((m, summ))
        # only fetch full stats for the most promising (highest item level) candidates
        cands.sort(key=lambda c: -(c[0]["ilvl"] or 0))
        found = []
        for m, summ in cands[:check]:
            g = m.get("preview") or item_gear(api, m["id"]) or {"stats": {}, "armor": 0, "dps": 0}
            g = {**g, "ilvl": g.get("ilvl") or m["ilvl"], "req": g.get("req") if g.get("req") is not None else m["req"],
                 "q": g.get("q") or m["q"], "inv": g.get("inv") or m["inv"]}
            if not g["ilvl"]:
                d["no_data"] += 1          # Blizzard has nothing on this item - can't score it
                continue
            e = efficiency(g, weights, slot, mode)
            gain = e["eff"] - cur_score
            if gain <= 0.01:
                continue
            d["better"] += 1
            found.append({"slot": slot, "slot_name": SLOT_NAMES[slot], "id": m["id"], "name": m["name"],
                          "q": g["q"], "ilvl": g["ilvl"], "req": g["req"], "gear": g,
                          "score": e["eff"], "eff": e["eff"], "power": e["power"], "fit": e["fit"], "est": e["est"],
                          "gain": gain, "up_pct": (gain / cur_score * 100) if cur_score > 0.5 else None,
                          "price": summ["lowest"], "listed": summ["quantity"],
                          "per_gold": gain / max(summ["lowest"] / 10000, 0.01)})
        found.sort(key=lambda r: -r["gain"])
        rows.extend(found[:per_slot])
        diag.append(d)
    if progress:
        progress(len(slots) - 1, len(slots), "done")
    # a ring or trinket shouldn't be suggested for both slots - keep it where it helps most
    best = {}
    for r in rows:
        if r["slot"][:-2] in ("FINGER", "TRINKET"):
            k = (r["slot"][:-2], r["id"])
            if k not in best or r["gain"] > best[k]["gain"]:
                best[k] = r
    rows = [r for r in rows if r["slot"][:-2] not in ("FINGER", "TRINKET") or best[(r["slot"][:-2], r["id"])] is r]
    return {"rows": rows, "current": current, "weights": weights, "ts": api.snapshot_time,
            "diag": diag, "used_pool": used_pool, "pool_left": pool_left, "unknown": unknown, "mode": mode}


def load_characters():
    return load_json(CHARACTERS_PATH, [])


def remember_character(entry):
    chars = [c for c in load_characters()
             if (c.get("name", "").lower(), c.get("surname", "").lower(), c.get("realm", "").lower(), c.get("game"))
             != (entry["name"].lower(), entry.get("surname", "").lower(), entry.get("realm", "").lower(), entry["game"])]
    chars.insert(0, entry)
    save_json(CHARACTERS_PATH, chars[:12])


# ---------- CSV export ----------

def export_history_csv(path):
    names = known_names()
    with closing(_db()) as con:
        rows = con.execute("SELECT ts, game, item_id, lowest, market, qty FROM prices "
                           "ORDER BY item_id, ts").fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date_time", "game", "item_id", "item_name", "lowest_gold", "market_gold", "quantity"])
        for ts, game, iid, low, mkt, qty in rows:
            w.writerow([datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"), game, iid,
                        names.get(iid, ""), round(low / 10000, 4), round(mkt / 10000, 4), qty])
    return len(rows)


def export_sessions_csv(path):
    sessions = load_sessions()
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date_time", "spot", "minutes", "item", "qty", "each_gold",
                    "item_total_gold", "session_total_after_cut_gold", "session_gold_per_hour"])
        for s in sessions:
            for it in s["items"]:
                w.writerow([s["date"].replace("T", " "), s["spot"], s.get("minutes") or "",
                            it["name"], it["qty"], round(it["each"] / 10000, 4),
                            round(it["each"] * it["qty"] / 10000, 4),
                            round(s["after_cut"] / 10000, 4),
                            round(s["gph"] / 10000, 4) if s.get("gph") else ""])
                n += 1
    return n


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--watchlist":
        game = "retail" if "retail" in sys.argv else "forever"
        api = connect(game)
        print(format_watchlist(check_watchlist(api, load_watchlist())))
        return

    ap = argparse.ArgumentParser(description="Current WoW auction house price lookup")
    ap.add_argument("item", help='Item name or item ID, e.g. "Copper Ore" or 2770')
    ap.add_argument("--game", default="forever", choices=["forever", "retail"])
    ap.add_argument("--realm", help="Retail only: realm slug for non-commodity items")
    ap.add_argument("--region", default="us", choices=["us", "eu", "kr", "tw"])
    args = ap.parse_args()

    cid, secret = load_credentials()
    api = Blizz(get_token(cid, secret), args.region, args.game)

    items = find_items(api, args.item)
    if not items:
        sys.exit(f'No item found named "{args.item}". Check the spelling, or try the item ID.')

    try:
        sources = forever_sources(api) if args.game == "forever" else retail_sources(api, args.realm)
    except ApiError as e:
        sys.exit(f"Couldn't load auction data.\n{e}")

    game_label = "WoW: Forever" if args.game == "forever" else "Retail"
    found = False
    for item_id, item_name in items:
        for label, book in sources:
            if item_id in book:
                found = True
                s = summarize(book[item_id])
                print(f"\n{item_name}  (item {item_id}) - {game_label}, {label}")
                print(f"  Lowest price:          {fmt_gold(s['lowest'])}")
                print(f"  Avg of cheapest 10%:   {fmt_gold(s['cheap10'])}")
                print(f"  Median listing:        {fmt_gold(s['median'])}")
                print(f"  Available:             {s['quantity']:,} across {s['listings']:,} listings")

    if not found:
        names = ", ".join(f"{n} ({i})" for i, n in items[:5])
        msg = f"Found {names}, but none are listed on the {game_label} auction house right now."
        if args.game == "retail" and not args.realm:
            msg += "\nFor gear or pets, add --realm your-realm-slug."
        print(msg)


if __name__ == "__main__":
    main()
