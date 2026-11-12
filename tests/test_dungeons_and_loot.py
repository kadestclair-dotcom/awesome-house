"""Dungeons tab (wow_dungeons) and the loot finder (wow_loot)."""

import json
import os
import time

import pytest

import wow_dungeons as wd
import wow_loot as wl
import wow_price as wp
from conftest import ROOT, book, char


# ---------------------------------------------------------------- travel notes

def test_load_travel_user_copy_wins_and_reloads(use_travel):
    wp.save_json(wd.BUNDLED_PATH, {"dungeons": {"2": {"kind": "raid"}, "7": {"kind": "dungeon"},
                                                "_x": {"kind": "junk"}, "8": "not a dict"}})
    t = wd.load_travel()
    assert t[2]["kind"] == "dungeon" and t[7]["kind"] == "dungeon" and set(t) == {2, 3, 7}
    assert wd.load_travel() is t                          # unchanged files: not re-read
    time.sleep(0.02)
    wp.save_json(wd.USER_PATH, {"dungeons": {"2": {"kind": "raid"}}})
    os.utime(wd.USER_PATH, (time.time() + 5, time.time() + 5))
    assert wd.load_travel()[2]["kind"] == "raid"


def test_load_travel_with_broken_files():
    with open(wd.USER_PATH, "w") as f:
        f.write("{broken")
    assert wd.load_travel() == {}


def test_editable_path_copies_the_built_in_notes():
    wp.save_json(wd.BUNDLED_PATH, {"dungeons": {"5": {"kind": "dungeon"}}})
    path = wd.editable_path()
    assert path == wd.USER_PATH and json.load(open(path))["dungeons"]["5"]["kind"] == "dungeon"


def test_route(travel):
    assert wd.route(travel[2], "horde") == ("Crossroads", ["Fly to the Crossroads", "Run south"])
    assert wd.route(travel[2], "alliance") == ("", [])
    assert wd.route(None, "horde") == ("", [])


# ---------------------------------------------------------------- dungeon pages

def test_level_range_ignores_skull_levels(db):
    assert wd.level_range(db, 2) == (18, 22)
    assert wd.level_range(db, 3) == (60, 63)
    assert wd.level_range(db, 1234) is None


def test_entrances_merge_doors_with_the_same_name(db):
    out = wd.entrances(db, 2)
    assert out == [("Testlands", 30.0, 30.0, ""), ("Testlands", 80.0, 20.0, "back")]
    assert wd.entrances(db, 999) == []


def test_dungeon_list_groups(db, travel):
    groups = dict(wd.dungeon_list(db, travel))
    assert [d["name"] for d in groups["Dungeons"]] == ["Grim Hold"]
    assert [d["name"] for d in groups["Raids"]] == ["Raid Peak"]
    assert "Forever additions" not in groups
    gh = groups["Dungeons"][0]
    assert gh["count"] == 2 and gh["levels"] == (18, 22) and gh["players"] == "5"
    # with no travel notes everything is a "Forever addition"
    assert [g for g, _l in wd.dungeon_list(db, {})] == ["Forever additions"]


def test_dungeon_quests(db):
    found = {qid: why for qid, _q, why in wd.dungeon_quests(db, 2)}
    assert found == {502: ["Kill Ogre Warlord"]}
    assert [qid for qid, _q, _w in wd.dungeon_quests(db, 3)] == [503]


def test_dungeon_drops_once_each_with_sources(db):
    drops = {d["name"]: d for d in wd.dungeon_drops(db, 2)}
    assert set(drops) == {"Ogre Cleaver", "Iron Helm", "Grunt Gloves"}
    assert sorted(drops["Ogre Cleaver"]["from"]) == ["Ogre Grunt", "Ogre Warlord"]


def test_unverified_report(db, use_travel):
    assert sorted(wd.unverified(db)) == [("Grim Hold", "not checked"), ("Raid Peak", "no route")]


def test_shipped_travel_notes_are_valid():
    with open(os.path.join(ROOT, "dungeon_travel.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data.get("dungeons"), dict) and data["dungeons"]
    for key, d in data["dungeons"].items():
        assert key.isdigit(), key
        assert (d.get("kind") or "") in ("", "dungeon", "raid"), key
        assert isinstance(d.get("verified", False), bool), key
        for side in ("alliance", "horde"):
            r = d.get(side)
            if r is not None:
                assert isinstance(r, dict), (key, side)
                assert all(isinstance(s, str) for s in r.get("steps") or []), (key, side)


# ---------------------------------------------------------------- loot finder

W = {"STRENGTH": 1.0, "STAMINA": 0.5, "DPS": 2.0}
MODE = wp.COMPARE_MODES[0]


def stats_file(entries):
    wp.save_json(wp.ITEM_STATS_PATH, {f"forever:{k}": v for k, v in entries.items()})


def test_dungeon_gear_only_counts_drops_from_inside(db, use_travel):
    assert wl.dungeon_gear(db) == {200: [20, 21], 202: [21], 300: [30]}     # Iron Helm also drops outside


def test_gear_of_and_not_asked():
    stats_file({200: {"inv": "WEAPON", "cls_id": 2}, 202: {"missing": True}})
    assert wl.gear_of(200)["inv"] == "WEAPON"
    assert wl.gear_of(202) is None                       # Blizzard has nothing
    assert wl.gear_of(300) is False                      # not asked yet
    assert wl.not_asked([200, 202, 300]) == [300]


def test_stats_cache_rereads_a_changed_file():
    stats_file({1: {"inv": "HEAD", "cls_id": 4}})
    assert wl.gear_of(1)
    stats_file({})
    os.utime(wp.ITEM_STATS_PATH, (time.time() + 5, time.time() + 5))
    assert wl.gear_of(1) is False


def test_rate_picks_the_slot_and_compares_with_what_you_wear():
    worn = {"slot": "HEAD", "name": "Old Cap", "inv": "HEAD", "cls_id": 4, "sub_id": 2, "ilvl": 5,
            "q": "COMMON", "stats": {"STRENGTH": 1}}
    c = char("Shaman", 20, gear=[worn])
    helm = {"inv": "HEAD", "cls_id": 4, "sub_id": 2, "ilvl": 20, "q": "RARE", "stats": {"STRENGTH": 8},
            "name": "New Cap"}
    r = wl.rate(c, helm, W, MODE)
    assert r["slot"] == "HEAD" and r["better"] and r["up_pct"] > 0 and not r["same"]
    assert wl.rate(c, dict(helm, name="Old Cap"), W, MODE)["same"]
    assert wl.rate(c, helm, W, MODE, slot="CHEST") is None
    ring = {"inv": "FINGER", "cls_id": 4, "ilvl": 20, "q": "RARE", "stats": {"STRENGTH": 3}}
    assert wl.rate(c, ring, W, MODE)["slot"] in ("FINGER_1", "FINGER_2")
    mail = dict(helm, sub_id=wp.MAIL)
    r = wl.rate(c, mail, W, MODE)
    assert not r["usable"] and not r["better"]


def test_drop_rows_scores_dungeon_gear(db, use_travel):
    stats_file({200: {"name": "Ogre Cleaver", "inv": "WEAPON", "cls_id": 2, "sub_id": wp.AXE1, "ilvl": 22,
                      "q": "UNCOMMON", "stats": {"STRENGTH": 5}, "dps": 10},
                202: {"missing": True}})
    rows, counts = wl.drop_rows(char("Shaman", 20), db, W, MODE,
                                sources=[("H", book((200, 12345, 2)))])
    assert counts == {"total": 3, "missing": 1, "unknown": 1}
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == 200 and r["slot"] == "MAIN_HAND" and r["price"] == 12345 and r["listed"] == 2
    assert r["from"] == {"Grim Hold": ["Ogre Warlord", "Ogre Grunt"]}
    assert wl.source_text(r) == "Ogre Warlord, Ogre Grunt · Grim Hold"
    assert wl.source_text(r, limit=1) == "Ogre Warlord +1 · Grim Hold"


def test_best_per_slot_limits_and_suggests_rings_once():
    def r(slot, gain, better=True):
        return {"slot": slot, "gain": gain, "better": better}
    rows = [r("HEAD", 5), r("HEAD", 4), r("HEAD", 3), r("FINGER_1", 9), r("FINGER_2", 8), r("FINGER_1", 1),
            r("CHEST", 50, better=False)]
    out = wl.best_per_slot(rows, per_slot=2)
    assert [(x["slot"], x["gain"]) for x in out] == [("FINGER_1", 9), ("FINGER_2", 8), ("HEAD", 5), ("HEAD", 4)]
