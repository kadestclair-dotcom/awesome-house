"""Blizzard Developer API Terms 2.18: data from Blizzard's API is kept for at most 30 days.

Everything the app stores from Blizzard carries the time it was fetched; enforce_data_ttl() deletes what
is older (it is fetched again when needed). Records without a time stamp come from older versions and
count as old. The user's own lists (watchlist, alerts, fishing log, recipes, spots, guide progress,
tracking list) are their records, not cached API data, and are left alone."""

import json
import os
import time

import wow_price as wp
import wow_progress as wpr
from conftest import FakeApi

NOW = time.time()
OLD = NOW - wp.DATA_TTL - 3600
RECENT = NOW - 3600


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def load(path):
    with open(path) as f:
        return json.load(f)


def test_the_limit_is_thirty_days():
    assert wp.DATA_TTL == 30 * 86400


def test_price_history_keeps_thirty_days():
    rows = [{"id": 1, "found": True, "lowest": 10, "cheap10": 12, "quantity": 3}]
    wp.record_history("forever", int(OLD), rows)
    wp.record_history("forever", int(RECENT), rows)
    wp.enforce_data_ttl()
    assert [r[0] for r in wp.price_history("forever", 1, 0)] == [int(RECENT)]


def test_recording_history_also_drops_old_points():
    rows = [{"id": 1, "found": True, "lowest": 10, "cheap10": 12, "quantity": 3}]
    wp.record_history("forever", int(OLD), rows)
    wp.record_history("forever", int(NOW), rows)
    assert [r[0] for r in wp.price_history("forever", 1, 0)] == [int(NOW)]


def test_item_names_are_stamped_and_expire():
    wp.remember_info("forever", 1, {"name": "Fresh"})
    assert abs(wp.cached_info("forever", 1)["at"] - NOW) < 60
    write(wp.ITEM_INFO_PATH, {"forever:1": {"name": "Fresh", "at": RECENT},
                              "forever:2": {"name": "Stale", "at": OLD},
                              "forever:3": {"name": "Unstamped (older version)"}})
    wp._info = None
    wp.enforce_data_ttl()
    assert set(load(wp.ITEM_INFO_PATH)) == {"forever:1"}
    assert wp.cached_info("forever", 2) == {}                       # the in-memory copy forgot it too


def test_item_stats_expire_and_are_fetched_again():
    write(wp.ITEM_STATS_PATH, {"forever:5": {"missing": True, "at": OLD}, "forever:6": {"missing": True}})
    wp.enforce_data_ttl()
    assert load(wp.ITEM_STATS_PATH) == {}
    api = FakeApi({"/data/wow/item/5": wp.ApiError(404, "gone")})
    cache = wp.fetch_items(api, [5])
    assert cache["forever:5"]["missing"] and abs(cache["forever:5"]["at"] - NOW) < 60


def test_item_name_lookups_expire_but_answers_look_the_same():
    write(wp.ITEM_CACHE_PATH, {"forever:copper ore": {"id": 2770, "name": "Copper Ore", "at": RECENT},
                               "forever:linen cloth": {"id": 2589, "name": "Linen Cloth"}})
    wp.enforce_data_ttl()
    assert set(load(wp.ITEM_CACHE_PATH)) == {"forever:copper ore"}
    assert wp.resolve_cached(FakeApi(), "Copper Ore") == {"id": 2770, "name": "Copper Ore"}


def test_recent_character_lookups_expire():
    wp.remember_character({"name": "New", "surname": "One", "realm": "", "game": "forever"})
    chars = wp.load_characters()
    write(wp.CHARACTERS_PATH, chars + [{"name": "Old", "surname": "Two", "realm": "", "game": "forever", "at": OLD},
                                       {"name": "Unstamped", "realm": "", "game": "forever"}])
    wp.enforce_data_ttl()
    assert [c["name"] for c in wp.load_characters()] == ["New"]


def test_saved_progress_snapshots_expire():
    wpr.save({"name": "Fresh", "surname": "A", "fetched": int(RECENT)})
    wpr.save({"name": "Stale", "surname": "B", "fetched": int(OLD)})
    wpr.enforce_data_ttl()
    saved = wpr.load_saved()
    assert list(saved["chars"]) == ["fresh a"] and saved["last"] == "fresh a"


def test_quest_text_expires_and_answers_look_the_same(fake_api):
    fake_api.routes["/data/wow/quest/7"] = {"description": {"en_US": "Kill boars."}}
    info = wpr.quest_info(7)
    assert info["desc"] == "Kill boars." and "at" not in info
    data = load(wpr.QINFO_PATH)
    data["8"] = {"desc": "Old text", "at": OLD}
    data["9"] = {"desc": "Unstamped"}
    write(wpr.QINFO_PATH, data)
    wpr.enforce_data_ttl()
    assert set(load(wpr.QINFO_PATH)) == {"7"}
    assert wpr.quest_info(7)["desc"] == "Kill boars."


def test_old_cache_files_are_deleted():
    old_files = ["forever_us_forever_all_houses_v4.json", "forever_guild_some-guild.json", "retail_us_area-52.json"]
    keep = ["token.json", "forever_us_forever_all_houses_v5.json"]
    for name in old_files + keep:
        write(os.path.join(wp.CACHE_DIR, name), {"x": 1})
    for name in old_files + ["token.json"]:
        os.utime(os.path.join(wp.CACHE_DIR, name), (OLD, OLD))
    os.makedirs(os.path.join(wp.CACHE_DIR, "questiedb"), exist_ok=True)
    wp.enforce_data_ttl()
    left = set(os.listdir(wp.CACHE_DIR))
    assert not left & set(old_files)
    assert set(keep) <= left and "questiedb" in left                 # token and QuestieDB aren't API data


def test_the_users_own_records_are_left_alone():
    wp.save_watchlist([{"id": 2770, "name": "Copper Ore", "alert_below": 50}])
    wp.save_session({"spot": "Pier", "items": [{"name": "Raw Brilliant Smallfish", "qty": 3, "each": 5}]})
    for p in (wp.WATCHLIST_PATH, wp.SESSIONS_PATH):
        os.utime(p, (OLD, OLD))
    wp.enforce_data_ttl()
    assert wp.load_watchlist()[0]["name"] == "Copper Ore" and len(wp.load_sessions()) == 1
