"""
wow_dungeons.py - Dungeons tab data for Awesome House (WoW: Forever).

The dungeon list, monsters, drops, quests and entrance coordinates come from the Monster
Compendium index (QuestieDB, see wow_monsters.py). The travel notes (nearest flight point
and route for each faction, group size) are this app's own dungeon_travel.json: a seed
shipped with the app, which a copy next to the app overrides dungeon by dungeon.
"""

import os
import shutil

import wow_price as wp

SEED_NAME = "dungeon_travel.json"
BUNDLED_PATH = os.path.join(wp.BUNDLE_DIR, SEED_NAME)
USER_PATH = os.path.join(wp.HERE, SEED_NAME)
NOT_DUNGEONS = {2257}                        # Deeprun Tram
GROUPS = ["Dungeons", "Raids", "Forever additions"]
MAX_LEVEL = 63                               # above this is a placeholder or skull level

_travel, _stamp = None, None


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def load_travel():
    """{area id: travel entry}; re-read whenever either file changes on disk."""
    global _travel, _stamp
    stamp = (_mtime(BUNDLED_PATH), _mtime(USER_PATH))
    if _travel is not None and stamp == _stamp:
        return _travel
    out = {}
    for path in dict.fromkeys((BUNDLED_PATH, USER_PATH)):       # the user's copy wins
        data = wp.load_json(path, {})
        entries = data.get("dungeons") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            continue
        for k, v in entries.items():
            if str(k).isdigit() and isinstance(v, dict):
                out[int(k)] = v
    _travel, _stamp = out, stamp
    return out


def editable_path():
    """The travel file the user can edit (copied next to the app the first time)."""
    if not os.path.exists(USER_PATH) and os.path.exists(BUNDLED_PATH):
        shutil.copyfile(BUNDLED_PATH, USER_PATH)
    return USER_PATH


def route(entry, side):
    """(flight point, [steps]) for "alliance" or "horde"; empty when not recorded."""
    r = (entry or {}).get(side) or {}
    steps = [s for s in r.get("steps") or [] if isinstance(s, str) and s.strip()]
    return (r.get("flight") or "").strip(), steps


def level_range(db, zid):
    """(low, high) of the monsters inside, ignoring placeholders and skull levels."""
    lows, highs = [], []
    for nid in db.by_zone.get(zid, []):
        a, b = db.npcs[nid]["l"]
        if 0 < a <= MAX_LEVEL:
            lows.append(a)
            highs.append(b if a <= b <= MAX_LEVEL else a)
    if not lows:
        return None
    lows.sort()
    return lows[len(lows) // 10], max(highs)       # skip the odd low-level stray


def entrances(db, zid):
    """[(zone name, x, y, label)] incl. the extra doors QuestieDB lists under the same name."""
    d = db.dungeons.get(zid)
    if not d:
        return []
    out, seen = [], set()
    same = [zid] + sorted(k for k, v in db.dungeons.items() if k != zid and v["n"] == d["n"])
    for k in same:
        for zone, x, y, label in db.dungeons[k]["e"]:
            key = (zone, round(x), round(y))
            if key not in seen:
                seen.add(key)
                out.append((zone, x, y, label))
    return out


def dungeon_list(db, travel=None):
    """[(group, [dungeon dict, ...])] for every dungeon and raid that has monsters in the index."""
    travel = load_travel() if travel is None else travel
    groups = {g: [] for g in GROUPS}
    for zid, z in db.zones.items():
        if zid in NOT_DUNGEONS or db.group_of(zid) != "Dungeons and raids":
            continue
        t = travel.get(zid) or {}
        kind = (t.get("kind") or "").lower()
        group = "Raids" if kind == "raid" else "Dungeons" if kind == "dungeon" else "Forever additions"
        groups[group].append({"id": zid, "name": z["n"], "kind": kind, "players": str(t.get("players") or ""),
                              "count": len(db.by_zone.get(zid, [])), "levels": level_range(db, zid)})
    for lst in groups.values():
        lst.sort(key=lambda d: ((d["levels"] or (99, 99)), d["name"].lower()))
    return [(g, groups[g]) for g in GROUPS if groups[g]]


def dungeon_quests(db, zid):
    """[(quest id, quest, [why, ...])]: quests filed under the dungeon, quests to kill its
    monsters, and quests for the quest items they drop (not for ordinary loot like herbs)."""
    areas = {zid, *db.dungeons.get(zid, {}).get("alt", [])}
    found = {}

    def add(qid, text):
        if qid in db.quests:
            w = found.setdefault(qid, [])
            if text and text not in w and len(w) < 4:
                w.append(text)
    for qid, q in db.quests.items():
        if q.get("z") in areas:
            add(qid, "")
    for nid in db.by_zone.get(zid, []):
        name = db.npcs[nid]["n"]
        for qid in db.kill_q.get(nid, []):
            add(qid, f"Kill {name}")
        for iid in db.drops.get(nid, []):
            it = db.items.get(iid, {})
            if it.get("c") != 12:
                continue
            for qid in db.collect_q.get(iid, []):
                add(qid, f"{it.get('n')} from {name}")
            if it.get("sq"):
                add(it["sq"], f"{it.get('n')} from {name} starts it")
    out = [(qid, db.quests[qid], why) for qid, why in found.items()]
    out.sort(key=lambda t: ((t[1].get("lv") or 0) if (t[1].get("lv") or 0) > 0 else 99, t[1]["n"]))
    return out


def dungeon_drops(db, zid):
    """Every item dropped inside, once each: drop dicts like Compendium.drops_of, plus "from"."""
    out = {}
    for nid in db.by_zone.get(zid, []):
        for d in db.drops_of(nid):
            cur = out.get(d["id"])
            if cur is None:
                d["from"] = [db.npcs[nid]["n"]]
                out[d["id"]] = d
            else:
                cur["from"].append(db.npcs[nid]["n"])
                cur["rate"] = max(cur["rate"] or 0, d["rate"] or 0) or None
    return list(out.values())


def unverified(db):
    """[(name, "no route" | "not checked")] for the report of travel notes still to confirm."""
    travel = load_travel()
    out = []
    for _g, lst in dungeon_list(db, travel):
        for d in lst:
            t = travel.get(d["id"]) or {}
            has = any(route(t, s)[1] for s in ("alliance", "horde"))
            if not has:
                out.append((d["name"], "no route"))
            elif not t.get("verified"):
                out.append((d["name"], "not checked"))
    return out
