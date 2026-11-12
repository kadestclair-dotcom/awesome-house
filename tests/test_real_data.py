"""Checks against the real QuestieDB index and your saved character.

These need files that are personal and never committed (.wow_price_cache/questiedb/monster_index.json
and character_progress.json), so they run on your PC and are skipped on GitHub. Open the Monster
Compendium tab once, and load a character on the Progress tab, to make them run."""

import json
import os
import time

import pytest

import wow_dungeons as wd
import wow_loot as wl
import wow_monsters as wm
import wow_price as wp
import wow_progress as wpr
from conftest import REAL_INDEX, REAL_PROGRESS, ROOT

pytestmark = pytest.mark.realdata
needs_index = pytest.mark.skipif(not os.path.exists(REAL_INDEX), reason="no QuestieDB index on this PC yet")
needs_char = pytest.mark.skipif(not os.path.exists(REAL_PROGRESS), reason="no saved Progress character")


@pytest.fixture(scope="module")
def real():
    with open(REAL_INDEX, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def rdb(real, monkeypatch):
    monkeypatch.setattr(wd, "BUNDLED_PATH", os.path.join(ROOT, wd.SEED_NAME))
    return wm.Compendium(real)


@pytest.fixture
def real_snap():
    with open(REAL_PROGRESS, encoding="utf-8") as f:
        data = json.load(f)
    return data["chars"][data["last"]]


@needs_index
def test_index_is_current_schema(real):
    assert real["schema"] == wm.INDEX_SCHEMA, "rebuild with Update data on the Monster Compendium tab"
    assert len(real["npcs"]) > 3000 and len(real["allq"]) > 4000


@needs_index
def test_index_integrity(rdb):
    assert all(i in rdb.items for lst in rdb.drops.values() for i in lst)
    assert {len(v) for v in rdb.allq.values()} == {15}
    for n in rdb.npcs.values():
        for _z, x, y, c in n.get("p", []):
            assert 0 < x <= 100 and 0 < y <= 100 and c > 0
    missing_npcs = sum(1 for q in rdb.quests.values() for n in q.get("k", []) if n not in rdb.npcs)
    assert missing_npcs < 100                       # QuestieDB has a few dozen non-monster targets


@needs_index
def test_every_travel_note_belongs_to_a_listed_dungeon(rdb):
    listed = {d["id"] for _g, lst in wd.dungeon_list(rdb) for d in lst}
    assert listed, "no dungeons found"
    assert set(wd.load_travel()) <= listed


@needs_index
def test_dungeon_pages_build(rdb):
    for _g, lst in wd.dungeon_list(rdb):
        for d in lst:
            wd.entrances(rdb, d["id"])
            wd.dungeon_quests(rdb, d["id"])
            for drop in wd.dungeon_drops(rdb, d["id"]):
                assert drop["from"]


@needs_index
def test_compendium_pages_build_for_every_monster(rdb):
    t = time.time()
    for nid in rdb.npcs:
        rdb.level_text(nid)
        rdb.rank_text(nid)
        rdb.drops_of(nid)
        rdb.quests_for(nid)
        rdb.where(nid)
    assert time.time() - t < 10
    assert rdb.search("hogger") or rdb.search("kobold")


@needs_index
def test_loot_finder_on_real_data(rdb, monkeypatch):
    monkeypatch.setattr(wp, "ITEM_STATS_PATH", os.path.join(ROOT, "item_stats.json"))
    wl._stats[:] = [None, {}]
    gear = wl.dungeon_gear(rdb)
    assert len(gear) > 500
    c = {"name": "T", "cls": "Warrior", "level": 30, "gear": []}
    weights = next(iter(wp.STAT_PRESETS["Warrior"].values()))
    rows, counts = wl.drop_rows(c, rdb, weights, wp.COMPARE_MODES[0])
    assert counts["total"] == len(gear)
    for r in rows:
        assert r["slot"] in wp.SLOT_SEARCH and wl.source_text(r)


@needs_index
@needs_char
def test_saved_character_progress(rdb, real_snap):
    p = wpr.Progress(rdb, real_snap)
    assert p.unknown_done <= len(p.done) * 0.05, "completed quests the index doesn't know"
    zones = p.zones()
    assert zones
    rec = p.recommend(zones)
    assert rec["zone"] is not None
    for q, _z in rec["quests"]:
        assert p.state(q) == "now"


@needs_index
@needs_char
def test_saved_character_route_is_fast_and_ordered(rdb, real_snap):
    p = wpr.Progress(rdb, real_snap)
    t = time.time()
    r = p.route()
    assert time.time() - t < 2
    rank = {"get": 0, "do": 1, "end": 2}
    seen = {}
    for s in r["stops"]:
        assert 0 < s["x"] <= 100 and 0 < s["y"] <= 100
        for kind, _text, q in s["acts"]:
            assert rank[kind] >= seen.get(q, 0), f"quest {q}: {kind} came too early"
            seen[q] = rank[kind]
