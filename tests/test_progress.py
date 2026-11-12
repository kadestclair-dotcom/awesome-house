"""Progress tab: reading a character from Blizzard, quest states, zones, what to do next,
Tonight's route and the guild crafters directory."""

import json
import os

import pytest

import wow_price as wp
import wow_progress as wpr
from conftest import snapshot


# ---------------------------------------------------------------- the Classic gray-quest rule

@pytest.mark.parametrize("level, gray", [(1, 0), (5, 0), (6, 1), (9, 4), (10, 4), (20, 13), (39, 31),
                                         (40, 31), (50, 39), (59, 47), (60, 51)])
def test_gray_level(level, gray):
    assert wpr.gray_level(level) == gray


# ---------------------------------------------------------------- fetching a character

BASE = "/profile/wow/character/testy-mc"


def profile_routes():
    return {
        BASE: {"name": "Testy", "surname": "Mc", "level": 8, "experience": 99,
               "character_class": {"id": 7, "name": "Shaman"}, "race": {"name": "Orc"},
               "faction": {"type": "HORDE", "name": "Horde"},
               "guild": {"name": "Example Guild", "slug": "example-guild"}},
        BASE + "/quests": {"in_progress": [{"id": 510, "name": "Active One"}, "junk"]},
        BASE + "/quests/completed": {"quests": [{"id": 500}, {"id": 500}, {"name": "no id"}]},
        BASE + "/achievements": {"total_points": 10, "achievements": [
            {"id": 1, "achievement": {"name": "Explorer"},
             "criteria": {"is_completed": False, "child_criteria": [{"amount": 3}, {"amount": 1}]}},
            {"id": 2, "achievement": {"name": "Level 10"}, "completed_timestamp": 5}]},
        BASE + "/reputations": {"reputations": [
            {"faction": {"name": "Orgrimmar"}, "standing": {"name": "Friendly", "value": 4000, "max": 6000}}]},
        BASE + "/professions": {"primaries": [{"profession": {"name": "Herbalism"},
                                               "tiers": [{"skill_points": 40, "max_skill_points": 75,
                                                          "known_recipes": []}]}],
                                "secondaries": [{"profession": {"name": "Fishing"}, "skill_points": 10,
                                                 "max_skill_points": 75}]},
        BASE + "/pvp-summary": {"honorable_kills": 3, "pvp_rank": 0},
        BASE + "/encounters/dungeons": {"expansions": [{"instances": [
            {"instance": {"name": "Ragefire Chasm"},
             "modes": [{"difficulty": {"name": "Normal"},
                        "progress": {"completed_count": 2, "total_count": 4,
                                     "encounters": [{"last_kill_timestamp": 77}]}}]}]}]},
        BASE + "/achievements/statistics": {"categories": [
            {"name": "Combat", "statistics": [{"name": "Kills", "quantity": 120}],
             "sub_categories": [{"name": "Deaths", "statistics": [{"name": "Falling", "quantity": 2}]}]}]},
        # /encounters/raids missing on purpose
    }


def test_fetch_builds_a_snapshot(fake_api):
    fake_api.routes.update(profile_routes())
    s = wpr.fetch("Testy", "Mc")
    assert (s["name"], s["level"], s["cls"], s["cls_id"], s["faction"]) == ("Testy", 8, "Shaman", 7, "H")
    assert s["guild_slug"] == "example-guild"
    assert s["completed"] == [500]
    assert s["in_progress"] == [[510, "Active One"]]
    assert s["missing"] == ["encounters/raids"]
    assert s["achievements"][0] == {"name": "Explorer", "id": 1, "done": False, "amount": 3, "ts": 0}
    assert s["achievements"][1]["done"] is True
    assert s["reputations"][0]["value"] == 4000
    assert [(p["name"], p["primary"], p["skill"]) for p in s["professions"]] == \
        [("Herbalism", True, 40), ("Fishing", False, 10)]
    assert s["pvp"] == {"hk": 3, "rank": 0}
    assert s["dungeons"] == [["Ragefire Chasm", "Normal", 2, 4, 77]]
    assert s["raids"] == []
    assert {(x["cat"], x["sub"], x["name"], x["qty"]) for x in s["stats"]} == \
        {("Combat", "", "Kills", 120), ("Combat", "Deaths", "Falling", 2)}


def test_fetch_unknown_character(fake_api):
    with pytest.raises(wp.ApiError):
        wpr.fetch("Nobody", "Here")


def test_alliance_faction_from_name(fake_api):
    routes = profile_routes()
    routes[BASE]["faction"] = {"type": "ALLIANCE"}
    fake_api.routes.update(routes)
    assert wpr.fetch("Testy", "Mc")["faction"] == "A"


# ---------------------------------------------------------------- saving characters

def test_save_keeps_the_newest_24():
    for i in range(30):
        wpr.save(snapshot(name=f"Char{i}", fetched=i))
    data = wpr.load_saved()
    assert len(data["chars"]) == 24 and data["last"] == "char29 mc"
    assert "char0 mc" not in data["chars"] and "char29 mc" in data["chars"]


def test_forget_moves_last_to_another_character():
    wpr.save(snapshot(name="A"))
    wpr.save(snapshot(name="B"))
    wpr.forget("b mc")
    data = wpr.load_saved()
    assert list(data["chars"]) == ["a mc"] and data["last"] == "a mc"
    wpr.forget("not there")


def test_load_saved_with_a_broken_file():
    with open(wpr.PROGRESS_PATH, "w") as f:
        f.write("[]")
    assert wpr.load_saved() == {"last": None, "chars": {}}


def test_refresh_all_keeps_the_selected_character(fake_api, monkeypatch):
    wpr.save(snapshot(name="A", fetched=1))
    wpr.save(snapshot(name="B", fetched=2))
    data = wpr.load_saved()
    data["last"] = "a mc"
    wp.save_json(wpr.PROGRESS_PATH, data)

    def fake_fetch(name, surname):
        if name == "B":
            raise wp.ApiError(404, "gone")
        return snapshot(name=name, fetched=99)
    monkeypatch.setattr(wpr, "fetch", fake_fetch)
    ok, failed = wpr.refresh_all()
    assert ok == 1 and failed == ["B Mc"]
    data = wpr.load_saved()
    assert data["last"] == "a mc" and data["chars"]["a mc"]["fetched"] == 99


# ---------------------------------------------------------------- quest states

@pytest.fixture
def prog(db):
    return wpr.Progress(db, snapshot())


@pytest.mark.parametrize("qid, state", [
    (500, "done"), (510, "active"), (501, "now"), (509, "now"), (504, "gray"), (502, "later"),
    (507, "closed"), (508, "later"),
])
def test_quest_states(prog, qid, state):
    assert prog.state(qid) == state


def test_faction_and_class_filters(prog):
    assert 505 not in prog.mine                      # Alliance only
    assert 506 not in prog.mine                      # Warrior only
    assert 501 in prog.mine


def test_blockers(prog):
    assert prog.blockers(508) == ["after Wolf Cull"]
    assert prog.blockers(502) == ["needs level 18"]


def test_level_too_high_but_allowed(db):
    p = wpr.Progress(db, snapshot(level=13))       # 502 needs 18
    assert p.state(502) == "later"
    p = wpr.Progress(db, snapshot(level=18))
    assert p.state(502) == "now"


def test_unknown_completed_quests_are_counted(db):
    p = wpr.Progress(db, snapshot(completed=[500, 999999]))
    assert p.unknown_done == 1


def test_zones(prog):
    zones = {z["name"]: z for z in prog.zones()}
    t = zones["Testlands"]
    assert t["done"] == 1 and t["active"] == 1 and t["gray"] == 1
    assert 511 not in t["ids"]                       # repeatable quests not counted
    assert 507 not in t["ids"]                       # closed quests not counted
    assert prog.zones()[0]["name"] == "Testlands"    # most open quests first


def test_recommend(prog, use_travel):
    rec = prog.recommend()
    assert rec["zone"]["name"] == "Testlands"
    picks = [q for q, _z in rec["quests"]]
    assert 501 in picks and 509 in picks and all(prog.state(q) == "now" for q in picks)
    assert rec["finish"] == [[510, "Active One"]]
    assert [r["name"] for r in rec["reps"]] == ["Orgrimmar"]       # 2/3 of the way; Booty Bay isn't
    assert [m["name"] for m in rec["milestones"]] == ["Explorer"]
    assert rec["profs"][0]["name"] == "Herbalism"


def test_dungeons_that_fit(db, use_travel):
    p = wpr.Progress(db, snapshot(level=19))
    fits = [d["name"] for d in p.dungeons() if d["fits"]]
    assert fits == ["Grim Hold"]
    gh = next(d for d in p.dungeons() if d["name"] == "Grim Hold")
    assert gh["total"] == 1 and gh["now"] == [502]


def test_pick_stats():
    s = snapshot(stats=[{"cat": "Combat", "sub": "", "name": "Kills"},
                        {"cat": "Travel", "sub": "", "name": "Flight paths"}])
    assert [x["name"] for x in wpr.pick_stats(s, "kill|death")] == ["Kills"]


# ---------------------------------------------------------------- Tonight's route

def test_route_orders_pickup_objectives_turnin(prog):
    r = prog.route()
    assert r["zone"] == "Testlands" and r["stops"]
    acts = [a for s in r["stops"] for a in s["acts"]]
    order = {}
    for n, (kind, _text, q) in enumerate(acts):
        order.setdefault(q, []).append(kind)
    for q, kinds in order.items():
        rank = {"get": 0, "do": 1, "end": 2}
        assert [rank[k] for k in kinds] == sorted(rank[k] for k in kinds), (q, kinds)
    texts = [t for _k, t, _q in acts]
    assert "Get Boar Meat from Testlands Boar for Meat Run" in texts
    assert "Kill Grey Wolf for Wolf Cull" in texts
    assert any(t.startswith("Turn in Meat Run to Cook Bo") for t in texts)


def test_route_merges_close_steps(prog):
    stops = prog.route()["stops"]
    for a, b in zip(stops, stops[1:]):          # two stops in a row are never on the same spot
        assert abs(a["x"] - b["x"]) >= 2 or abs(a["y"] - b["y"]) >= 2
    # Boar Hunt's giver and Active One's quest giver stand together: one stop, several actions
    assert any(len(s["acts"]) > 1 for s in stops)


def test_route_lists_what_it_cannot_place(db):
    p = wpr.Progress(db, snapshot(completed=[500, 509], in_progress=[[513, "Far Away"]], level=8))
    r = p.route()
    assert any(q == 513 for *_rest, q in r["elsewhere"])           # on another map
    assert any("Click the Shrine" in t for t, _q in r["unknown"])   # objective not in the data


def test_route_with_nothing_to_do(db):
    p = wpr.Progress(db, snapshot(level=1, completed=[500, 504], in_progress=[]))
    r = p.route()
    assert r["stops"] == [] and r["quests"] == 0


# ---------------------------------------------------------------- quest descriptions from Blizzard

def test_quest_info_is_fetched_once(fake_api):
    fake_api.routes["/data/wow/quest/501"] = {
        "description": " Bring meat. ",
        "rewards": {"experience": 100, "money": {"value": 250},
                    "items": {"choice_of": [{"item": {"name": "Sword"}}, {"name": "Shield"}]}}}
    info = wpr.quest_info(501)
    assert info == {"desc": "Bring meat.", "xp": 100, "money": 250, "items": ["Sword", "Shield"]}
    n = len(fake_api.calls)
    assert wpr.quest_info(501) == info and len(fake_api.calls) == n
    saved = json.load(open(wpr.QINFO_PATH))["501"]
    assert saved.pop("at") > 0 and saved == info                       # stamped for the 30-day limit


def test_quest_info_missing_and_hiccup(fake_api):
    assert wpr.quest_info(404404) == {}                          # 404: remembered as "nothing"
    assert "404404" in json.load(open(wpr.QINFO_PATH))
    fake_api.routes["/data/wow/quest/7"] = wp.ApiError(503, "busy")
    assert wpr.quest_info(7) == {}
    assert "7" not in json.load(open(wpr.QINFO_PATH))            # a hiccup: ask again next time


# ---------------------------------------------------------------- guild crafters

ROSTER = "/data/wow/guild/example-guild/roster"


def guild_routes():
    return {
        ROSTER: {"guild": {"name": "Example Guild"}, "members": [
            {"character": {"name": "Ann", "surname": "Smith", "level": 30, "playable_class": {"name": "Mage"}},
             "rank": 0},
            {"character": {"name": "Bo", "level": 45, "playable_class": {"name": "Warrior"}}, "rank": 1},
            {"character": {"level": 5}}, "junk"]},
        "/profile/wow/character/ann-smith/professions": {"primaries": [
            {"profession": {"name": "Tailoring"}, "tiers": [
                {"skill_points": 150, "max_skill_points": 225,
                 "known_recipes": [{"name": "Bolt of Silk Cloth"}, {"name": "Azure Silk Hood"}, {}]}]}]},
        # Bo's professions page is missing
    }


def test_guild_slug():
    assert wpr.guild_slug("Example Guild") == "example-guild"
    assert wpr.guild_slug("  <The> Best! ") == "the-best"


def test_guild_crafters_reads_roster_and_professions(fake_api):
    fake_api.routes.update(guild_routes())
    seen = []
    g = wpr.guild_crafters("example-guild", progress=lambda d, n: seen.append((d, n)))
    assert g["name"] == "Example Guild" and g["listed"] == 2
    assert [m["name"] for m in g["members"]] == ["Bo", "Ann Smith"]           # highest level first
    bo, ann = g["members"]
    assert bo["read"] is False and ann["read"] is True
    assert ann["profs"][0]["recipes"] == ["Bolt of Silk Cloth", "Azure Silk Hood"]
    assert seen[-1] == (2, 2)
    assert wpr.find_crafters(g, "silk") == [("Azure Silk Hood", "Ann Smith", "Tailoring", 150, 30),
                                            ("Bolt of Silk Cloth", "Ann Smith", "Tailoring", 150, 30)]
    assert wpr.guild_professions(g) == [("Tailoring", "Ann Smith", 150, 225, 2, 30)]


def test_guild_crafters_cached_for_a_day(fake_api):
    fake_api.routes.update(guild_routes())
    first = wpr.guild_crafters("example-guild")
    n = len(fake_api.calls)
    assert wpr.guild_crafters("example-guild") == first and len(fake_api.calls) == n
    wpr.guild_crafters("example-guild", force=True)
    assert len(fake_api.calls) > n
    assert wpr.guild_cached("example-guild")["name"] == "Example Guild"
    assert wpr.guild_cached("other") is None


def test_guild_crafters_unexpected_answer_is_saved(fake_api):
    fake_api.routes[ROSTER] = {"something": "else"}
    with pytest.raises(SystemExit, match="guild_debug.json"):
        wpr.guild_crafters("example-guild")
    assert json.load(open(os.path.join(wp.CACHE_DIR, "guild_debug.json"))) == {"something": "else"}
