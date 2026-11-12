"""
Shared test setup for Awesome House.

Every test runs in a sandbox:
  * all of the app's data files (config, watchlist, price history, caches...) are pointed at a
    fresh temporary folder, so your real key and data in the app folder are never read or changed;
  * the network is blocked, so nothing talks to Blizzard or GitHub;
  * the in-memory caches the modules keep between calls are emptied.

Blizzard is replaced by FakeApi: give it a dict of {path: answer} and it serves those answers.
"""

import copy
import json
import os
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import wow_price as wp          # noqa: E402
import wow_monsters as wm       # noqa: E402
import wow_dungeons as wd       # noqa: E402
import wow_loot as wl           # noqa: E402
import wow_progress as wpr      # noqa: E402

REAL_HERE = wp.HERE
MODULES = [wp, wm, wd, wl, wpr]
REAL_INDEX = os.path.join(ROOT, ".wow_price_cache", "questiedb", "monster_index.json")
REAL_PROGRESS = os.path.join(ROOT, "character_progress.json")


def _repoint(mod, home, monkeypatch):
    """Point every UPPERCASE path constant that lives under the app folder into the sandbox."""
    for name, val in list(vars(mod).items()):
        if name.isupper() and isinstance(val, str) and val.startswith(REAL_HERE):
            monkeypatch.setattr(mod, name, home + val[len(REAL_HERE):])


def _block_network(*_a, **_k):
    raise OSError("network is blocked in tests")


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    home = str(tmp_path / "app")
    os.makedirs(home)
    mods = MODULES + [m for m in (sys.modules.get("wow_price_gui"),) if m]
    for mod in mods:
        _repoint(mod, home, monkeypatch)
    # like the packaged exe: bundled files in their own folder, separate from the user's copies
    bundle = os.path.join(home, "_bundle")
    os.makedirs(bundle)
    monkeypatch.setattr(wp, "BUNDLE_DIR", bundle)
    monkeypatch.setattr(wd, "BUNDLED_PATH", os.path.join(bundle, wd.SEED_NAME))
    os.makedirs(wp.CACHE_DIR, exist_ok=True)
    monkeypatch.delenv("BLIZZARD_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLIZZARD_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", _block_network)
    # in-memory caches
    monkeypatch.setattr(wp, "_info", None)
    wp._forever_memo.clear()
    wp._partial_memo.clear()
    wp._houses.clear()
    wp._summary_memo[:] = [None, {}]
    monkeypatch.setattr(wd, "_travel", None)
    monkeypatch.setattr(wd, "_stamp", None)
    wl._stats[:] = [None, {}]
    monkeypatch.setattr(wpr, "_qinfo", None)
    monkeypatch.setattr(wm, "_loaded", None)
    wm._asset_urls.clear()
    yield home
    wp._forever_memo.clear()
    wp._partial_memo.clear()
    wp._houses.clear()
    wp._summary_memo[:] = [None, {}]


# ---------------------------------------------------------------- fake Blizzard

class FakeApi(wp.Blizz):
    """wow_price.Blizz with get() answered from a table instead of the internet.

    routes: {path: answer}. An answer can be data, an exception to raise, or a function
    taking the query params (dict) and returning either. Unknown paths raise ApiError 404."""

    def __init__(self, routes=None, game="forever", region="us"):
        super().__init__("test-token", region, game)
        self.routes = dict(routes or {})
        self.calls = []
        self.gear_ids = set()

    def get(self, path, kind, **params):
        self.calls.append((path, kind, params))
        ans = self.routes.get(path)
        if ans is None:
            raise wp.ApiError(404, f"no fake answer for {path}")
        if callable(ans):
            ans = ans(params)
        if isinstance(ans, BaseException):
            raise ans
        return copy.deepcopy(ans)

    def paths(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def fake_api(monkeypatch):
    """A FakeApi that wp.connect() also returns (used by Progress, quest info, guild...)."""
    api = FakeApi()
    monkeypatch.setattr(wp, "connect", lambda game="forever", region="us": api)
    return api


def book(*pairs):
    """{item id: [(price, qty), ...]} from (item id, price, qty) triples."""
    out = {}
    for iid, price, qty in pairs:
        out.setdefault(iid, []).append((price, qty))
    return out


@pytest.fixture
def use_sources(monkeypatch):
    """use_sources([("House", book(...)), ...]) makes get_sources() return them."""
    def setter(sources):
        monkeypatch.setattr(wp, "get_sources", lambda api, realm=None: sources)
        return sources
    return setter


def know_item(item_id, name, game="forever", **extra):
    """Teach the app an item name, as if it had seen it before (no search needed)."""
    wp.remember_info(game, item_id, {"name": name, **extra}, save=False)


# ---------------------------------------------------------------- a tiny monster database

#  zone 1  Testlands (Kalimdor)        boar 10, wolf 11
#  zone 2  Grim Hold (dungeon)         ogre boss 20, ogre grunt 21
#  zone 3  Raid Peak (raid)            skull-level boss 22, dragon 30
Q = dict(N=0, LV=1, RL=2, FA=3, ZONE=4, CLS=5, PRE_ONE=6, PRE_ALL=7, EXCL=8, REPEAT=9, GIVER=10, ENDER=11,
         TEXT=12)


def q(name, lv, rl, zone, fa="", cls=0, pre_one=(), pre_all=(), excl=(), repeat=0, giver="", ender="",
      text="", start=0, end=0):
    return [name, lv, rl, fa, zone, cls, list(pre_one), list(pre_all), list(excl), repeat, giver, ender, text,
            start, end]


def tiny_index():
    return {
        "schema": wm.INDEX_SCHEMA, "version": "9.9.9", "built": int(time.time()),
        "zones": {"1": {"n": "Testlands", "g": "Kalimdor"},
                  "2": {"n": "Grim Hold", "g": "Dungeons"},
                  "3": {"n": "Raid Peak", "g": "Raids"},
                  "616": {"n": "Mount Hyjal", "g": "Forever"},
                  "2597": {"n": "Alterac Valley", "g": "Battlegrounds"}},
        "npcs": {
            "10": {"n": "Testlands Boar", "l": [5, 6], "r": 0, "z": {"1": 20}, "p": [[1, 50.0, 50.0, 20]]},
            "11": {"n": "Grey Wolf", "l": [6, 7], "r": 0, "z": {"1": 10}, "p": [[1, 60.0, 40.0, 10]]},
            "20": {"n": "Ogre Warlord", "l": [20, 22], "r": 1, "z": {"2": 1}, "p": []},
            "21": {"n": "Ogre Grunt", "l": [18, 19], "r": 0, "z": {"2": 12}, "p": []},
            "22": {"n": "Skull Horror", "l": [9999, 9999], "r": 3, "z": {"3": 1}, "p": []},
            "30": {"n": "Peak Dragon", "l": [60, 63], "r": 3, "z": {"3": 1}, "p": []},
            "40": {"n": "Hyjal Spirit", "l": [58, 60], "r": 4, "z": {"616": 2}, "p": [[616, 20.0, 20.0, 2]]},
        },
        "drops": {"10": [100, 101], "11": [201], "20": [200, 201], "21": [200, 202], "30": [300]},
        "items": {
            "100": {"n": "Boar Meat", "c": 12, "rate": {"10": 40.0}},
            "101": {"n": "Linen Cloth", "c": 7},
            "200": {"n": "Ogre Cleaver", "c": 2, "il": 22, "rl": 17},
            "201": {"n": "Iron Helm", "c": 4, "il": 20},
            "202": {"n": "Grunt Gloves", "c": 4, "il": 19},
            "300": {"n": "Dragon Scale Vest", "c": 4, "il": 66, "sq": 503},
        },
        "quests": {
            "500": {"n": "Boar Hunt", "lv": 5, "z": 1, "k": [10]},
            "501": {"n": "Meat Run", "lv": 6, "z": 1, "c": [100]},
            "502": {"n": "Ogre Trouble", "lv": 20, "z": 2, "k": [20]},
            "503": {"n": "Scale of the Peak", "lv": 60, "z": 3},
            "509": {"n": "Wolf Cull", "lv": 7, "z": 1, "k": [11]},
        },
        "dungeons": {"2": {"n": "Grim Hold", "alt": [], "p": "Testlands",
                           "e": [["Testlands", 30.0, 30.0, ""]]},
                     "4": {"n": "Grim Hold", "alt": [], "p": "Testlands",
                           "e": [["Testlands", 30.2, 30.3, "side door"], ["Testlands", 80.0, 20.0, "back"]]},
                     "3": {"n": "Raid Peak", "alt": [], "p": "Testlands", "e": [["Testlands", 70.0, 70.0, ""]]}},
        "allq": {
            "500": q("Boar Hunt", 5, 3, 1, giver="Farmer Ann", ender="Farmer Ann",
                     start=[1, 40.0, 40.0], end=[1, 40.0, 40.0]),
            "501": q("Meat Run", 6, 4, 1, pre_one=[500], giver="Farmer Ann", ender="Cook Bo",
                     start=[1, 40.0, 40.0], end=[1, 45.0, 45.0]),
            "502": q("Ogre Trouble", 20, 18, 2, start=[1, 31.0, 31.0], end=[1, 31.0, 31.0]),
            "503": q("Scale of the Peak", 60, 58, 3),
            "504": q("Old Chores", 2, 1, 1, start=[1, 40.0, 40.0], end=[1, 40.0, 40.0]),
            "505": q("For the Alliance", 7, 5, 1, fa="A"),
            "506": q("Warrior Training", 7, 5, 1, cls=1),
            "507": q("The Other Path", 7, 5, 1, excl=[500]),
            "508": q("Second Step", 7, 5, 1, pre_all=[509]),
            "509": q("Wolf Cull", 7, 5, 1, giver="Hunter Cy", ender="Hunter Cy",
                     start=[1, 62.0, 42.0], end=[1, 62.0, 42.0]),
            "510": q("Active One", 7, 5, 1, start=[1, 40.0, 40.0], end=[1, 41.0, 41.0]),
            "511": q("Daily Chores", 7, 5, 1, repeat=1),
            "512": q("Click the Shrine", 7, 5, 1, text="Pray at the shrine.", start=[1, 70.0, 70.0],
                     end=[1, 70.5, 70.5]),
            "513": q("Far Away", 7, 5, 1, start=[616, 20.0, 20.0], end=[616, 20.0, 20.0]),
        },
        "qzones": {"1": "Testlands", "2": "Grim Hold", "3": "Raid Peak", "616": "Mount Hyjal"},
    }


@pytest.fixture
def db():
    return wm.Compendium(json.loads(json.dumps(tiny_index())))


@pytest.fixture
def travel():
    return {2: {"name": "Grim Hold", "kind": "dungeon", "players": "5",
                "horde": {"flight": "Crossroads", "steps": ["Fly to the Crossroads", "Run south", "  "]},
                "verified": False},
            3: {"name": "Raid Peak", "kind": "raid", "players": "40"}}


@pytest.fixture
def use_travel(travel):
    """Write the travel notes as the user's own dungeon_travel.json."""
    wp.save_json(wd.USER_PATH, {"dungeons": {str(k): v for k, v in travel.items()}})
    return travel


def snapshot(**over):
    """A level 8 Horde shaman who has done Boar Hunt and has Active One in the log."""
    s = {"name": "Testy", "surname": "Mc", "level": 8, "cls": "Shaman", "cls_id": 7, "race": "Orc",
         "faction": "H", "guild": "", "guild_slug": "", "fetched": 1000, "missing": [],
         "completed": [500], "in_progress": [[510, "Active One"]],
         "achievements": [{"name": "Explorer", "id": 1, "done": False, "amount": 3, "ts": 0},
                          {"name": "Level 10", "id": 2, "done": True, "amount": 0, "ts": 5}],
         "reputations": [{"name": "Orgrimmar", "standing": "Friendly", "value": 4000, "max": 6000},
                         {"name": "Booty Bay", "standing": "Neutral", "value": 100, "max": 3000}],
         "professions": [{"name": "Herbalism", "primary": True, "skill": 40, "max": 75, "recipes": 0}],
         "pvp": {}, "dungeons": [], "raids": [], "stats": [], "points": 0}
    s.update(over)
    return s


def char(cls="Shaman", level=20, gear=()):
    return {"name": "Testy", "cls": cls, "level": level, "gear": list(gear)}
