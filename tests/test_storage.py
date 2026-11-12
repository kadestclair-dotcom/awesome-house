"""Saving files safely: a crash or a damaged file must never cost the user their data.

* Every save writes a temporary file next to the real one and swaps it in, so a crash mid-save
  leaves the previous version whole.
* User data files (watchlist, fishing log, characters, recipes, spots, guide progress, tracking
  list, Progress snapshots) keep the previous good version as <name>.bak.
* A file that can't be read is kept as <name>.corrupt-<time> (never overwritten) and the .bak is
  used instead; caches just start over.
* Saved files keep exactly the format older versions wrote.
"""

import glob
import json
import os

import pytest

import wow_price as wp
import wow_monsters as wm
import wow_progress as wpr
from conftest import FakeApi

ORE = {"id": 2770, "name": "Copper Ore"}
CLOTH = {"id": 2589, "name": "Linen Cloth"}


def damage(path, text='[{"id": 2770, "name": "Cop'):
    with open(path, "w") as f:
        f.write(text)


def leftovers(folder):
    return [p for p in os.listdir(folder) if p.endswith(".tmp")]


# ---------------------------------------------------------------- atomic save

def test_saves_keep_the_old_file_format():
    wp.save_watchlist([ORE])
    with open(wp.WATCHLIST_PATH) as f:
        assert f.read() == json.dumps([ORE], indent=2)
    path = os.path.join(wp.HERE, "recipes.json")
    wp.save_json(path, [{"name": "x"}])
    with open(path) as f:
        assert f.read() == json.dumps([{"name": "x"}], indent=1)


def test_failed_save_leaves_the_previous_file_whole(monkeypatch):
    wp.save_watchlist([ORE])

    def broken_disk(_fd):
        raise OSError("disk full")
    with monkeypatch.context() as m:
        m.setattr(os, "fsync", broken_disk)
        with pytest.raises(OSError):
            wp.save_watchlist([ORE, CLOTH])
    assert wp.load_watchlist() == [ORE]
    assert leftovers(wp.HERE) == []


def test_save_retries_while_windows_holds_the_file(monkeypatch):
    real, tries = os.replace, []

    def busy_then_free(src, dst):
        tries.append(dst)
        if len(tries) < 3:
            raise PermissionError(13, "file in use by another process")
        real(src, dst)
    with monkeypatch.context() as m:
        m.setattr(os, "replace", busy_then_free)
        m.setattr(wp.time, "sleep", lambda s: None)
        wp.save_watchlist([ORE])
    assert len(tries) == 3 and wp.load_watchlist() == [ORE]
    assert leftovers(wp.HERE) == []


def test_every_writer_goes_through_the_safe_save(monkeypatch):
    """No module writes JSON straight into its target file any more."""
    seen = []
    real = wp.atomic_write_bytes
    monkeypatch.setattr(wp, "atomic_write_bytes", lambda path, data, **k: (seen.append(os.path.basename(path)),
                                                                           real(path, data, **k)))
    wp.save_watchlist([ORE])
    wp.save_session({"spot": "x", "items": []})
    wp.save_credentials("id", "secret")
    wp.remember_info("forever", 1, {"name": "Thing"})
    wp.save_progress({"Mining": 3})
    wp.remember_character({"name": "A", "game": "forever"})
    wm.save_tracking([{"id": 1}])
    wpr.save({"name": "A", "surname": "B", "fetched": 1})
    api = FakeApi({"/x": {"ok": 1}})
    api.cached("probe", lambda: {"ok": 1})
    for name in ("watchlist.json", "fishing_sessions.json", "wow_price_config.json", "item_info.json",
                 "guide_progress.json", "characters.json", "monster_tracking.json", "character_progress.json",
                 "forever_us_probe.json"):
        assert name in seen, name


# ---------------------------------------------------------------- backups and damaged files

def test_user_data_keeps_the_previous_version_as_bak():
    wp.save_watchlist([ORE])
    wp.save_watchlist([ORE, CLOTH])
    with open(wp.WATCHLIST_PATH + ".bak") as f:
        assert json.load(f) == [ORE]


def test_caches_get_no_backup():
    wp.save_json(wp.ITEM_STATS_PATH, {"forever:1": {"missing": True}})
    wp.save_json(wp.ITEM_STATS_PATH, {"forever:1": {"missing": True}, "forever:2": {"missing": True}})
    assert not os.path.exists(wp.ITEM_STATS_PATH + ".bak")


def test_damaged_watchlist_is_kept_and_not_wiped():
    damage(wp.WATCHLIST_PATH)
    assert wp.load_watchlist() == []
    wp.save_watchlist([CLOTH])                      # the next save must not destroy the damaged copy
    kept = glob.glob(wp.WATCHLIST_PATH + ".corrupt-*")
    assert len(kept) == 1
    with open(kept[0]) as f:
        assert f.read() == '[{"id": 2770, "name": "Cop'


def test_damaged_watchlist_comes_back_from_the_backup():
    wp.save_watchlist([ORE])
    wp.save_watchlist([ORE, CLOTH])                 # .bak now holds [ORE]
    damage(wp.WATCHLIST_PATH)
    assert wp.load_watchlist() == [ORE]
    with open(wp.WATCHLIST_PATH) as f:              # the good copy is back in place
        assert json.load(f) == [ORE]
    assert len(glob.glob(wp.WATCHLIST_PATH + ".corrupt-*")) == 1


def test_a_deleted_file_is_not_brought_back_from_the_backup():
    wp.save_watchlist([ORE])
    wp.save_watchlist([ORE, CLOTH])
    os.remove(wp.WATCHLIST_PATH)                    # the user removed it on purpose
    assert wp.load_watchlist() == []


@pytest.mark.parametrize("save, load, good", [
    (lambda d: wp.save_session(d), wp.load_sessions, {"spot": "Pier", "items": []}),
    (lambda d: wm.save_tracking([d]), wm.load_tracking, {"id": 7, "kills": 3}),
    (lambda d: wp.save_progress(d), wp.load_progress, {"Mining": 12}),
])
def test_every_user_file_recovers_from_damage(save, load, good):
    save(good)
    first = load()
    save(good)                                      # second save: .bak holds the first
    paths = {wp.SESSIONS_PATH, wm.TRACK_PATH, wp.PROGRESS_PATH}
    path = next(p for p in paths if os.path.exists(p + ".bak"))
    damage(path, "{not json")
    assert load() == first


def test_damaged_progress_snapshots_recover():
    wpr.save({"name": "A", "surname": "B", "fetched": 1})
    wpr.save({"name": "C", "surname": "D", "fetched": 2})
    damage(wpr.PROGRESS_PATH, '{"chars": {')
    assert list(wpr.load_saved()["chars"]) == ["a b"]


def test_damaged_item_cache_is_set_aside_and_rebuilt():
    damage(wp.ITEM_CACHE_PATH, '{"forever:copper ore": {"id": 27')
    api = FakeApi({"/data/wow/search/item": {"results": [
        {"data": {"id": 2770, "name": {"en_US": "Copper Ore"}}}]}})
    assert wp.resolve_cached(api, "Copper Ore") == ORE
    with open(wp.ITEM_CACHE_PATH) as f:
        saved = json.load(f)["forever:copper ore"]
    assert saved["id"] == ORE["id"] and saved["name"] == ORE["name"]
    assert len(glob.glob(wp.ITEM_CACHE_PATH + ".corrupt-*")) == 1


def test_damaged_auction_snapshot_is_downloaded_again():
    api = FakeApi()
    api.cached("probe", lambda: {"v": 1})
    path = os.path.join(wp.CACHE_DIR, "forever_us_probe.json")
    damage(path, '{"v": ')
    assert api.cached("probe", lambda: {"v": 2}) == {"v": 2}
    with open(path) as f:
        assert json.load(f) == {"v": 2}
