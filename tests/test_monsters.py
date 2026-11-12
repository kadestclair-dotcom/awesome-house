"""Monster Compendium: the QuestieDB decoder, the loaded index and its lookups."""

import base64
import json
import os
import struct
import zlib

import pytest

import wow_monsters as wm
from conftest import FakeApi, book, tiny_index


# ---------------------------------------------------------------- a tiny CBOR writer to feed the reader

def cbor(v):
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    if v is False:
        return b"\xf4"
    if v is True:
        return b"\xf5"
    if v is None:
        return b"\xf6"
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, float):
        return b"\xfb" + struct.pack(">d", v)
    if isinstance(v, str):
        b = v.encode()
        return head(2, len(b)) + b                       # QuestieDB stores text as byte strings
    if isinstance(v, list):
        return head(4, len(v)) + b"".join(cbor(x) for x in v)
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())
    raise TypeError(v)


@pytest.mark.parametrize("value", [
    0, 23, 24, 255, 256, 70000, 2 ** 40, -1, -500, 1.5, -0.25, True, False, None, "", "Hogger",
    "Kel'Thuzad ’", [1, [2, 3], None], {1: "a", 2: [4, 5]}, {"k": {"n": 1}},
])
def test_cbor_round_trip(value):
    assert wm._cbor(cbor(value)) == value


def test_cbor_half_and_single_floats_and_tags():
    assert wm._cbor(b"\xf9\x3c\x00") == 1.0                    # half float
    assert wm._cbor(b"\xfa" + struct.pack(">f", 2.5)) == 2.5   # single float
    assert wm._cbor(b"\xc1" + cbor(7)) == 7                    # tagged value: tag ignored


def test_cbor_bad_byte():
    with pytest.raises(wm.DataError):
        wm._cbor(b"\xff")


def test_arr_lua_tables():
    assert wm._arr(None) == []
    assert wm._arr([1, None, 3]) == [1, None, 3]
    assert wm._arr({1: "a", 3: "c"}) == ["a", None, "c"]
    assert wm._arr({}) == []


def b64(v):
    return base64.b64encode(cbor(v)).decode()


def test_toc_reader():
    ids = base64.b64encode(zlib.compress(cbor([5, None, 7]))).decode()
    row = b64([None, "Hogger", 11])
    half = len(row) // 2
    toc = wm._Toc("\n".join([
        "## Title: QuestieDB", "## X-NPC-IDS: " + ids,
        "## X-NPC-5-S: ~2~", "## X-NPC-5-S-1: " + row[:half], "## X-NPC-5-S-2: " + row[half:],
        "## X-NPC-5-2: " + b64("field two"), "## X-NPC-7-S: " + b64({"p": 1, "n": "x"})]))
    assert toc.ids("NPC") == [5, 7]
    assert toc.row("NPC", 5) == {2: "Hogger", 3: 11}
    assert toc.row("NPC", 9) == {}
    assert toc.field("NPC", 5, 2) == "field two"
    assert toc.field("NPC", 5, 3) is None
    assert toc.field("NPC", 7, 2, row={"p": 1}) is None          # presence bit 2 not set: skipped


def test_toc_ids_raw_deflate():
    c = zlib.compressobj(wbits=-15)
    raw = c.compress(cbor([1, 2])) + c.flush()
    toc = wm._Toc("## X-ITEM-IDS: " + base64.b64encode(raw).decode())
    assert toc.ids("ITEM") == [1, 2]


# ---------------------------------------------------------------- small helpers

def test_way():
    assert wm.way("Elwynn Forest", 42.0, 65.5, "Hogger") == "/way Elwynn Forest 42 65.5 Hogger"
    assert wm.way("Duskwood", 10.25, 5, "") == "/way Duskwood 10.25 5"


@pytest.mark.parametrize("mask, side", [
    (1, "A"), (4 | 8, "A"), (2, "H"), (16 | 128, "H"), (1 | 2, ""), (0, ""), (None, ""),
    (1 << 32, ""), ((1 << 33) | 2, "H"),        # Forever's Skyborne bits don't pick a side
])
def test_faction(mask, side):
    assert wm._faction(mask) == side


def test_spots_picks_the_busiest_point_per_zone():
    spawns = {"1": [[10, 10], [11, 11], [10.5, 10.2], [80, 80]], "2": [[-1, -1]], "x": [[5, 5]],
              "3": {1: [20, 30]}}
    out = wm._spots(spawns, lambda z: z)
    assert out[0][0] == 1 and out[0][3] == 4 and abs(out[0][1] - 10.5) < 1
    assert [o[0] for o in out] == [1, 3]                     # dungeon (-1,-1) and bad keys dropped


def test_spots_merges_subzones_into_their_zone():
    out = wm._spots({"101": [[1, 1]], "102": [[2, 2]]}, lambda z: 1)
    assert out == [[1, 1.0, 1.0, 2]] or out[0][3] == 2


# ---------------------------------------------------------------- the Compendium

def test_regions_and_groups(db):
    assert db.group_of(1) == "Kalimdor"
    assert db.group_of(2) == db.group_of(3) == "Dungeons and raids"
    assert db.group_of(616) == "Forever: new areas"
    assert db.group_of(2597) == "Battlegrounds"
    assert db.group_of(12345) == "Other"
    groups = [g for g, _z in db.regions()]
    assert groups == ["Kalimdor", "Forever: new areas", "Dungeons and raids", "Battlegrounds"]
    assert db.zone_name(1) == "Testlands" and db.zone_name(9) == "Area 9"


def test_monster_lookups(db):
    assert db.monsters_in(1) == [10, 11]
    assert db.search("boar") == [10]
    assert db.search("10")[0] == 10                           # an id works too
    assert db.search("   ") == []
    assert db.search("o")[:2] == [21, 20]                     # names starting with it first
    assert db.find_by_drop("cleaver") == [21, 20]                # sorted by monster name
    assert db.find_by_drop("") == []
    assert db.where(10) == [("Testlands", 50.0, 50.0, 20)]
    assert db.main_zone(10) == 1


def test_level_and_rank_text(db):
    assert db.level_text(10) == "5-6"
    assert db.level_text(22) == "??"
    assert db.rank_text(20) == "Elite" and db.rank_text(10) == ""


def test_drops_quest_items_first(db):
    drops = db.drops_of(10)
    assert [d["name"] for d in drops] == ["Boar Meat", "Linen Cloth"]
    assert drops[0]["cls"] == "Quest" and drops[0]["rate"] == 40.0


def test_quests_for_a_monster(db):
    found = [(qid, why) for qid, _q, why in db.quests_for(10)]
    assert found == [(500, "Kill"), (501, "Collect Boar Meat")]
    assert [(qid, why) for qid, _q, why in db.quests_for(30)] == [(503, "Dragon Scale Vest starts it")]


def test_quest_spot(db):
    assert db.quest_spot(501) == ("Testlands", 40.0, 40.0)
    assert db.quest_spot(501, end=True) == ("Testlands", 45.0, 45.0)
    assert db.quest_spot(503) is None and db.quest_spot(99999) is None


# ---------------------------------------------------------------- loading, updates, tracking

def write_index(idx):
    os.makedirs(wm.DATA_DIR, exist_ok=True)
    with open(wm.INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(idx, f, separators=(",", ":"))


def test_load_saved_index_without_network():
    write_index(tiny_index())
    db = wm.load(progress=lambda *_: None)
    assert db.version == "9.9.9" and len(db.npcs) == 7
    assert wm.index_info()[0] == "9.9.9"


def test_old_index_schema_is_rebuilt_and_offline_fails_politely():
    old = tiny_index()
    old["schema"] = wm.INDEX_SCHEMA - 1
    write_index(old)
    with pytest.raises(wm.DataError, match="internet"):
        wm.load(progress=lambda *_: None)


def test_index_info_without_index():
    assert wm.index_info() == (None, None)


def test_latest_version_offline_is_none():
    assert wm.latest_version() is None


def test_newer_release(monkeypatch):
    monkeypatch.setattr(wm, "index_info", lambda: ("1.0.13", 0))
    monkeypatch.setattr(wm, "latest_version", lambda: "1.0.14")
    assert wm.newer_release() == "1.0.14"
    monkeypatch.setattr(wm, "latest_version", lambda: "1.0.13")
    assert wm.newer_release() is None
    monkeypatch.setattr(wm, "latest_version", lambda: None)
    assert wm.newer_release() is None


def test_newer_release_never_offers_an_older_version(monkeypatch):
    monkeypatch.setattr(wm, "index_info", lambda: ("1.0.14", 0))
    monkeypatch.setattr(wm, "latest_version", lambda: "1.0.13")
    assert wm.newer_release() is None


def test_newer_release_compares_numbers_not_text(monkeypatch):
    # "1.0.10" sorts before "1.0.9" as text; as numbers it is newer
    monkeypatch.setattr(wm, "index_info", lambda: ("1.0.9", 0))
    monkeypatch.setattr(wm, "latest_version", lambda: "1.0.10")
    assert wm.newer_release() == "1.0.10"
    monkeypatch.setattr(wm, "index_info", lambda: ("1.0.10", 0))
    monkeypatch.setattr(wm, "latest_version", lambda: "1.0.9")
    assert wm.newer_release() is None


def test_newer_release_unreadable_version_is_never_an_update(monkeypatch):
    monkeypatch.setattr(wm, "index_info", lambda: ("1.0.14", 0))
    monkeypatch.setattr(wm, "latest_version", lambda: "nightly")
    assert wm.newer_release() is None
    monkeypatch.setattr(wm, "index_info", lambda: (None, None))
    monkeypatch.setattr(wm, "latest_version", lambda: "1.0.14")
    assert wm.newer_release() is None


def test_version_tuple():
    assert wm.version_tuple("1.0.14") == (1, 0, 14)
    assert wm.version_tuple("v1.0.14") == (1, 0, 14)
    assert wm.version_tuple("1.0") < wm.version_tuple("1.0.1")
    assert wm.version_tuple("") is None and wm.version_tuple(None) is None
    assert wm.version_tuple("nightly") is None


def test_zip_urls_prefer_the_asset_github_named():
    wm._asset_urls["1.2.3"] = "https://example/asset.zip"
    urls = wm._zip_urls("1.2.3")
    assert urls[0] == "https://example/asset.zip" and len(urls) == 3
    assert all("1.2.3" in u for u in urls[1:])


def test_tracking_round_trip():
    assert wm.load_tracking() == []
    wm.save_tracking([{"id": 10, "kills": 3, "note": "boars"}])
    assert wm.load_tracking() == [{"id": 10, "kills": 3, "note": "boars"}]
    wm.save_tracking({"not": "a list"})
    assert wm.load_tracking() == []


def test_price_drops(monkeypatch):
    import wow_price as wp
    monkeypatch.setattr(wp, "get_sources", lambda api, realm=None: [("H", book((100, 50, 3)))])
    out = wm.price_drops(FakeApi(), [100, 101])
    assert out[100]["lowest"] == 50 and out[101] is None


# ---------------------------------------------------------------- updating the QuestieDB data safely

def _zip_bytes(files):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def old_data(monkeypatch):
    """Monster data already on the PC: an old zip and a built index."""
    os.makedirs(wm.DATA_DIR, exist_ok=True)
    with open(wm.ZIP_PATH, "wb") as f:
        f.write(b"OLD ZIP")
    with open(wm.INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(tiny_index(), f)
    monkeypatch.setattr(wm, "latest_version", lambda: "2.0.0")
    with open(wm.INDEX_PATH, "rb") as f:
        return f.read()


def test_an_update_in_an_unknown_layout_keeps_the_old_data(old_data, monkeypatch):
    new = _zip_bytes({"QuestieDB/QuestieDB_Forever.toc": "## Version: 2.0.0\n## X-Something: new"})
    monkeypatch.setattr(wm, "_get", lambda url, timeout=60: (url, new))
    with pytest.raises(wm.DataError) as e:
        wm.load(progress=lambda m: None, update=True)
    assert "doesn't understand" in str(e.value) and "kept" in str(e.value)
    with open(wm.ZIP_PATH, "rb") as f:
        assert f.read() == b"OLD ZIP"                       # the old download is still there
    with open(wm.INDEX_PATH, "rb") as f:
        assert f.read() == old_data                         # and so is the old index
    assert not [n for n in os.listdir(wm.DATA_DIR) if n.endswith((".new", ".part", ".tmp"))]


def test_a_good_update_replaces_the_old_zip(old_data, monkeypatch):
    new = _zip_bytes({"QuestieDB/QuestieDB_Forever.toc": "## Version: 2.0.0"})
    monkeypatch.setattr(wm, "_get", lambda url, timeout=60: (url, new))
    built = []

    def fake_build(version=None, progress=print, zip_path=None):
        with open(zip_path, "rb") as f:
            built.append(f.read())
        return tiny_index()
    monkeypatch.setattr(wm, "build_index", fake_build)
    wm.load(progress=lambda m: None, update=True)
    assert built == [new]
    with open(wm.ZIP_PATH, "rb") as f:
        assert f.read() == new
    assert not [n for n in os.listdir(wm.DATA_DIR) if n.endswith((".new", ".part", ".tmp"))]
