"""
wow_monsters.py - Monster Compendium data for Awesome House (WoW: Forever).

Where the data comes from
    The monster, drop and quest data is the community QuestieDB database (the data
    behind the Questie addon), Forever edition: https://github.com/Questie/QuestieDB
    It is NOT shipped with this app. The first time the Monster Compendium opens, the
    app downloads the public QuestieDB-Forever release (about 14 MB) from GitHub to
    this computer, reads it, and saves a small index in .wow_price_cache/. The
    "Update data" button checks GitHub for a newer release.

    QuestieDB's Forever data started from Classic Era and is still filling in, so some
    new Forever monsters, drops and quests may be missing or out of date. Drop chances
    are only known for quest items (QuestieDB's Wowhead-derived drop table).

Tracking list: monster_tracking.json next to the app.
"""

import base64
import io
import json
import os
import re
import struct
import time
import urllib.request
import zipfile

import wow_price as wp

INDEX_SCHEMA = 9
REPO = "Questie/QuestieDB"
FALLBACK_VERSION = "1.0.13"
DATA_DIR = os.path.join(wp.CACHE_DIR, "questiedb")
ZIP_PATH = os.path.join(DATA_DIR, "QuestieDB-Forever.zip")
INDEX_PATH = os.path.join(DATA_DIR, "monster_index.json")
TRACK_PATH = os.path.join(wp.HERE, "monster_tracking.json")
CHECK_EVERY = 3 * 24 * 3600            # look for a newer QuestieDB release every few days
UA = {"User-Agent": "Awesome-House"}

WOWHEAD_NPC = "https://www.wowhead.com/forever/npc={}"
WOWHEAD_ITEM = "https://www.wowhead.com/forever/item={}"
WOWHEAD_QUEST = "https://www.wowhead.com/forever/quest={}"
WIKI_PAGE = "https://warcraft.wiki.gg/wiki/{}"

RANKS = {0: "", 1: "Elite", 2: "Rare Elite", 3: "Boss", 4: "Rare"}
ITEM_CLASSES = {0: "Consumable", 1: "Container", 2: "Weapon", 3: "Gem", 4: "Armor", 5: "Reagent",
                6: "Projectile", 7: "Trade Goods", 9: "Recipe", 11: "Quiver", 12: "Quest",
                13: "Key", 15: "Miscellaneous"}
# Forever's Skyborne races use bits 32 and 33. A Horde Skyborne character has completed quests
# limited to bit 32 alone, so those bits don't say which faction a quest is for and are ignored.
ALLIANCE_RACES = 1 | 4 | 8 | 64                  # human, dwarf, night elf, gnome
HORDE_RACES = 2 | 16 | 32 | 128                  # orc, undead, tauren, troll
NOT_MONSTER = re.compile(r"trigger|bunny|\(|\[|invisible|\bdnd\b|\bdnr\b|spawn point|waypoint|"
                         r"\bunused\b|\btest\b|\bcredit\b|\bdummy\b|\bbeacon\b|\breuse\b|programmer", re.I)
FOREVER_ZONES = {616, 16651, 16606}              # Mount Hyjal, Shen'dralas, Darkspear Islands
BATTLEGROUNDS = {2597, 3277, 3358, 16603, 16653}  # Alterac Valley, WSG, AB, winter WSG, Gilneas

# Hand-made zone names where the symbol loses an apostrophe or reads oddly.
ZONE_FIXES = {
    "UN_GORO_CRATER": "Un'Goro Crater", "ZUL_FARRAK": "Zul'Farrak", "ZUL_GURUB": "Zul'Gurub",
    "ONYXIAS_LAIR": "Onyxia's Lair", "SHEN_DRALAS": "Shen'dralas", "AHN_QIRAJ": "Ahn'Qiraj",
    "RUINS_OF_AHN_QIRAJ": "Ruins of Ahn'Qiraj", "TEMPLE_OF_AHN_QIRAJ": "Temple of Ahn'Qiraj",
    "THE_TEMPLE_OF_ATAL_HAKKAR": "The Temple of Atal'Hakkar", "KROL_DOK_STRONGHOLD": "Krol'dok Stronghold",
    "ROG_MAR": "Rog'mar", "DAE_GUN": "Dae'gun", "SHEN_DAR_HIGHLANDS": "Shen'dar Highlands",
    "SHEN_DAR_VILLAGE": "Shen'dar Village", "BOLDER_OK": "Bolder'ok", "CAMP_GEV_REK": "Camp Gev'rek",
    "RUINS_OF_BAN_AETHAL": "Ruins of Ban'aethal", "MOURNINGS_REST": "Mourning's Rest",
    "MALORNES_RETREAT": "Malorne's Retreat", "TERRALS_WATCH": "Terral's Watch",
    "WHEELERS_GRANGE": "Wheeler's Grange", "ELBRIMS_FARM": "Elbrim's Farm",
    "TURNERS_LOGGING_CAMP": "Turner's Logging Camp", "ASHWOODS_FALL": "Ashwood's Fall",
    "TWILIGHTS_SHROUD": "Twilight's Shroud", "POACHERS_DEN": "Poacher's Den",
    "RUTSAKS_GUARD": "Rutsak's Guard", "TEMPESTS_REACH": "Tempest's Reach",
    "EVENSHADES_OVERLOOK": "Evenshade's Overlook", "THE_SHAPERS_TERRACE": "The Shaper's Terrace",
    "WHELGARS_EXCAVATION_SITE": "Whelgar's Excavation Site", "THE_HALL_OF_THANES": "Hall of Thanes",
    "STRANGLETHORN_VALE": "Stranglethorn Vale", "ALTERAC_VALLEY": "Alterac Valley",
    "THE_BARRENS": "The Barrens", "MOONGLADE": "Moonglade", "AHN_QIRAJ_THE_FALLEN_KINGDOM":
    "Ahn'Qiraj: The Fallen Kingdom", "MOUNT_HYJAL": "Mount Hyjal", "DRAGONMAW_RETREAT": "Dragonmaw Retreat",
}
SMALL = {"of", "the", "and", "in", "on"}


class DataError(Exception):
    pass


# ================================================================ tiny CBOR + TOC reader

def _cbor(b):
    pos = 0

    def arg(info):
        nonlocal pos
        if info < 24:
            return info
        n = {24: 1, 25: 2, 26: 4, 27: 8}[info]
        v = int.from_bytes(b[pos:pos + n], "big")
        pos += n
        return v

    def item():
        nonlocal pos
        ib = b[pos]
        pos += 1
        mt, info = ib >> 5, ib & 31
        if mt == 0:
            return arg(info)
        if mt == 1:
            return -1 - arg(info)
        if mt in (2, 3):
            n = arg(info)
            s = b[pos:pos + n]
            pos += n
            return s.decode("utf-8", "replace")      # QuestieDB stores text as byte strings
        if mt == 4:
            return [item() for _ in range(arg(info))]
        if mt == 5:
            d = {}
            for _ in range(arg(info)):
                k = item()
                d[k] = item()
            return d
        if mt == 6:
            arg(info)
            return item()
        if info == 20:
            return False
        if info == 21:
            return True
        if info in (22, 23):
            return None
        fmt = {25: (">e", 2), 26: (">f", 4), 27: (">d", 8)}.get(info)
        if not fmt:
            raise DataError(f"unexpected CBOR byte {ib}")
        v = struct.unpack(fmt[0], b[pos:pos + fmt[1]])[0]
        pos += fmt[1]
        return v

    return item()


def _arr(v):
    """CBOR arrays from Lua come back as lists (with None holes) or {index: value} maps."""
    if v is None:
        return []
    if isinstance(v, dict):
        return [v.get(i) for i in range(1, max((k for k in v if isinstance(k, int)), default=0) + 1)]
    return v


class _Toc:
    def __init__(self, text):
        self.meta = {}
        for line in text.splitlines():
            if line.startswith("## X-"):
                k, _, v = line[3:].partition(": ")
                self.meta[k] = v.strip()

    def stored(self, key):
        v = self.meta.get(key)
        if v is None:
            return None
        m = re.fullmatch(r"~(\d+)~", v)
        if m:
            v = "".join(self.meta[f"{key}-{i}"] for i in range(1, int(m.group(1)) + 1))
        return v

    def ids(self, kind):
        import zlib
        raw = base64.b64decode(self.stored(f"X-{kind}-IDS"))
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            data = zlib.decompress(raw, -15)
        return [i for i in _arr(_cbor(data)) if i is not None]

    def row(self, kind, i):
        s = self.stored(f"X-{kind}-{i}-S")
        r = _cbor(base64.b64decode(s)) if s else {}
        if isinstance(r, list):
            r = {n + 1: v for n, v in enumerate(r) if v is not None}
        return r

    def field(self, kind, i, f, row=None):
        if row is not None and not (int(row.get("p", 0)) >> (f - 1)) & 1:
            return None
        s = self.stored(f"X-{kind}-{i}-{f}")
        return _cbor(base64.b64decode(s)) if s else None


# ================================================================ download

def _get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read()


_asset_urls = {}          # version -> Forever zip URL found through GitHub's API


def latest_version():
    """Newest QuestieDB release tag (GitHub API first, then the /releases/latest redirect)."""
    try:
        _, body = _get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=30)
        rel = json.loads(body)
        version = (rel.get("tag_name") or "").lstrip("v")
        for a in rel.get("assets", []):
            if "forever" in a.get("name", "").lower() and a.get("name", "").endswith(".zip"):
                _asset_urls[version] = a.get("browser_download_url")
                break
        if version:
            return version
    except Exception:
        pass
    try:
        req = urllib.request.Request(f"https://github.com/{REPO}/releases/latest", headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            m = re.search(r"/tag/v?([\w.\-]+)$", r.geturl())
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def _zip_urls(version):
    base = f"https://github.com/{REPO}/releases/download/v{version}"
    urls = [f"{base}/QuestieDB-{version}-Forever.zip", f"{base}/QuestieDB-Forever.zip"]
    if _asset_urls.get(version):
        urls.insert(0, _asset_urls[version])
    return urls


def download(version=None, progress=print):
    version = version or latest_version() or FALLBACK_VERSION
    os.makedirs(DATA_DIR, exist_ok=True)
    last = None
    for url in _zip_urls(version):
        try:
            progress(f"Downloading QuestieDB {version} for Forever (about 14 MB)...")
            _, data = _get(url, timeout=180)
            zipfile.ZipFile(io.BytesIO(data)).testzip()
            tmp = ZIP_PATH + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, ZIP_PATH)
            return version
        except Exception as e:            # try the other file name, then give up
            last = e
    raise DataError(f"Couldn't download the QuestieDB data from GitHub ({last}). "
                    "Check your internet connection and try Update data again.")


# ================================================================ build the index

def _zone_names(zf):
    """{area id: (name, group)} from QuestieDB's zone symbols, plus dungeon names."""
    names, group = {}, "Other"
    text = zf.read(_member(zf, "src/corrections/enum/zones.lua")).decode("utf-8", "replace")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("--"):
            g = s.lstrip("- ").split(":")[0]
            if s.lstrip("- ").startswith("Forever"):
                g = "Forever"
            group = g
            continue
        m = re.match(r"([A-Z][A-Z0-9_]*)\s*=\s*(\d+)", s)
        if not m:
            continue
        sym, zid = m.group(1), int(m.group(2))
        if zid in names:
            continue
        base = re.sub(r"_(FOREVER|SOD|CAMELOT|\d{4,})$", "", sym)
        name = ZONE_FIXES.get(base) or ZONE_FIXES.get(sym)
        if not name:
            words = base.lower().split("_")
            name = " ".join(w if (i and w in SMALL) else w.capitalize() for i, w in enumerate(words))
        names[zid] = (name, group)
    try:
        dtext = zf.read(_member(zf, "support/Forever/Zones/dungeons.lua")).decode("utf-8", "replace")
        for m in re.finditer(r'\[(\d+)\]\s*=\s*\{"([^"]+)",(\{[\d,]*\}|nil)', dtext):
            zid = int(m.group(1))
            names[zid] = (m.group(2), "Dungeons and raids")
            for alt in re.findall(r"\d+", m.group(3)):
                names.setdefault(int(alt), (m.group(2), "Dungeons and raids"))
    except KeyError:
        pass
    return names


def _dungeon_entries(zf, zone_names):
    """{area id: {"n": name, "alt": [ids], "p": parent zone name, "e": [[zone name, x, y, label]]}}
    from QuestieDB's dungeon table: where each dungeon's entrance is on the world map."""
    out = {}
    try:
        text = zf.read(_member(zf, "support/Forever/Zones/dungeons.lua")).decode("utf-8", "replace")
    except KeyError:
        return out
    row = re.compile(r'^\s*\[(\d+)\]\s*=\s*\{"([^"]+)",(\{[\d,]*\}|nil),(\d+),\{(.*)\}\},?\s*(?:--\s*(.*))?$')

    def area(a):
        return zone_names.get(a, (f"Area {a}", ""))[0]
    for line in text.splitlines():
        m = row.match(line)
        if not m or "isHorde" in line:
            continue
        note = (m.group(6) or "").split(":")[0].strip()
        label = note if re.fullmatch(r"(North|South|East|West|The [A-Z][a-z]+)", note) else ""
        ents = [[area(int(a)), float(x), float(y), label]
                for a, x, y in re.findall(r"\{(\d+),\s*([\d.]+),\s*([\d.]+)\}", m.group(5))]
        out[int(m.group(1))] = {"n": m.group(2), "alt": [int(a) for a in re.findall(r"\d+", m.group(3))],
                                "p": area(int(m.group(4))), "e": ents}
    return out


def _parents(zf):
    out = {}
    try:
        text = zf.read(_member(zf, "support/Forever/Zones/subZoneToParentZone.lua")).decode("utf-8", "replace")
    except KeyError:
        return out
    for m in re.finditer(r"\[(\d+)\]\s*=\s*(\d+)", text):
        out[int(m.group(1))] = int(m.group(2))
    return out


def _drop_rates(zf):
    """{item id: {npc id: percent}} - only known for quest items."""
    out = {}
    try:
        text = zf.read(_member(zf, "support/Forever/DropTables/classicItemDrops.lua")).decode("utf-8", "replace")
    except KeyError:
        return out
    cur = None
    for line in text.splitlines():
        m = re.match(r"\s*\[(\d+)\]\s*=\s*\{", line)
        if m:
            cur = out.setdefault(int(m.group(1)), {})
            continue
        m = re.match(r"\s*\[(\d+)\]\s*=\s*([\d.]+)", line)
        if m and cur is not None:
            cur[int(m.group(1))] = float(m.group(2))
    return out


def _member(zf, suffix):
    for n in zf.namelist():
        if n.replace("\\", "/").endswith(suffix):
            return n
    raise KeyError(suffix)


def _spots(spawns, top_zone):
    """[[zone id, x, y, spawn points]] - the busiest spot per zone, most spawns first.
    Dungeon spawns have no map position (-1, -1) and are left out."""
    zones = {}
    if isinstance(spawns, list):
        spawns = {i + 1: v for i, v in enumerate(spawns) if v}
    for zid, pts in (spawns or {}).items():
        try:
            zid = top_zone(int(zid))
        except (TypeError, ValueError):
            continue
        for p in _arr(pts):
            p = _arr(p)
            if len(p) >= 2 and isinstance(p[0], (int, float)) and isinstance(p[1], (int, float)) \
                    and p[0] > 0 and p[1] > 0:
                zones.setdefault(zid, []).append((float(p[0]), float(p[1])))
    out = []
    for zid, pts in zones.items():
        sample = pts[:250]
        best = max(sample, key=lambda a: sum(1 for b in sample if abs(a[0] - b[0]) < 3 and abs(a[1] - b[1]) < 3))
        out.append([zid, round(best[0], 1), round(best[1], 1), len(pts)])
    out.sort(key=lambda t: -t[3])
    return out[:3]


def way(zone, x, y, label=""):
    """A TomTom waypoint command for the game's chat box."""
    return f"/way {zone} {x:g} {y:g} {label}".strip()


def _faction(mask):
    mask = int(mask or 0)
    a, h = bool(mask & ALLIANCE_RACES), bool(mask & HORDE_RACES)
    if a and not h:
        return "A"
    if h and not a:
        return "H"
    return ""


def build_index(version=None, progress=print):
    """Read the downloaded QuestieDB release and write a compact monster index."""
    if not os.path.exists(ZIP_PATH):
        raise DataError("The QuestieDB data hasn't been downloaded yet.")
    progress("Reading monsters, drops and quests...")
    zf = zipfile.ZipFile(ZIP_PATH)
    toc_name = next((n for n in zf.namelist() if n.endswith("QuestieDB_Forever.toc")), None) \
        or next((n for n in zf.namelist() if n.endswith(".toc")), None)
    if not toc_name:
        raise DataError("The QuestieDB download doesn't contain a Forever database.")
    toc = _Toc(zf.read(toc_name).decode("utf-8", "replace"))
    version = version or (re.search(r"## Version: (\S+)", zf.read(toc_name).decode("utf-8", "replace")[:4000])
                          or [None, FALLBACK_VERSION])[1]
    zone_names = _zone_names(zf)
    parents = _parents(zf)
    rates = _drop_rates(zf)
    dungeons = _dungeon_entries(zf, zone_names)
    dungeon_areas = {a for zid, d in dungeons.items() for a in [zid] + d["alt"]}

    def top_zone(z):
        seen = set()
        while z in parents and z not in seen and parents[z] != z:
            seen.add(z)
            z = parents[z]
        return z

    # --- items: who drops what
    drops, items = {}, {}
    for iid in toc.ids("Item"):
        r = toc.row("Item", iid)
        npcs = toc.field("Item", iid, 2, r)
        start_q = r.get(5)
        if not npcs:
            continue
        npcs = [n for n in _arr(npcs) if n]
        items[iid] = {"n": r.get(1) or f"Item {iid}", "c": r.get(12), "sc": r.get(13),
                      "il": r.get(9), "rl": r.get(10)}
        if start_q:
            items[iid]["sq"] = start_q
        if iid in rates:
            items[iid]["rate"] = {str(k): v for k, v in rates[iid].items()}
        for n in npcs:
            drops.setdefault(n, []).append(iid)

    # --- quests: kill and collect objectives, starters and enders
    quests, kill_q, collect_q = {}, {}, {}
    npc_names = {}
    quest_rows = {}
    for qid in toc.ids("Quest"):
        r = toc.row("Quest", qid)
        objs = _arr(toc.field("Quest", qid, 10, r))
        kills, collects = set(), set()
        if objs:
            for o in _arr(objs[0] if len(objs) > 0 else None):
                o = _arr(o)
                if o and o[0]:
                    kills.add(o[0])
            for o in _arr(objs[2] if len(objs) > 2 else None):
                o = _arr(o)
                if o and o[0]:
                    collects.add(o[0])
            for o in _arr(objs[4] if len(objs) > 4 else None):
                o = _arr(o)
                if o:
                    kills.update(n for n in _arr(o[0]) if n)
                    if len(o) > 1 and o[1]:
                        kills.add(o[1])
        extra = _arr(toc.field("Quest", qid, 29, r))      # extraObjectives sometimes name creatures
        started = _arr(toc.field("Quest", qid, 2, r))
        finished = _arr(toc.field("Quest", qid, 3, r))
        text = _arr(toc.field("Quest", qid, 8, r))
        q = {"n": r.get(1) or f"Quest {qid}", "lv": r.get(5), "rl": r.get(4), "fa": _faction(r.get(6)),
             "z": r.get(17) if (r.get(17) or 0) > 0 else None,
             "sn": [n for n in _arr(started[0] if started else None) if n],
             "si": [n for n in _arr(started[2] if len(started) > 2 else None) if n],
             "en": [n for n in _arr(finished[0] if finished else None) if n],
             "t": " ".join(t for t in text if isinstance(t, str))[:400]}
        q["x"] = [r.get(7) or 0,                                      # class mask
                  [n for n in _arr(toc.field("Quest", qid, 13, r)) if n],   # needs any one of these done
                  [n for n in _arr(toc.field("Quest", qid, 12, r)) if n],   # needs all of these done
                  [n for n in _arr(toc.field("Quest", qid, 16, r)) if n],   # can't be done after these
                  int(r.get(24) or 0) & 1,                             # repeatable
                  r.get(17) or 0]                                      # raw zone (negative = a category)
        if kills:
            q["k"] = sorted(kills)
        if collects:
            q["c"] = sorted(collects)
        quest_rows[qid] = q
        for n in kills:
            kill_q.setdefault(n, []).append(qid)
        for i in collects:
            collect_q.setdefault(i, []).append(qid)
        del extra

    # --- NPCs: keep hostile ones with spawns (the monsters), remember names of quest givers
    npcs = {}
    zone_counts = {}
    npc_loc = {}                                     # quest givers: where they stand
    giver_ids = {n for q in quest_rows.values() for n in q["sn"] + q["en"]}
    for nid in toc.ids("Npc"):
        r = toc.row("Npc", nid)
        name = r.get(1) or ""
        if nid in giver_ids:
            npc_names[nid] = name
            spots = _spots(toc.field("Npc", nid, 7, r), top_zone)
            if spots:
                npc_loc[nid] = spots[0][:3]
        if r.get(13) or not name or NOT_MONSTER.search(name):
            continue                                 # friendly to a faction, or a technical NPC
        spawns = toc.field("Npc", nid, 7, r) or {}
        if isinstance(spawns, list):
            spawns = {i + 1: v for i, v in enumerate(spawns) if v}
        z = {}
        for zid, pts in spawns.items():
            try:
                zid = top_zone(int(zid))
            except (TypeError, ValueError):
                continue
            z[zid] = z.get(zid, 0) + max(1, len(_arr(pts)))
        if not z and r.get(9):
            z = {top_zone(int(r[9])): 0}
        lmin, lmax = r.get(4) or 0, r.get(5) or r.get(4) or 0
        has_use = nid in drops or nid in kill_q
        if not z or (lmax <= 1 and not has_use):
            continue                                 # critters and placeholders
        if r.get(15) or nid in giver_ids:
            continue                                 # vendors, innkeepers, trainers, quest givers
        if not r.get(12) and not has_use:
            continue                                 # new Forever NPC with no faction data: only keep
                                                     # it if it drops loot or is a kill target
        npcs[nid] = {"n": name, "l": [lmin, lmax], "r": r.get(6) or 0, "z": z}
        spots = _spots(spawns, top_zone)
        if spots:
            npcs[nid]["p"] = spots
        if r.get(14):
            npcs[nid]["s"] = r[14]
        for zid, cnt in z.items():
            zone_counts[zid] = zone_counts.get(zid, 0) + 1

    # keep only items/quests that touch a monster
    for nid in list(drops):
        if nid not in npcs:
            del drops[nid]
    used_items = {i for lst in drops.values() for i in lst}
    items = {i: v for i, v in items.items() if i in used_items}
    used_q = set()
    for nid in npcs:
        used_q.update(kill_q.get(nid, []))
        for i in drops.get(nid, []):
            used_q.update(collect_q.get(i, []))
            if items.get(i, {}).get("sq"):
                used_q.add(items[i]["sq"])
    # every quest, compact, for the Progress tab: [name, level, required level, faction, zone,
    # class mask, needs-one, needs-all, exclusive-to, repeatable, first giver, turn-in, objective,
    # giver's spot [zone, x, y] or 0, turn-in's spot]
    allq, qzones = {}, {}
    for qid, q in quest_rows.items():
        x = q.pop("x")
        zt = top_zone(x[5]) if x[5] > 0 else 0
        if zt and zt not in qzones:
            qzones[zt] = zone_names.get(zt, (f"Area {zt}", ""))[0]
        giver = next((npc_names.get(n) for n in q["sn"] if npc_names.get(n)), "")
        ender = next((npc_names.get(n) for n in q["en"] if npc_names.get(n)), "")
        gloc = next((npc_loc[n] for n in q["sn"] if npc_names.get(n) and n in npc_loc), 0)
        eloc = next((npc_loc[n] for n in q["en"] if npc_names.get(n) and n in npc_loc), 0)
        for loc in (gloc, eloc):
            if loc and loc[0] not in qzones:
                qzones[loc[0]] = zone_names.get(loc[0], (f"Area {loc[0]}", ""))[0]
        allq[qid] = [q["n"], q.get("lv") or 0, q.get("rl") or 0, q["fa"], zt, x[0], x[1], x[2], x[3], x[4], giver,
                     ender, q.get("t") or "", gloc, eloc]

    # quests filed under a dungeon stay too, even with no kill or collect objective
    used_q.update(qid for qid, q in quest_rows.items() if q.get("z") in dungeon_areas)
    quests = {}
    for qid in used_q:
        q = quest_rows.get(qid)
        if not q:
            continue
        q = dict(q)
        q["sn"] = [npc_names.get(n) or f"NPC {n}" for n in q["sn"]]
        q["en"] = [npc_names.get(n) or f"NPC {n}" for n in q["en"]]
        quests[qid] = q

    zones = {}
    for zid, cnt in zone_counts.items():
        name, group = zone_names.get(zid, (f"Area {zid}", "Other"))
        if "prototype" in name.lower() or "test" in name.lower():
            group = "Other"
        zones[zid] = {"n": name, "g": group, "m": cnt}

    idx = {"schema": INDEX_SCHEMA, "version": version, "built": int(time.time()),
           "zones": zones, "dungeons": dungeons, "allq": allq, "qzones": qzones, "npcs": npcs, "drops": drops, "items": items, "quests": quests}
    tmp = INDEX_PATH + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, separators=(",", ":"))
    os.replace(tmp, INDEX_PATH)
    return idx


# ================================================================ loading and queries

class Compendium:
    """Loaded monster index with the lookups the window needs."""

    GROUP_ORDER = ["Eastern Kingdoms", "Kalimdor", "Forever", "Dungeons and raids",
                   "Classic dungeons and raids", "Classic battlegrounds", "Other"]

    def __init__(self, idx):
        self.version = idx.get("version")
        self.built = idx.get("built")
        self.zones = {int(k): v for k, v in idx["zones"].items()}
        self.npcs = {int(k): {**v, "z": {int(z): c for z, c in v["z"].items()}} for k, v in idx["npcs"].items()}
        self.drops = {int(k): v for k, v in idx["drops"].items()}
        self.items = {int(k): v for k, v in idx["items"].items()}
        self.quests = {int(k): v for k, v in idx["quests"].items()}
        self.dungeons = {int(k): v for k, v in idx.get("dungeons", {}).items()}
        self.allq = {int(k): v for k, v in idx.get("allq", {}).items()}
        self.qzones = {int(k): v for k, v in idx.get("qzones", {}).items()}
        self.by_zone = {}
        for nid, n in self.npcs.items():
            for z in n["z"]:
                self.by_zone.setdefault(z, []).append(nid)
        self.kill_q, self.collect_q = {}, {}
        for qid, q in self.quests.items():
            for n in q.get("k", []):
                self.kill_q.setdefault(n, []).append(qid)
            for i in q.get("c", []):
                self.collect_q.setdefault(i, []).append(qid)

    # --- regions
    def group_of(self, zid):
        g = self.zones.get(zid, {}).get("g", "Other")
        if zid in BATTLEGROUNDS or "battleground" in g.lower():
            return "Battlegrounds"
        if zid in FOREVER_ZONES:
            return "Forever: new areas"
        if zid in (10073, 10074, 10089):
            return "Other"
        if "dungeon" in g.lower() or "raid" in g.lower():
            return "Dungeons and raids"
        if g.startswith("Eastern Kingdoms"):
            return "Eastern Kingdoms"
        if g.startswith("Kalimdor"):
            return "Kalimdor"
        if g == "Forever":
            return "Forever: new areas"
        if "battleground" in g.lower():
            return "Battlegrounds"
        return "Other"

    def regions(self):
        """[(group, [(zone id, name, monster count), ...]), ...] sorted for the side list."""
        groups = {}
        for zid, z in self.zones.items():
            groups.setdefault(self.group_of(zid), []).append((zid, z["n"], len(self.by_zone.get(zid, []))))
        order = ["Eastern Kingdoms", "Kalimdor", "Forever: new areas", "Dungeons and raids", "Battlegrounds", "Other"]
        out = []
        for g in order:
            if g in groups:
                out.append((g, sorted(groups[g], key=lambda t: t[1].lower())))
        return out

    def zone_name(self, zid):
        return self.zones.get(zid, {}).get("n", f"Area {zid}")

    # --- monsters
    def monsters_in(self, zid):
        return sorted(self.by_zone.get(zid, []), key=lambda n: (self.npcs[n]["l"][0], self.npcs[n]["n"]))

    def search(self, text, limit=300):
        t = text.replace("\u2019", "'").lower().strip()
        if not t:
            return []
        hits = [nid for nid, n in self.npcs.items() if t in n["n"].lower()]
        if t.isdigit() and int(t) in self.npcs:
            hits.insert(0, int(t))
        hits.sort(key=lambda n: (not self.npcs[n]["n"].lower().startswith(t), self.npcs[n]["n"]))
        return hits[:limit]

    def find_by_drop(self, text, limit=300):
        """Monsters that drop an item whose name contains the text."""
        t = text.replace("\u2019", "'").lower().strip()
        ids = {i for i, it in self.items.items() if t and t in it["n"].lower()}
        hits = [nid for nid, lst in self.drops.items() if ids.intersection(lst)]
        return sorted(hits, key=lambda n: self.npcs[n]["n"])[:limit]

    def where(self, nid):
        """[(zone name, x, y, spawn points)] - the busiest spot in each zone the monster is in."""
        return [(self.zone_name(z), x, y, n) for z, x, y, n in self.npcs[nid].get("p", [])]

    def quest_spot(self, qid, end=False):
        """(zone name, x, y) of a quest's giver (or its turn-in), or None."""
        q = self.allq.get(qid)
        loc = q[14 if end else 13] if q and len(q) > 14 else 0
        return (self.qzones.get(loc[0]) or self.zone_name(loc[0]), loc[1], loc[2]) if loc else None

    def level_text(self, nid):
        a, b = self.npcs[nid]["l"]
        if a >= 100 or b >= 100:
            return "??"                              # skull level: always above the player
        return f"{a}" if a == b or not b else f"{a}-{b}"

    def rank_text(self, nid):
        return RANKS.get(self.npcs[nid].get("r") or 0, "")

    def main_zone(self, nid):
        z = self.npcs[nid]["z"]
        return max(z, key=lambda k: z[k]) if z else None

    def drops_of(self, nid):
        """Item dicts this monster can drop, quest items and gear first."""
        out = []
        for iid in self.drops.get(nid, []):
            it = self.items.get(iid)
            if not it:
                continue
            rate = (it.get("rate") or {}).get(str(nid))
            out.append({"id": iid, "name": it["n"], "cls": ITEM_CLASSES.get(it.get("c"), "Other"),
                        "ilvl": it.get("il"), "req": it.get("rl"), "rate": rate,
                        "starts": it.get("sq")})
        out.sort(key=lambda d: (d["cls"] != "Quest", -(d["rate"] or 0), d["name"]))
        return out

    def quests_for(self, nid):
        """[(quest id, quest dict, why)] for quests that need this monster or its drops."""
        out, seen = [], set()

        def add(qid, why):
            q = self.quests.get(qid)
            if q and (qid, why) not in seen:
                seen.add((qid, why))
                out.append((qid, q, why))

        prio = {}
        for qid in self.kill_q.get(nid, []):
            add(qid, "Kill")
            prio[(qid, "Kill")] = 0
        for iid in self.drops.get(nid, []):
            it = self.items.get(iid, {})
            name = it.get("n", f"item {iid}")
            for qid in self.collect_q.get(iid, []):
                why = f"Collect {name}"
                add(qid, why)
                prio[(qid, why)] = 1 if it.get("c") == 12 or it.get("rate") else 2   # quest items first
            if it.get("sq"):
                why = f"{name} starts it"
                add(it["sq"], why)
                prio[(it["sq"], why)] = 1
        out.sort(key=lambda t: (prio.get((t[0], t[2]), 2), t[1].get("lv") or 0, t[1]["n"]))
        return out


_loaded = None


def index_info():
    """(version, built timestamp) of the saved index, or (None, None)."""
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            head = f.read(200)
        v = re.search(r'"version":"([^"]*)"', head)
        b = re.search(r'"built":(\d+)', head)
        return (v.group(1) if v else None), (int(b.group(1)) if b else None)
    except OSError:
        return None, None


def load(progress=print, update=False):
    """The Compendium, downloading and indexing QuestieDB the first time (or on update)."""
    global _loaded
    idx = None
    if not update and os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                idx = json.load(f)
            if idx.get("schema") != INDEX_SCHEMA:
                idx = None
        except (OSError, ValueError):
            idx = None
    if idx is None:
        version = None
        if update or not os.path.exists(ZIP_PATH):
            latest = latest_version()
            have, _ = index_info()
            if update and latest and have == latest and os.path.exists(ZIP_PATH):
                version = latest
            else:
                version = download(latest, progress)
        idx = build_index(version, progress)
    _loaded = Compendium(idx)
    return _loaded


def newer_release():
    """The latest QuestieDB version if it is newer than ours, else None."""
    have, _ = index_info()
    latest = latest_version()
    return latest if latest and have and latest != have else None


# ================================================================ tracking list

def load_tracking():
    data = wp.load_json(TRACK_PATH, [])
    return data if isinstance(data, list) else []


def save_tracking(entries):
    wp.save_json(TRACK_PATH, entries)


# ================================================================ AH value of a monster's drops

def price_drops(api, item_ids):
    """{item id: summary or None} using the app's normal auction snapshot."""
    sources = wp.get_sources(api)
    return {i: wp.item_summary(sources, i) for i in item_ids}
