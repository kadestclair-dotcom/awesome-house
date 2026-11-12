"""Auction-house price math, history, trends and the money tools (sell helper, flips, crafting,
fishing). Blizzard is faked and the auction snapshot is built by hand."""

import json
import os
import time
from datetime import datetime

import pytest

import wow_price as wp
from conftest import FakeApi, book, know_item

HOUSES = "/data/wow/ruleset/2/auctions/"


# ---------------------------------------------------------------- summarize

def test_summarize_basic():
    s = wp.summarize([(200, 9), (100, 1)])
    assert s == {"lowest": 100, "cheap10": 100, "median": 200, "quantity": 10, "listings": 2}


def test_summarize_cheap10_is_average_of_cheapest_tenth():
    s = wp.summarize([(100, 5), (300, 5), (1000, 90)])      # cheapest 10 units: 5 @100 + 5 @300
    assert s["cheap10"] == pytest.approx(200)
    assert s["median"] == 1000 and s["quantity"] == 100


def test_summarize_weighted_median_matches_expanded_list():
    import statistics
    lst = [(10, 3), (20, 1), (30, 4), (40, 2)]
    expanded = sorted(p for p, n in lst for _ in range(n))
    assert wp.summarize(lst)["median"] == statistics.median_low(expanded)


def test_add_listings_reads_both_price_kinds_and_skips_junk():
    b = {}
    wp.add_listings(b, [{"item": {"id": 1}, "unit_price": 50, "quantity": 20},
                        {"item": {"id": 2}, "buyout": 9000},
                        {"item": {"id": 3}},                      # no price
                        "junk", None])
    assert b == {1: [(50, 20)], 2: [(9000, 1)]}


def test_build_entries_and_item_summary():
    know_item(1, "Copper Ore", cls="Trade Goods")
    sources = [("North", book((1, 100, 10))), ("South", book((1, 80, 2), (1, 120, 5)))]
    entry = wp.build_entries(FakeApi(), sources, [(1, "Copper Ore"), (2, "Nothing")])
    assert entry[0]["found"] and entry[0]["lowest"] == 80 and entry[0]["quantity"] == 17
    assert [h["label"] for h in entry[0]["houses"]] == ["South", "North"]
    assert entry[1]["found"] is False
    assert wp.build_entries(FakeApi(), sources, [(2, "Nothing")], only_listed=True) == []

    s = wp.item_summary(sources, 1)
    assert s["house"] == "South" and s["lowest"] == 80
    s["lowest"] = -1                                       # callers may change their copy...
    assert wp.item_summary(sources, 1)["lowest"] == 80     # ...without touching the remembered one
    assert wp.item_summary(sources, 2) is None


def test_item_summary_memo_resets_for_a_new_snapshot():
    a = [("H", book((1, 100, 1)))]
    b = [("H", book((1, 50, 1)))]
    assert wp.item_summary(a, 1)["lowest"] == 100
    assert wp.item_summary(b, 1)["lowest"] == 50


# ---------------------------------------------------------------- Forever auction download

def forever_routes():
    return {
        HOUSES: {"auctions": [{"id": 110, "name": "Orgrimmar"}, {"id": 111, "name": "Orgrimmar"},
                              {"id": 112, "name": {"en_US": "Ironforge"}}]},
        # gear only in the house call, the same auction twice
        HOUSES + "110": {"auctions": [{"id": 1, "item": {"id": 200}, "buyout": 5000, "quantity": 1},
                                      {"id": 1, "item": {"id": 200}, "buyout": 5000, "quantity": 1}],
                         "commodities": {"href": "https://link"}},
        HOUSES + "110/commodities": {"auctions": [{"id": 2, "item": {"id": 2318}, "unit_price": 100,
                                                   "quantity": 20}]},
        # stackables only
        HOUSES + "111": {"commodities": [{"id": 3, "item": {"id": 2318}, "unit_price": 90, "quantity": 5}]},
        HOUSES + "111/auctions": wp.ApiError(404, "none"),
        # house 112 is down
    }


def test_forever_sources_combines_houses_and_dedupes():
    api = FakeApi(forever_routes())
    sources = wp.forever_sources(api)
    labels = [s[0] for s in sources]
    assert labels == ["Orgrimmar #110", "Orgrimmar #111", "Ironforge"]
    org = dict(sources)
    assert org["Orgrimmar #110"] == {200: [(5000, 1)], 2318: [(100, 20)]}
    assert org["Orgrimmar #111"] == {2318: [(90, 5)]}
    assert org["Ironforge"] == {}
    assert api.gear_ids == {200}
    assert os.path.exists(os.path.join(wp.CACHE_DIR, "forever_us_forever_all_houses_v5.json"))


def test_forever_sources_second_call_is_free():
    api = FakeApi(forever_routes())
    first = wp.forever_sources(api)
    n = len(api.calls)
    assert wp.forever_sources(api) is first
    assert len(api.calls) == n


def test_forever_sources_reads_the_saved_snapshot_after_restart():
    api = FakeApi(forever_routes())
    wp.forever_sources(api)
    wp._forever_memo.clear()                     # like starting the app again
    api2 = FakeApi()                             # Blizzard unreachable: the hour-old file is used
    assert dict(wp.forever_sources(api2))["Orgrimmar #111"] == {2318: [(90, 5)]}


def test_forever_house_list_fallback():
    houses = wp.forever_house_list(FakeApi())
    assert [h for h, _n in houses] == wp.FOREVER_FALLBACK_HOUSES


# ---------------------------------------------------------------- history and trends

def row(iid, market, qty=10, lowest=None):
    return {"id": iid, "found": True, "lowest": lowest or market, "cheap10": market, "quantity": qty}


def test_history_records_once_per_snapshot():
    t1, t2 = int(time.time()) - 7200, int(time.time()) - 3600   # recent: older points expire after 30 days
    wp.record_history("forever", t1, [row(1, 100), {"id": 2, "found": False}])
    wp.record_history("forever", t1, [row(1, 999)])             # same snapshot: ignored
    wp.record_history("forever", t2, [row(1, 110)])
    assert wp.price_history("forever", 1, 0) == [(t1, 100, 100, 10), (t2, 110, 110, 10)]
    assert wp.price_history("forever", 2, 0) == []
    assert wp.price_history("retail", 1, 0) == []


def test_pct_change_and_trends():
    now = int(time.time())
    wp.record_history("forever", now - 86400, [row(1, 100)])
    wp.record_history("forever", now - 7 * 86400 - 3600, [row(1, 200)])
    assert wp.pct_change("forever", 1, 110, now, 86400) == pytest.approx(10)
    rows = [row(1, 110)]
    wp.add_trends("forever", now, rows)
    assert rows[0]["day"] == pytest.approx(10)
    assert rows[0]["week"] == pytest.approx(-45)
    assert rows[0]["month"] is None                              # nothing near 30 days ago


def test_history_stats():
    now = int(time.time())
    for i, m in enumerate([100, 300, 200]):
        wp.record_history("forever", now - 3600 * (3 - i), [row(1, m, qty=10 * (i + 1))])
    st = wp.history_stats("forever", 1, 7)
    assert st["points"] == 3 and st["median_market"] == 200 and st["median_qty"] == 20
    assert wp.history_stats("forever", 1, 7, before_ts=now - 3 * 3600) is None


def test_check_watchlist(use_sources):
    use_sources([("H", book((1, 100, 5)))])
    entries = [{"id": 1, "name": "Copper Ore", "cls": "Trade Goods"}, {"id": 2, "name": "Gone", "cls": "X"}]
    rows = wp.check_watchlist(FakeApi(), entries)
    assert rows[0]["found"] and rows[0]["lowest"] == 100 and "day" in rows[0]
    assert rows[1]["found"] is False
    text = wp.format_watchlist(rows)
    assert "Copper Ore" in text and "not listed" in text
    assert wp.format_watchlist([]) == "Your watchlist is empty."


def test_watchlist_round_trip_and_broken_file():
    wp.save_watchlist([{"id": 1, "name": "A"}])
    assert wp.load_watchlist() == [{"id": 1, "name": "A"}]
    with open(wp.WATCHLIST_PATH, "w") as f:
        f.write("[oops")
    assert wp.load_watchlist() == []


# ---------------------------------------------------------------- sell helper and timing

def test_sell_advice_ignores_a_tiny_undercut(use_sources):
    use_sources([("H", book((1, 50, 1), (1, 100, 50), (1, 120, 50)))])
    res = wp.sell_advice(FakeApi(), "x", my_qty=10, item={"id": 1, "name": "Ore"})
    assert res["outlier"] == {"price": 50, "qty": 1, "next": 100}
    assert res["suggested"] == 99
    assert res["ahead"] == 1
    assert res["payout"] == pytest.approx(99 * 10 * 0.95)
    assert res["ladder"][0] == (50, 1, 1) and res["ladder"][1] == (100, 50, 51)


def test_sell_advice_undercuts_by_one_copper(use_sources):
    use_sources([("H", book((1, 100, 20), (1, 100, 5), (1, 105, 20)))])
    res = wp.sell_advice(FakeApi(), "x", item={"id": 1, "name": "Ore"})
    assert res["outlier"] is None and res["suggested"] == 99
    assert res["ladder"][0] == (100, 25, 25)                     # same price merged into one step


def test_sell_advice_not_listed_and_not_found(use_sources):
    use_sources([("H", {})])
    res = wp.sell_advice(FakeApi(), "x", item={"id": 1, "name": "Ore"})
    assert res["listed"] is False
    assert wp.sell_advice(FakeApi({"/data/wow/search/item": {"results": []}}), "No Such Item") is None


def test_sell_timing_finds_the_expensive_hours():
    now = int(time.time())
    start = now - 3 * 86400
    for t in range(start, now, 3600):
        block = datetime.fromtimestamp(t).hour // 3
        wp.record_history("forever", t, [row(1, 150 if block == 5 else 100)])
    res = wp.sell_timing("forever", 1, days=30)
    assert res["points"] >= 70 and res["hours"] is not None and res["weekdays"] is None
    values = [v for v, _n in res["hours"]]
    assert max(range(8), key=lambda k: values[k] if values[k] is not None else -999) == 5


def test_sell_timing_needs_data():
    assert wp.sell_timing("forever", 1)["hours"] is None


# ---------------------------------------------------------------- flip finder

def test_find_flips(use_sources):
    wp.save_watchlist([{"id": 1, "name": "Ore"}, {"id": 2, "name": "New"}])
    now = int(time.time())
    for i in range(14):
        wp.record_history("forever", now - 3600 * (i + 1), [row(1, 1000)])
    use_sources([("H", book((1, 500, 4), (1, 990, 10)))])
    api = FakeApi()
    api.snapshot_time = now
    res = wp.find_flips(api)
    assert res["skipped"] == ["New"]
    f = res["flips"][0]
    assert f["units"] == 4 and f["cost"] == 2000
    assert f["profit"] == pytest.approx((1000 * 0.95 - 500) * 4)
    assert f["discount"] == pytest.approx(50)


# ---------------------------------------------------------------- fishing, crafting, spots

def test_value_catch_merges_and_reports_unknown(use_sources):
    know_item(6303, "Raw Slitherskin Mackerel")
    know_item(6289, "Raw Longjaw Mud Snapper")
    use_sources([("H", book((6303, 20, 100)))])
    api = FakeApi({"/data/wow/search/item": {"results": []}})
    catch = wp.parse_catch("10 Raw Slitherskin Mackerel\n5 6303\n3 Raw Longjaw Mud Snapper\n2 Mystery Fish")
    api.routes["/data/wow/item/6303"] = {"id": 6303, "name": "Raw Slitherskin Mackerel"}
    res = wp.value_catch(api, catch)
    rows = {r["id"]: r for r in res["rows"]}
    assert rows[6303]["qty"] == 15 and rows[6303]["total"] == 300
    assert rows[6289]["found"] is False
    assert res["unresolved"] == ["Mystery Fish"]
    assert res["after_cut"] == pytest.approx(285)


def test_sessions_round_trip():
    wp.save_session({"spot": "Pier", "minutes": 30, "items": [{"name": "Fish", "qty": 30}]})
    wp.save_session({"spot": "pier ", "minutes": 30, "items": [{"name": "Fish", "qty": 10},
                                                               {"name": "Boot", "qty": 10}]})
    assert len(wp.load_sessions()) == 2
    sp = wp.spot_from_sessions("PIER")
    assert sp["catches_per_hour"] == 50.0 and sp["sessions"] == 2
    assert wp.parse_drops(sp["drops"]) == [(80.0, "Fish"), (20.0, "Boot")]
    assert wp.spot_from_sessions("Nowhere") is None


def test_craft_profit(use_sources):
    know_item(1, "Light Leather")
    know_item(2, "Handstitched Boots")
    use_sources([("H", book((1, 100, 50), (2, 2000, 5)))])
    api = FakeApi({"/data/wow/search/item": {"results": []}})
    res = wp.craft_profit(api, [
        {"name": "Boots", "makes": "Handstitched Boots", "reagents": "4 Light Leather\n1 Coarse Thread @ 10c"},
        {"name": "Broken", "makes": "Handstitched Boots", "reagents": "1 Thread @ lots"},
        {"name": "Mystery", "makes": "Nope Item", "reagents": ""},
        {"name": "No mats", "makes": "Handstitched Boots", "reagents": "1 Unknown Reagent"},
    ])
    ok = res[0]
    assert ok["ok"] and ok["cost"] == 410 and ok["sell"] == pytest.approx(1900)
    assert ok["profit"] == pytest.approx(1490)
    assert ok["vs_raw"] == pytest.approx(1900 - (400 * 0.95 + 10))
    assert not res[1]["ok"] and "price" in res[1]["errors"][0]
    assert not res[2]["ok"] and "crafted item" in res[2]["errors"][0]
    assert not res[3]["ok"] and "reagent" in res[3]["errors"][0]


def test_plan_spots(use_sources):
    know_item(1, "Fish A")
    know_item(2, "Fish B")
    use_sources([("H", book((1, 100, 10), (2, 300, 10)))])
    api = FakeApi({"/data/wow/search/item": {"results": []}})
    res = wp.plan_spots(api, [
        {"name": "Cheap", "catches_per_hour": 100, "drops": "100% Fish A"},
        {"name": "Rich", "catches_per_hour": 100, "drops": "60 Fish A\n60 Fish B"},   # shares add to 120
        {"name": "Empty", "catches_per_hour": 100, "drops": ""},
        {"name": "Slow", "catches_per_hour": 0, "drops": "100% Fish A"},
    ])
    assert [r["name"] for r in res][:2] == ["Rich", "Cheap"]           # best gold per hour first
    rich = res[0]
    assert rich["per_catch"] == pytest.approx(200) and rich["normalized"] is True
    assert rich["gph"] == pytest.approx(100 * 200 * 0.95)
    assert {r["name"]: r["ok"] for r in res} == {"Rich": True, "Cheap": True, "Empty": False, "Slow": False}


def test_option_cost_and_value():
    prices = {"Ore": {"each": 10, "how": "AH"}, "Bar": {"each": 50, "how": "AH"}, "Flux": {"each": None}}
    opt = {"crafts": [("Smelt", 3, [("Ore", 2), ("Flux", 1)], "Bar")], "gathers": ["Ore", "Bar", "Nope"]}
    cost, value, missing = wp.option_cost(opt, prices)
    assert cost == 60 and value == pytest.approx(3 * 50 * 0.95) and missing == ["Flux"]
    assert wp.option_value(opt, prices) == 30
    assert wp.option_value({"gathers": []}, prices) is None


# ---------------------------------------------------------------- credentials and token

def test_credentials_file_and_env(monkeypatch):
    assert wp.has_credentials() is False
    wp.save_credentials(" id ", " secret ")
    assert wp.has_credentials() and wp.load_credentials() == ("id", "secret")
    monkeypatch.setenv("BLIZZARD_CLIENT_ID", "e1")
    monkeypatch.setenv("BLIZZARD_CLIENT_SECRET", "e2")
    assert wp.load_credentials() == ("e1", "e2")


def test_saved_token_is_reused_until_it_expires(monkeypatch):
    path = os.path.join(wp.CACHE_DIR, "token.json")
    wp.save_json(path, {"access_token": "old", "expires_at": time.time() + 3600})
    assert wp.get_token("id", "secret") == "old"
    wp.save_json(path, {"access_token": "old", "expires_at": time.time() + 10})
    monkeypatch.setattr(wp, "http_json", lambda *a, **k: {"access_token": "new", "expires_in": 100})
    assert wp.get_token("id", "secret") == "new"
    assert json.load(open(path))["access_token"] == "new"


def test_bad_login_explains_itself(monkeypatch):
    def refuse(*a, **k):
        raise wp.ApiError(401, "nope")
    monkeypatch.setattr(wp, "http_json", refuse)
    with pytest.raises(SystemExit, match="Client ID"):
        wp.get_token("id", "secret")


def test_namespaces():
    assert wp.Blizz("t", "us", "forever").ns("dynamic") == "dynamic-forever-us"
    assert wp.Blizz("t", "eu", "retail").ns("static") == "static-eu"


# ---------------------------------------------------------------- CSV export

def test_export_history_csv(tmp_path):
    know_item(1, "Copper Ore")
    wp.save_watchlist([{"id": 1, "name": "Copper Ore"}])
    wp.record_history("forever", int(time.time()), [row(1, 15000)])
    out = tmp_path / "h.csv"
    wp.export_history_csv(str(out))
    lines = out.read_text().strip().splitlines()
    assert lines[0].startswith("date_time,") and len(lines) == 2
    assert ",1.5," in lines[1]                                   # 15000 copper = 1.5 gold


def test_export_sessions_csv(tmp_path):
    wp.save_session({"date": "2026-11-11T20:00", "spot": "Pier", "minutes": 30, "after_cut": 9500,
                     "gph": 19000, "items": [{"name": "Fish", "qty": 3, "each": 2000}]})
    out = tmp_path / "s.csv"
    wp.export_sessions_csv(str(out))
    lines = out.read_text().strip().splitlines()
    assert lines[1].startswith("2026-11-11 20:00,Pier,30,Fish,3,0.2,0.6,0.95,1.9")


# ---------------------------------------------------------------- an auction house that doesn't answer

SNAP_FILE = "forever_us_forever_all_houses_v5.json"


def one_house_down(error=None):
    routes = forever_routes()
    routes[HOUSES + "111"] = error or wp.ApiError(503, "Service Unavailable")
    routes[HOUSES + "111/commodities"] = error or wp.ApiError(503, "Service Unavailable")
    routes[HOUSES + "111/auctions"] = error or wp.ApiError(503, "Service Unavailable")
    return routes


def test_all_houses_answering_is_saved_and_has_no_note():
    api = FakeApi(forever_routes())
    wp.forever_sources(api)
    assert os.path.exists(os.path.join(wp.CACHE_DIR, SNAP_FILE))
    assert not api.partial and wp.snapshot_note() is None


@pytest.mark.parametrize("error", [None, wp.NetworkError("Could not reach Blizzard API: reset")])
def test_a_house_that_fails_is_not_saved_as_empty_for_the_hour(error):
    api = FakeApi(one_house_down(error))
    sources = dict(wp.forever_sources(api))
    assert sources["Orgrimmar #110"]                        # the houses that answered are still used
    assert api.partial
    assert not os.path.exists(os.path.join(wp.CACHE_DIR, SNAP_FILE))
    assert wp.snapshot_note() == "2 of 3 auction houses answered - prices may be incomplete"


def test_a_partial_snapshot_is_reused_briefly_then_tried_again(monkeypatch):
    api = FakeApi(one_house_down())
    first = wp.forever_sources(api)
    n = len(api.calls)
    assert wp.forever_sources(api) is first and len(api.calls) == n     # no hammering Blizzard
    later = time.time() + wp.PARTIAL_RETRY_SECONDS + 1
    monkeypatch.setattr(wp.time, "time", lambda: later)
    api.routes.update(forever_routes())                                  # the house is back
    full = dict(wp.forever_sources(api))
    assert full["Orgrimmar #111"] == {2318: [(90, 5)]}
    assert not api.partial and wp.snapshot_note() is None


def test_a_partial_check_records_no_history_and_says_so():
    api = FakeApi(one_house_down())
    rows = wp.check_watchlist(api, [{"id": 2318, "name": "Light Leather", "cls": "Trade Goods"}])
    assert rows[0]["found"] and rows[0]["partial"]
    assert wp.price_history("forever", 2318, 0) == []


def test_a_full_check_records_history():
    api = FakeApi(forever_routes())
    rows = wp.check_watchlist(api, [{"id": 2318, "name": "Light Leather", "cls": "Trade Goods"}])
    assert not rows[0].get("partial")
    assert len(wp.price_history("forever", 2318, 0)) == 1
