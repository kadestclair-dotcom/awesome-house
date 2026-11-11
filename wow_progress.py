"""
wow_progress.py - Progress tab data for Awesome House (WoW: Forever).

Reads one character's progress from Blizzard's Profile API (completed and current quests,
achievements, reputations, professions, PvP summary, dungeon/raid encounters, statistics)
and compares it with the full quest list in the Monster Compendium index (QuestieDB) to
show progress per zone and suggest what to do next.

The last snapshot of each character is kept in character_progress.json next to the app
(personal data, never shared).
"""

import re
import time

import wow_price as wp
import wow_dungeons as wd

PROGRESS_PATH = wp.os.path.join(wp.HERE, "character_progress.json")
OTHER_ZONE = "Class, profession and event quests"
# QuestieDB quest fields in the index (see wow_monsters.build_index)
N, LV, RL, FA, ZONE, CLS, PRE_ONE, PRE_ALL, EXCL, REPEAT, GIVER, ENDER, TEXT = range(13)
QINFO_PATH = wp.os.path.join(wp.CACHE_DIR, "forever_quest_info.json")


# ================================================================ fetch

def _opt(api, path, missing):
    try:
        return api.get(path, "profile") or {}
    except (wp.ApiError, SystemExit):
        missing.append(path.rsplit("/character/", 1)[-1].split("/", 1)[-1])
        return {}


def _name(x):
    return wp._loc(x.get("name")) if isinstance(x, dict) else ""


def _stats(d):
    out = []

    def add(cat, sub, lst):
        for s in lst or []:
            if not isinstance(s, dict):
                continue
            q = s.get("quantity")
            out.append({"cat": cat, "sub": sub, "name": _name(s), "qty": q,
                        "desc": wp._loc(s.get("description")) or ""})
    for c in d.get("categories") or []:
        add(_name(c), "", c.get("statistics"))
        for sc in c.get("sub_categories") or []:
            add(_name(c), _name(sc), sc.get("statistics"))
    return out


def _encounters(d):
    """[[instance, mode, bosses down, bosses total, last kill timestamp]] from either page."""
    out = []
    groups = d.get("expansions") or [d]
    for g in groups:
        for inst in g.get("instances") or []:
            name = _name(inst.get("instance") or inst)
            for m in inst.get("modes") or [{}]:
                pr = m.get("progress") or {}
                last = max((e.get("last_kill_timestamp") or 0 for e in pr.get("encounters") or []), default=0)
                out.append([name, _name(m.get("difficulty") or {}), pr.get("completed_count") or 0,
                            pr.get("total_count") or 0, last])
    return out


def _amount(c):
    if not isinstance(c, dict):
        return 0
    kids = c.get("child_criteria") or []
    return (c.get("amount") or 0) if not kids else max((_amount(k) for k in kids), default=0)


def fetch(name, surname):
    """Download one Forever character's progress. Raises ApiError (404 = not found)."""
    api = wp.connect("forever")
    base = f"/profile/wow/character/{wp.char_slug(name, surname)}"
    prof = api.get(base, "profile")
    missing = []
    pages = ["/quests", "/quests/completed", "/achievements", "/reputations", "/professions", "/pvp-summary",
             "/encounters/dungeons", "/encounters/raids", "/achievements/statistics"]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(5) as ex:            # the pages don't depend on each other
        quests, done, ach, reps, profs, pvp, enc_d, enc_r, stats = ex.map(
            lambda page: _opt(api, base + page, missing), pages)

    faction = wp._type(prof.get("faction")) or ""
    snap = {
        "name": prof.get("name") or name, "surname": prof.get("surname") or surname or "",
        "level": wp._int(prof.get("level")) or 0, "xp": prof.get("experience"),
        "cls": _name(prof.get("character_class") or {}), "cls_id": (prof.get("character_class") or {}).get("id") or 0,
        "race": _name(prof.get("race") or {}), "faction": "A" if str(faction).upper().startswith("A") else "H",
        "guild": _name(prof.get("guild") or {}), "guild_slug": (prof.get("guild") or {}).get("slug") or "",
        "fetched": int(time.time()), "missing": missing,
        "completed": sorted({q["id"] for q in done.get("quests") or [] if isinstance(q, dict) and q.get("id")}),
        "in_progress": [[q.get("id"), _name(q)] for q in quests.get("in_progress") or [] if isinstance(q, dict)],
        "achievements": [], "reputations": [], "professions": [],
        "pvp": {"hk": pvp.get("honorable_kills"), "rank": pvp.get("pvp_rank")} if pvp else {},
        "dungeons": _encounters(enc_d), "raids": _encounters(enc_r), "stats": _stats(stats),
        "points": ach.get("total_points"),
    }
    for a in ach.get("achievements") or []:
        if not isinstance(a, dict):
            continue
        c = a.get("criteria") or {}
        snap["achievements"].append({"name": _name(a.get("achievement") or {}), "id": a.get("id"),
                                     "done": bool(a.get("completed_timestamp") or c.get("is_completed")),
                                     "amount": _amount(c), "ts": a.get("completed_timestamp") or 0})
    for r in reps.get("reputations") or []:
        st = r.get("standing") or {}
        snap["reputations"].append({"name": _name(r.get("faction") or {}), "standing": _name(st),
                                    "value": st.get("value") or 0, "max": st.get("max") or 0,
                                    "tier": st.get("tier") or 0, "raw": st.get("raw") or 0})
    for kind in ("primaries", "secondaries"):
        for p in profs.get(kind) or []:
            tiers = p.get("tiers") or [p]
            for t in tiers:
                snap["professions"].append({"name": _name(p.get("profession") or {}), "primary": kind == "primaries",
                                            "skill": t.get("skill_points") or 0, "max": t.get("max_skill_points") or 0,
                                            "recipes": len(t.get("known_recipes") or [])})
    return snap


_qinfo = None


def quest_info(qid):
    """Blizzard's own page for a quest: {"desc", "xp", "money", "items"}; {} when it has none.
    Kept in .wow_price_cache so each quest is only asked for once."""
    global _qinfo
    if _qinfo is None:
        data = wp.load_json(QINFO_PATH, {})
        _qinfo = data if isinstance(data, dict) else {}
    if str(qid) in _qinfo:
        return _qinfo[str(qid)]
    try:
        d = wp.connect("forever").get(f"/data/wow/quest/{qid}", "static") or {}
    except wp.ApiError as e:
        if e.code != 404:
            return {}                        # a hiccup: ask again next time
        d = {}
    rw = d.get("rewards") if isinstance(d.get("rewards"), dict) else {}
    money = rw.get("money")
    if isinstance(money, dict):
        money = money.get("value") or money.get("units")
    items = []
    for group in ((rw.get("items") or {}) if isinstance(rw.get("items"), dict) else {}).values():
        for it in group if isinstance(group, list) else []:
            nm = _name(it.get("item") or it) if isinstance(it, dict) else ""
            if nm:
                items.append(nm)
    info = {"desc": (wp._loc(d.get("description")) or "").strip(), "xp": rw.get("experience") or 0,
            "money": money if isinstance(money, (int, float)) else 0, "items": items[:8]}
    if not any(info.values()):
        info = {}
    _qinfo[str(qid)] = info
    wp.os.makedirs(wp.CACHE_DIR, exist_ok=True)
    wp.save_json(QINFO_PATH, _qinfo)
    return info


def key_of(snap):
    return f"{snap.get('name', '')} {snap.get('surname', '')}".strip().lower()


def load_saved():
    """{"last": key, "chars": {key: snapshot}}"""
    data = wp.load_json(PROGRESS_PATH, {})
    if not isinstance(data, dict) or not isinstance(data.get("chars"), dict):
        return {"last": None, "chars": {}}
    return data


def save(snap):
    data = load_saved()
    data["chars"][key_of(snap)] = snap
    data["last"] = key_of(snap)
    keep = sorted(data["chars"], key=lambda k: -data["chars"][k].get("fetched", 0))[:24]
    data["chars"] = {k: data["chars"][k] for k in keep}
    wp.save_json(PROGRESS_PATH, data)


def forget(key):
    """Drop one character from the saved list."""
    data = load_saved()
    if data["chars"].pop(key, None) is not None:
        if data.get("last") == key:
            data["last"] = next(iter(data["chars"]), None)
        wp.save_json(PROGRESS_PATH, data)


def refresh_all():
    """Re-read every saved character from Blizzard. Returns (updated, [names that failed])."""
    ok, failed = 0, []
    last = load_saved().get("last")
    for key, old in list(load_saved()["chars"].items()):
        try:
            save(fetch(old["name"], old.get("surname") or None))
            ok += 1
        except (wp.ApiError, SystemExit, OSError):
            failed.append(f"{old['name']} {old.get('surname', '')}".strip())
    data = load_saved()
    if last in data["chars"]:
        data["last"] = last
        wp.save_json(PROGRESS_PATH, data)
    return ok, failed


# ================================================================ quests against QuestieDB

def gray_level(level):
    """Quests at or below this level give no experience any more (Classic rule)."""
    if level <= 5:
        return 0
    if level <= 39:
        return level - level // 10 - 5
    if level <= 59:
        return level - level // 5 - 1
    return level - 9


class Progress:
    """One character's snapshot matched against the quest list."""

    def __init__(self, db, snap):
        self.db, self.snap = db, snap
        self.level = snap.get("level") or 0
        self.done = set(snap.get("completed") or [])
        self.active = {q[0] for q in snap.get("in_progress") or [] if q[0]}
        self.cls_bit = 1 << (snap["cls_id"] - 1) if snap.get("cls_id") else 0
        self.gray = gray_level(self.level)
        self.mine = {qid: q for qid, q in db.allq.items() if self.for_me(q)}
        self.unknown_done = len(self.done - set(db.allq))
        self._dungeons = None

    def for_me(self, q):
        if q[FA] and q[FA] != self.snap.get("faction"):
            return False
        return not (q[CLS] and self.cls_bit and not q[CLS] & self.cls_bit)

    def zone_name(self, q):
        return self.db.qzones.get(q[ZONE]) or OTHER_ZONE

    def state(self, qid):
        """done / active / now (can pick up, still worth it) / gray / later (level or earlier quest needed)."""
        q = self.db.allq[qid]
        if qid in self.done:
            return "done"
        if qid in self.active:
            return "active"
        if any(x in self.done for x in q[EXCL]):
            return "closed"
        if q[RL] > self.level or (q[PRE_ONE] and not any(x in self.done for x in q[PRE_ONE])) \
                or any(x not in self.done for x in q[PRE_ALL]):
            return "later"
        if 0 < q[LV] <= self.gray:
            return "gray"
        if q[LV] > self.level + 3:
            return "later"
        return "now"

    def blockers(self, qid):
        """Names of the earlier quests still needed, or a level note."""
        q = self.db.allq[qid]
        out = []
        if q[RL] > self.level:
            out.append(f"needs level {q[RL]}")
        need = [x for x in q[PRE_ALL] if x not in self.done]
        if q[PRE_ONE] and not any(x in self.done for x in q[PRE_ONE]):
            need += q[PRE_ONE][:1]
        for x in need[:3]:
            out.append("after " + (self.db.allq[x][N] if x in self.db.allq else f"quest {x}"))
        if not out and q[LV] > self.level + 3:
            out.append(f"level {q[LV]} quest")
        return out

    def zones(self):
        """[{name, total, done, now, later, gray, lo, hi, ids}] for every zone with quests for this character."""
        z = {}
        for qid, q in self.mine.items():
            if q[REPEAT]:
                continue
            st = self.state(qid)
            if st == "closed":
                continue
            d = z.setdefault(self.zone_name(q), {"total": 0, "done": 0, "now": 0, "later": 0, "gray": 0,
                                                 "active": 0, "lv": [], "ids": []})
            d["total"] += 1
            d[st] += 1
            d["ids"].append(qid)
            if q[LV] > 0:
                d["lv"].append(q[LV])
        out = []
        for name, d in z.items():
            lv = sorted(d.pop("lv"))
            d["name"] = name
            d["lo"], d["hi"] = (lv[len(lv) // 10], lv[-1 - len(lv) // 10]) if lv else (0, 0)
            out.append(d)
        out.sort(key=lambda d: (-d["now"], abs((d["lo"] + d["hi"]) / 2 - self.level), d["name"]))
        return out

    def dungeons(self):
        """[{id, name, kind, levels, total, done, now, fits}] quest progress per dungeon and raid."""
        if self._dungeons is not None:
            return self._dungeons
        out = self._dungeons = []
        for _g, lst in wd.dungeon_list(self.db):
            for d in lst:
                ids = [qid for qid, _q, _w in wd.dungeon_quests(self.db, d["id"])
                       if qid in self.mine and not self.mine[qid][REPEAT]]
                lv = d["levels"]
                out.append({"id": d["id"], "name": d["name"], "kind": d["kind"], "levels": lv,
                            "total": len(ids), "done": sum(1 for q in ids if q in self.done),
                            "now": [q for q in ids if self.state(q) in ("now", "active")],
                            "fits": bool(lv) and lv[0] - 2 <= self.level <= lv[1] + 1})
        return out

    def recommend(self, zones=None):
        """What to do next, as {"finish", "zone", "quests", "also", "dungeons", "reps", "profs", "milestones"}."""
        zones = self.zones() if zones is None else zones
        real = [z for z in zones if z["name"] != OTHER_ZONE and z["now"]]
        best = real[0] if real else None
        picks = []
        for z in real[:3]:
            ids = sorted((q for q in z["ids"] if self.state(q) == "now"),
                         key=lambda q: (abs(self.db.allq[q][LV] - self.level), self.db.allq[q][N]))
            picks += [(q, z["name"]) for q in ids[:8 if z is best else 3]]
        nearly = [z for z in zones if z["name"] != OTHER_ZONE and z["total"] >= 8 and z["now"]
                  and z["done"] / z["total"] >= 0.7 and z is not best][:2]
        reps = sorted((r for r in self.snap.get("reputations") or [] if r.get("max") and r["value"] < r["max"]),
                      key=lambda r: -(r["value"] / r["max"]))
        return {"finish": [q for q in self.snap.get("in_progress") or []], "zone": best, "quests": picks,
                "nearly": nearly, "dungeons": [d for d in self.dungeons() if d["fits"]],
                "reps": [r for r in reps if r["value"] / r["max"] >= 0.5][:2],
                "profs": [p for p in self.snap.get("professions") or [] if p.get("max")],
                "milestones": [a for a in self.snap.get("achievements") or [] if not a["done"] and a["amount"]][:4]}

    # ------------------------------------------------------------ route
    def _item_sources(self):
        if getattr(self.db, "_item_src", None) is None:
            src = {}
            for nid, lst in self.db.drops.items():
                for iid in lst:
                    src.setdefault(iid, []).append(nid)
            self.db._item_src = src
        return self.db._item_src

    def _monster_spot(self, nid, zid):
        """(x, y, spawn points) of a monster in one zone, or None."""
        for z, x, y, n in self.db.npcs.get(nid, {}).get("p", []):
            if z == zid:
                return x, y, n
        return None

    def route(self, zones=None, max_quests=10):
        """An ordered plan for one zone: pick up, do, turn in - nearest stop first.
        Returns {"zone", "stops": [{"x", "y", "acts": [(kind, text, quest id)]}],
                 "elsewhere": [(text, zone, x, y, quest id)], "unknown": [(text, quest id)], "quests": n}."""
        db = self.db
        zones = self.zones() if zones is None else zones
        best = next((z for z in zones if z["name"] != OTHER_ZONE and z["now"]), None)
        picks = sorted((q for q in (best["ids"] if best else []) if self.state(q) == "now"),
                       key=lambda q: (abs(db.allq[q][LV] - self.level), db.allq[q][N]))[:max_quests]
        active = [q for q in self.active if q in db.allq]
        quests = active + picks
        # the map everything is measured on: where most of these quests start (or end)
        votes = {}
        for q in quests:
            for loc in (db.allq[q][13], db.allq[q][14]):
                if loc:
                    votes[loc[0]] = votes.get(loc[0], 0) + (2 if q in picks else 1)
        if not votes:
            return {"zone": best["name"] if best else "", "stops": [], "elsewhere": [], "quests": len(quests),
                    "unknown": [(db.allq[q][N], q) for q in quests]}
        zid = max(votes, key=lambda z: votes[z])
        zname = db.qzones.get(zid) or db.zone_name(zid)
        steps, elsewhere, unknown = [], [], []

        def place(q, kind, text, loc):
            """Add a step on this map; returns False when it lies on another map or has no position."""
            if loc and loc[0] == zid:
                steps.append({"q": q, "kind": kind, "text": text, "x": loc[1], "y": loc[2]})
                return True
            if loc:
                elsewhere.append((text, db.qzones.get(loc[0]) or db.zone_name(loc[0]), loc[1], loc[2], q))
            else:
                unknown.append((text, q))
            return False

        for q in quests:
            row, rich = db.allq[q], db.quests.get(q) or {}
            name = row[N]
            if q in picks:
                if not row[13]:                      # starts from an item or object: nowhere to send you
                    unknown.append((f"{name}: where it starts isn't in the data", q))
                    continue
                if not place(q, "get", f"Pick up {name}" + (f" from {row[GIVER]}" if row[GIVER] else ""), row[13]):
                    continue                         # its giver is on another map
            for nid in (rich.get("k") or [])[:3]:
                spot = self._monster_spot(nid, zid)
                if nid in db.npcs:
                    place(q, "do", f"Kill {db.npcs[nid]['n']} for {name}", [zid, spot[0], spot[1]] if spot else 0)
            for iid in (rich.get("c") or [])[:3]:
                item = db.items.get(iid, {}).get("n") or f"item {iid}"
                spots = [(self._monster_spot(n, zid), n) for n in self._item_sources().get(iid, [])]
                spots = [(s, n) for s, n in spots if s]
                if spots:
                    s, n = max(spots, key=lambda t: t[0][2])
                    place(q, "do", f"Get {item} from {db.npcs[n]['n']} for {name}", [zid, s[0], s[1]])
                else:
                    unknown.append((f"Get {item} for {name}", q))
            known = bool(rich.get("k") or rich.get("c"))
            same_spot = row[13] and row[14] and row[13][0] == row[14][0] \
                and abs(row[13][1] - row[14][1]) < 2 and abs(row[13][2] - row[14][2]) < 2
            if not known and (same_spot or not row[14]) and q in picks:
                # nothing to kill or loot from a monster, and it ends where it starts: the objective
                # (an object to click, a place to visit...) isn't in the data
                unknown.append((f"{name}: " + (row[TEXT][:130] or "objective not in the data")
                                + (f" Turn in to {row[ENDER]}." if row[ENDER] else ""), q))
                continue
            place(q, "end", f"Turn in {name}" + (f" to {row[ENDER]}" if row[ENDER] else ""), row[14])

        # nearest stop first, never an objective before its pick-up or a turn-in before its objectives
        def near(a, b):
            return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
        gets = [s for s in steps if s["kind"] == "get"]
        todo, order, pos = list(steps), [], None
        if gets:
            pos = max(gets, key=lambda a: sum(1 for b in gets if near(a, b) < 4))
        rank = {"get": 0, "end": 1, "do": 2}
        while todo:
            ready = [s for s in todo if s["kind"] == "get"
                     or (s["kind"] == "do" and not any(t["q"] == s["q"] and t["kind"] == "get" for t in todo))
                     or (s["kind"] == "end" and not any(t["q"] == s["q"] and t["kind"] != "end" for t in todo))]
            pos = pos or ready[0]
            nxt = min(ready, key=lambda s: (round(near(pos, s) / 2), rank[s["kind"]], near(pos, s)))
            todo.remove(nxt)
            order.append(nxt)
            pos = nxt
        stops = []
        for s in order:
            if stops and abs(stops[-1]["x"] - s["x"]) < 2 and abs(stops[-1]["y"] - s["y"]) < 2:
                stops[-1]["acts"].append((s["kind"], s["text"], s["q"]))
            else:
                stops.append({"x": s["x"], "y": s["y"], "acts": [(s["kind"], s["text"], s["q"])]})
        return {"zone": zname, "stops": stops, "elsewhere": elsewhere, "unknown": unknown, "quests": len(quests)}


def pick_stats(snap, pattern):
    """Statistics whose category, group or name matches the pattern."""
    rx = re.compile(pattern, re.I)
    return [s for s in snap.get("stats") or [] if rx.search(f"{s['cat']} {s['sub']} {s['name']}")]


# ================================================================ guild crafters

GUILD_SECONDS = 24 * 3600


def guild_slug(name):
    return wp.urllib.parse.quote(re.sub(r"[^\w\s-]", "", name.strip().lower()).replace(" ", "-"))


def _guild_path(slug):
    return wp.os.path.join(wp.CACHE_DIR, f"forever_guild_{slug}.json")


def guild_cached(slug):
    """The saved guild directory, or None."""
    data = wp.load_json(_guild_path(slug), None)
    return data if isinstance(data, dict) and data.get("members") is not None else None


def guild_crafters(slug, progress=None, force=False, max_members=400):
    """{"name", "fetched", "listed", "members": [{"name", "level", "cls", "profs": [{"name", "skill", "max",
    "recipes": [names]}]}]} - the guild roster and what each member can craft. Kept for a day."""
    old = guild_cached(slug)
    if old and not force and time.time() - old.get("fetched", 0) < GUILD_SECONDS:
        return old
    api = wp.connect("forever")
    roster = api.get(f"/data/wow/guild/{slug}/roster", "profile")
    members = []
    for m in roster.get("members") or []:
        c = m.get("character") if isinstance(m, dict) and isinstance(m.get("character"), dict) else m
        if not isinstance(c, dict) or not c.get("name"):
            continue
        members.append({"name": f"{c['name']} {c.get('surname') or ''}".strip(),
                        "slug": c.get("slug") or wp.char_slug(c["name"], c.get("surname")),
                        "level": wp._int(c.get("level")) or 0,
                        "cls": _name(c.get("playable_class") or c.get("character_class") or {}),
                        "rank": m.get("rank") if isinstance(m, dict) else None})
    if not members:                          # an unexpected answer: keep it so it can be looked at
        wp.save_json(wp.os.path.join(wp.CACHE_DIR, "guild_debug.json"), roster)
        raise SystemExit("Blizzard's answer for this guild had no member list in the form the app expects. "
                         "It was saved as guild_debug.json in .wow_price_cache.")
    members.sort(key=lambda m: -m["level"])
    listed, members = len(members), members[:max_members]

    def one(m):
        try:
            d = api.get(f"/profile/wow/character/{m['slug']}/professions", "profile")
        except (wp.ApiError, SystemExit):
            return m, None
        profs = []
        for kind in ("primaries", "secondaries"):
            for p in d.get(kind) or []:
                for t in p.get("tiers") or [p]:
                    profs.append({"name": _name(p.get("profession") or {}), "skill": t.get("skill_points") or 0,
                                  "max": t.get("max_skill_points") or 0,
                                  "recipes": [_name(r) for r in t.get("known_recipes") or [] if _name(r)]})
        return m, profs

    from concurrent.futures import ThreadPoolExecutor
    out, done = [], 0
    with ThreadPoolExecutor(8) as ex:
        for m, profs in ex.map(one, members):
            done += 1
            if progress and (done % 10 == 0 or done == len(members)):
                progress(done, len(members))
            out.append({"name": m["name"], "level": m["level"], "cls": m["cls"], "profs": profs or [],
                        "read": profs is not None})
    data = {"name": _name(roster.get("guild") or {}) or slug, "fetched": int(time.time()), "listed": listed,
            "members": out}
    wp.os.makedirs(wp.CACHE_DIR, exist_ok=True)
    wp.save_json(_guild_path(slug), data)
    return data


def find_crafters(guild, text):
    """[(recipe, member, profession, skill, level)] for recipes whose name contains the text."""
    t = text.lower().strip()
    out = []
    for m in guild["members"]:
        for p in m["profs"]:
            for r in p["recipes"]:
                if t in r.lower():
                    out.append((r, m["name"], p["name"], p["skill"], m["level"]))
    out.sort(key=lambda x: (x[0].lower(), -x[3]))
    return out


def guild_professions(guild):
    """[(profession, member, skill, cap, recipes known, level)] - highest skill first."""
    out = [(p["name"], m["name"], p["skill"], p["max"], len(p["recipes"]), m["level"])
           for m in guild["members"] for p in m["profs"] if p["name"]]
    out.sort(key=lambda x: (x[0], -x[2], x[1]))
    return out
