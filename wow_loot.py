"""
wow_loot.py - Loot finder for Awesome House (WoW: Forever).

Scores the gear that drops inside dungeons and raids against what a character wears, with
the same Efficiency scoring the Character tab uses for auction-house gear. Which monster
drops what comes from the Monster Compendium index (QuestieDB); item stats come from
Blizzard and are remembered in item_stats.json. Blizzard has no data for many Classic-era
items, so those can't be scored.
"""

import os

import wow_price as wp
import wow_dungeons as wd

_stats = [None, {}]


def stats_cache():
    """item_stats.json, re-read only when the file changes."""
    try:
        m = os.path.getmtime(wp.ITEM_STATS_PATH)
    except OSError:
        return {}
    if _stats[0] != m:
        _stats[:] = [m, wp.load_json(wp.ITEM_STATS_PATH, {})]
    return _stats[1]


def gear_of(item_id):
    """Blizzard's stats for an item: a dict, None (Blizzard has none) or False (not asked yet)."""
    g = stats_cache().get(f"forever:{item_id}")
    if g is None:
        return False
    return None if g.get("missing") or not g.get("inv") else g


def dungeon_gear(db):
    """{item id: [monster ids]} for weapons and armor that only drop inside dungeons and raids."""
    memo = getattr(db, "_dungeon_gear", None)
    if memo is not None:
        return memo
    inside = {n for _g, lst in wd.dungeon_list(db) for d in lst for n in db.by_zone.get(d["id"], [])}
    src = {}
    for nid, lst in db.drops.items():
        for iid in lst:
            if db.items.get(iid, {}).get("c") in (wp.WEAPON, wp.ARMOR):
                src.setdefault(iid, []).append(nid)
    db._dungeon_gear = {i: n for i, n in src.items() if all(x in inside for x in n)}
    return db._dungeon_gear


def not_asked(ids):
    """Item ids Blizzard hasn't been asked about yet."""
    cache = stats_cache()
    return [i for i in ids if f"forever:{i}" not in cache]


def rate(char, g, weights, mode, slot=None):
    """Score one item for a character: the best slot it fits (or the slot given).
    Returns a row like wow_price.slot_view's, or None when it fits no slot."""
    equipped = {x["slot"]: x for x in char["gear"]}
    two_hander = (equipped.get("MAIN_HAND") or {}).get("inv") == "TWOHWEAPON"
    best = None
    for s, wanted in wp.SLOT_SEARCH.items():
        if slot and s != slot:
            continue
        if not any(g.get("cls_id") == c and g.get("inv") in invs for c, invs in wanted):
            continue
        cur = equipped.get(s)
        cur_e = wp.efficiency(cur, weights, s, mode)
        ok, why = wp.check_use(char, s, g, two_hander)
        e = wp.efficiency(g, weights, s, mode)
        gain = e["eff"] - cur_e["eff"]
        row = {"slot": s, "slot_name": wp.SLOT_NAMES[s], "q": g.get("q"), "ilvl": g.get("ilvl"),
               "req": g.get("req"), "gear": g, "score": e["eff"], "eff": e["eff"], "power": e["power"],
               "fit": e["fit"], "est": e["est"], "gain": gain, "usable": ok, "why": why,
               "up_pct": (gain / cur_e["eff"] * 100) if cur_e["eff"] > 0.5 else None,
               "better": ok and gain > 0.01, "same": bool(cur) and cur.get("name") == g.get("name")}
        if best is None or (row["usable"], row["gain"]) > (best["usable"], best["gain"]):
            best = row
    return best


def drop_rows(char, db, weights, mode, slot=None, sources=None):
    """(rows, counts) - every scoreable dungeon drop for a slot (or for its best slot)."""
    rows, counts = [], {"total": 0, "missing": 0, "unknown": 0}
    for iid, npcs in dungeon_gear(db).items():
        counts["total"] += 1
        g = gear_of(iid)
        if not g:
            counts["missing" if g is None else "unknown"] += 1
            continue
        r = rate(char, g, weights, mode, slot)
        if not r or r["same"]:
            continue
        summ = wp.item_summary(sources, iid) if sources is not None else None
        places = {}
        for n in npcs:
            z = db.main_zone(n)
            places.setdefault(db.zone_name(z) if z else "", []).append(db.npcs[n]["n"])
        r.update({"id": iid, "name": g.get("name") or db.items[iid]["n"], "from": places, "npcs": npcs,
                  "price": summ["lowest"] if summ else 0, "listed": summ["quantity"] if summ else 0,
                  "per_gold": 0})
        rows.append(r)
    return rows, counts


def best_per_slot(rows, per_slot=4):
    """The biggest few upgrades for each slot; a ring or trinket is only suggested once."""
    by = {}
    for r in sorted((r for r in rows if r["better"]), key=lambda r: -r["gain"]):
        key = r["slot"][:-2] if r["slot"][:-2] in ("FINGER", "TRINKET") else r["slot"]
        if len(by.setdefault(key, [])) < per_slot:
            by[key].append(r)
    return [r for lst in by.values() for r in lst]


def source_text(r, limit=2):
    """"Rhahk'Zor - The Deadmines" for a drop row."""
    parts = []
    for zone, names in r["from"].items():
        parts.append(", ".join(names[:limit]) + (f" +{len(names) - limit}" if len(names) > limit else "")
                     + (f" · {zone}" if zone else ""))
    return "; ".join(parts[:2]) + (" ..." if len(parts) > 2 else "")
