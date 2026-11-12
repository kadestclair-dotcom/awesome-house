"""Turning a typed item name into the right item.

Beta 0.14 shipped a bug here: Blizzard's search matches ANY word and returns the lowest IDs
first, so "Heavy Leather" became Dwarven Leather Pants and that wrong answer was saved for good.
These tests rebuild that situation with a fake search and check every layer of the fix."""

import json
import os

import pytest

import wow_price as wp
from conftest import ROOT, FakeApi, book, know_item

SEARCH = "/data/wow/search/item"


def leather_search(total_junk=150, real_id=4234, real_name="Heavy Leather", cap_1000=True):
    """A stand-in for Blizzard's item search: lots of leather items with low IDs first,
    the item actually asked for far down the list."""
    names = ["Dwarven Leather Pants", "Light Leather", "Rugged Leather", "Leather Cap", "Heavy Hide"]
    junk = [{"data": {"id": i + 1, "name": {"en_US": names[i % len(names)]}}} for i in range(total_junk)]
    everything = junk + [{"data": {"id": real_id, "name": {"en_US": real_name}}}]

    def answer(params):
        size = params["_pageSize"]
        if cap_1000 and size == 1000:
            return wp.ApiError(400, "page size too large")
        page = params["_page"]
        chunk = everything[(page - 1) * size: page * size]
        return {"results": chunk, "pageCount": -(-len(everything) // size)}
    return answer


def test_find_items_reads_more_pages_until_the_exact_name(sandbox):
    api = FakeApi({SEARCH: leather_search()})
    assert wp.find_items(api, "Heavy Leather") == [(4234, "Heavy Leather")]
    sizes = [c[2]["_pageSize"] for c in api.calls]
    assert sizes[0] == 1000 and set(sizes[1:]) == {100}          # fell back to the smaller page size
    assert len(api.calls) == 3                                   # 1000 refused, page 1, page 2


def test_find_items_curly_apostrophe_and_spacing():
    api = FakeApi({SEARCH: leather_search(real_name="Kel'Thuzad's Ring", total_junk=3)})
    assert wp.find_items(api, "  Kel’Thuzad's   Ring ") == [(4234, "Kel'Thuzad's Ring")]


def test_find_items_without_exact_keeps_names_with_every_word():
    api = FakeApi({SEARCH: leather_search(total_junk=20, real_name="Thick Leather")})
    found = wp.find_items(api, "leather pants")
    assert found and all("leather pants" in n.lower() for _i, n in found)


def test_find_items_by_number_uses_item_endpoint():
    api = FakeApi({"/data/wow/item/2318": {"id": 2318, "name": {"en_US": "Light Leather"},
                                          "item_class": {"name": "Trade Goods"}, "quality": {"type": "COMMON"}}})
    assert wp.find_items(api, "2318") == [(2318, "Light Leather")]
    assert wp.cached_info("forever", 2318)["cls"] == "Trade Goods"


def test_find_items_by_number_when_blizzard_has_no_page():
    api = FakeApi()
    assert wp.find_items(api, "99999") == [(99999, "Item 99999")]


def test_find_items_broken_search_explains_itself():
    api = FakeApi({SEARCH: wp.ApiError(500, "down")})
    with pytest.raises(SystemExit, match="item ID"):
        wp.find_items(api, "Heavy Leather")


def test_find_items_includes_names_already_known_locally():
    know_item(777, "Heavy Leather")
    api = FakeApi({SEARCH: {"results": [], "pageCount": 1}})
    assert wp.find_items(api, "heavy leather") == [(777, "Heavy Leather")]


def test_resolve_item_exact_only():
    api = FakeApi({SEARCH: leather_search()})
    assert wp.resolve_item(api, "Heavy Leather") == {"id": 4234, "name": "Heavy Leather"}


def test_resolve_item_never_returns_a_near_miss():
    api = FakeApi({SEARCH: leather_search(real_name="Heavy Leather Ball")})
    assert wp.resolve_item(api, "Heavy Leather") is None         # a near miss must not be priced


def test_resolve_item_prefers_local_names_without_searching():
    know_item(4234, "Heavy Leather")
    api = FakeApi()
    assert wp.resolve_item(api, "heavy leather") == {"id": 4234, "name": "Heavy Leather"}
    assert api.calls == []


def test_pick_prefers_the_item_listed_on_the_ah():
    know_item(50, "Twin Name")
    know_item(60, "Twin Name")
    assert wp.local_item("forever", "Twin Name")["id"] == 50                     # lowest id
    wp._forever_memo["us"] = (0, [("House", book((60, 100, 1)))], set())
    assert wp.local_item("forever", "Twin Name")["id"] == 60                     # the one for sale


def test_resolve_cached_saves_and_reuses():
    api = FakeApi({SEARCH: leather_search()})
    first = wp.resolve_cached(api, "Heavy Leather")
    n = len(api.calls)
    assert wp.resolve_cached(api, "heavy  LEATHER") == first
    assert len(api.calls) == n
    saved = json.load(open(wp.ITEM_CACHE_PATH))
    assert list(saved) == ["forever:heavy leather"]
    assert {k: v for k, v in saved["forever:heavy leather"].items() if k != "at"} == {"id": 4234, "name": "Heavy Leather"}
    assert saved["forever:heavy leather"]["at"] > 0                    # stamped for the 30-day limit


def test_resolve_cached_repairs_a_wrong_saved_answer():
    """Exactly what 0.14 left in people's item_cache.json."""
    wp.save_json(wp.ITEM_CACHE_PATH, {"forever:heavy leather": {"id": 61, "name": "Dwarven Leather Pants"}})
    api = FakeApi({SEARCH: leather_search()})
    assert wp.resolve_cached(api, "Heavy Leather")["id"] == 4234
    assert json.load(open(wp.ITEM_CACHE_PATH))["forever:heavy leather"]["id"] == 4234


def test_resolve_cached_survives_a_broken_cache_file():
    with open(wp.ITEM_CACHE_PATH, "w") as f:
        f.write("{not json")
    know_item(4234, "Heavy Leather")
    assert wp.resolve_cached(FakeApi(), "Heavy Leather")["id"] == 4234


def test_lookup_items_ranks_exact_then_phrase_then_listed(use_sources):
    know_item(1, "Heavy Leather Ball")
    know_item(2, "Heavy Leather")
    know_item(3, "Extra Heavy Leather Thing")
    use_sources([("House", book((1, 500, 99), (3, 100, 1)))])
    api = FakeApi({SEARCH: {"results": [], "pageCount": 1}})
    # no exact name -> every "contains all words" match, phrase matches first
    res = wp.lookup_items(api, "heavy leather")
    assert [e["id"] for e in res["items"]] == [2]          # exact name wins outright
    res = wp.lookup_items(api, "leather heavy")
    ids = [e["id"] for e in res["items"]]
    assert set(ids) == {1, 2, 3} and ids.index(1) < ids.index(2)   # listed before not listed


# ---------------------------------------------------------------- no Blizzard data ships with the exe

def test_the_app_no_longer_copies_bundled_item_data():
    """Blizzard API Terms 2.5/2.18: item data is fetched with each user's own key and kept 30 days, not
    shipped. (Up to Beta 0.15 item_info/item_stats/item_cache.json were bundled and copied out.)"""
    src = open(os.path.join(ROOT, "wow_price.py"), encoding="utf-8").read()
    assert "_seed" not in src and "shutil.copyfile(_src" not in src


def test_items_sharing_a_name_prefer_the_one_listed_in_this_region():
    wp._forever_memo["eu"] = (0, [("H", book((2, 100, 1)))], set())
    wp._forever_memo["us"] = (0, [("H", book((1, 100, 1)))], set())
    both = [(1, "Twin Blade"), (2, "Twin Blade")]
    assert wp._pick("forever", both, region="eu") == {"id": 2, "name": "Twin Blade"}
    assert wp._pick("forever", both) == {"id": 1, "name": "Twin Blade"}
