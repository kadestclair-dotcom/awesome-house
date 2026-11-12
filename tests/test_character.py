"""Character tab: reading a character, who can use what, and how upgrades are scored."""

import pytest

import wow_price as wp
from conftest import FakeApi, book, char

W = {"STRENGTH": 1.0, "AGILITY": 0.5, "STAMINA": 0.5, "DPS": 2.0}


def gear(inv, sub=None, cls_id=wp.ARMOR, ilvl=20, q="UNCOMMON", req=1, stats=None, **extra):
    return {"inv": inv, "sub_id": sub, "cls_id": cls_id, "ilvl": ilvl, "q": q, "req": req,
            "stats": stats or {}, "armor": 0, "dps": 0, **extra}


# ---------------------------------------------------------------- reading a character

def test_get_character_forever():
    base = "/profile/wow/character/example-person"
    api = FakeApi({
        base: {"name": "Example", "surname": "Person", "level": 14, "character_class": {"name": "Shaman"},
               "race": {"name": "Orc"}, "faction": {"name": "Horde"}, "equipped_item_level": 12},
        base + "/equipment": {"equipped_items": [
            {"slot": {"type": "CHEST", "name": "Chest"}, "item": {"id": 6125}, "name": "Brawler's Harness",
             "inventory_type": {"type": "CHEST"}, "item_subclass": {"id": 2}, "level": 10,
             "stats": [{"type": {"type": "STRENGTH"}, "value": 2}]},
            "junk"]},
    })
    c = wp.get_character(api, "Example", "Person")
    assert (c["name"], c["level"], c["cls"], c["faction"], c["ilvl"]) == ("Example", 14, "Shaman", "Horde", 12)
    assert len(c["gear"]) == 1
    g = c["gear"][0]
    assert (g["slot"], g["slot_name"], g["id"], g["stats"]) == ("CHEST", "Chest", 6125, {"STRENGTH": 2})


def test_get_character_without_equipment_page():
    api = FakeApi({"/profile/wow/character/a-b": {"name": "A", "level": 10}})
    assert wp.get_character(api, "A", "B")["gear"] == []


def test_get_character_not_found():
    with pytest.raises(wp.ApiError) as e:
        wp.get_character(FakeApi(), "Nobody")
    assert e.value.code == 404


# ---------------------------------------------------------------- who can use what

@pytest.mark.parametrize("cls, level, slot, item, ok, why", [
    ("Shaman", 20, "CHEST", gear("CHEST", wp.LEATHER), True, ""),
    ("Shaman", 20, "CHEST", gear("CHEST", wp.MAIL), False, "mail - unlocks at 40"),
    ("Shaman", 40, "CHEST", gear("CHEST", wp.MAIL), True, ""),
    ("Shaman", 40, "CHEST", gear("CHEST", wp.LEATHER), True, ""),         # one step down is fine
    ("Shaman", 20, "CHEST", gear("CHEST", wp.CLOTH), False, "cloth - you wear leather"),
    ("Priest", 20, "CHEST", gear("CHEST", wp.CLOTH), True, ""),
    ("Priest", 20, "CHEST", gear("CHEST", wp.LEATHER), False, "leather - not your armor"),
    ("Warrior", 45, "LEGS", gear("LEGS", wp.MAIL), True, ""),
    ("Shaman", 20, "OFF_HAND", gear("SHIELD", 6), True, ""),
    ("Rogue", 20, "OFF_HAND", gear("SHIELD", 6), False, "Rogues can't use shields"),
    ("Rogue", 20, "OFF_HAND", gear("HOLDABLE"), False, "caster off-hand"),
    ("Mage", 20, "OFF_HAND", gear("HOLDABLE"), True, ""),
    ("Mage", 20, "MAIN_HAND", gear("WEAPON", wp.AXE1, wp.WEAPON), False, "can't use one-handed axes"),
    ("Mage", 20, "MAIN_HAND", gear("WEAPON", wp.SWORD1, wp.WEAPON), True, ""),
    ("Paladin", 20, "OFF_HAND", gear("WEAPON", wp.SWORD1, wp.WEAPON), False, "can't dual wield"),
    ("Warrior", 12, "OFF_HAND", gear("WEAPON", wp.SWORD1, wp.WEAPON), False, "dual wield at level 20"),
    ("Warrior", 20, "OFF_HAND", gear("WEAPON", wp.SWORD1, wp.WEAPON), True, ""),
    ("Rogue", 10, "OFF_HAND", gear("WEAPON", wp.DAGGER, wp.WEAPON), True, ""),
    ("Rogue", 20, "MAIN_HAND", gear("WEAPONOFFHAND", wp.DAGGER, wp.WEAPON), False, "off-hand only"),
    ("Shaman", 5, "CHEST", gear("CHEST", wp.LEATHER, req=10), False, "needs level 10"),
    ("Mystery Class", 5, "CHEST", gear("CHEST", wp.PLATE), True, ""),       # unknown class: no rules
])
def test_check_use(cls, level, slot, item, ok, why):
    assert wp.check_use(char(cls, level), slot, item) == (ok, why)


def test_check_use_two_hander_blocks_off_hand():
    assert wp.check_use(char("Warrior", 30), "OFF_HAND", gear("SHIELD", 6), two_hander=True) == \
        (False, "you wield a two-hander")


def test_every_class_has_gear_rules_and_stat_presets():
    assert set(wp.CLASS_GEAR) == set(wp.STAT_PRESETS)
    for cls, presets in wp.STAT_PRESETS.items():
        assert presets, cls
        for name, weights in presets.items():
            assert all(k in wp.PRIMARY + ("DPS", "RDPS", "ARMOR") for k in weights), (cls, name)


def test_every_slot_has_a_name_and_a_default_inventory_type():
    assert set(wp.SLOT_SEARCH) == set(wp.SLOT_NAMES)
    assert set(wp.SLOT_SEARCH) <= set(wp.SLOT_DEFAULT_INV)


# ---------------------------------------------------------------- scoring

def test_item_power_follows_quality_and_slot():
    assert wp.item_power(0, "EPIC", "HEAD") == 0
    assert wp.item_power(30, "RARE", "HEAD") > wp.item_power(30, "UNCOMMON", "HEAD") > \
        wp.item_power(30, "COMMON", "HEAD") > 0
    for q in ("COMMON", "UNCOMMON", "RARE", "EPIC"):                    # more item level, more power
        assert wp.item_power(70, q, "HEAD") > wp.item_power(50, q, "HEAD") >= 0
    assert wp.item_power(30, "RARE", "HEAD") > wp.item_power(30, "RARE", "WRIST")
    assert wp.item_power(30, "RARE", None, slot="FINGER_1") == wp.item_power(30, "RARE", "FINGER")
    assert wp.item_power(5, "COMMON", "HEAD") == 0                  # never negative


def test_efficiency_rewards_useful_stats():
    strong = gear("CHEST", stats={"STRENGTH": 10})
    sta = gear("CHEST", stats={"STAMINA": 10})
    e1, e2 = wp.efficiency(strong, W, "CHEST"), wp.efficiency(sta, W, "CHEST")
    assert e1["eff"] > e2["eff"]
    assert e1["fit"] == pytest.approx(1.0) and e2["fit"] == pytest.approx(0.5)
    assert not e1["est"]


def test_efficiency_estimates_when_stats_are_unknown():
    e = wp.efficiency(gear("CHEST", ilvl=30, q="RARE"), W, "CHEST")
    assert e["est"] and e["fit"] == wp.TYPICAL_FIT and e["eff"] > 0
    assert wp.efficiency(None, W, "CHEST") == {"eff": 0.0, "power": 0.0, "fit": None, "est": False}


def test_efficiency_modes():
    low_stats_high_ilvl = gear("CHEST", ilvl=40, stats={"STAMINA": 1})
    big_stats_low_ilvl = gear("CHEST", ilvl=20, stats={"STRENGTH": 20})
    ilvl, stats = "Item level only", "Stats only"
    assert wp.efficiency(low_stats_high_ilvl, W, "CHEST", ilvl)["eff"] > \
        wp.efficiency(big_stats_low_ilvl, W, "CHEST", ilvl)["eff"]
    assert wp.efficiency(big_stats_low_ilvl, W, "CHEST", stats)["eff"] > \
        wp.efficiency(low_stats_high_ilvl, W, "CHEST", stats)["eff"]
    unknown = gear("CHEST", ilvl=60, q="EPIC")
    assert wp.efficiency(unknown, W, "CHEST", stats)["eff"] == pytest.approx(0.6)   # guesses don't count
    assert set(wp.COMPARE_MODES) == {"Efficiency (power x fit)", stats, ilvl}


def test_weapon_dps_counts_for_the_right_slot():
    w = {"STRENGTH": 1.0, "DPS": 3.0, "RDPS": 0.5}
    melee = gear("WEAPON", wp.SWORD1, wp.WEAPON, stats={"STRENGTH": 1}, dps=10)
    assert wp.efficiency(melee, w, "MAIN_HAND")["eff"] == pytest.approx(1 + 30 + 0.2)
    assert wp.efficiency(melee, w, "RANGED")["eff"] == pytest.approx(1 + 5 + 0.2)


# ---------------------------------------------------------------- upgrade tables

def upgrade_index():
    items = [
        dict(gear("CHEST", wp.LEATHER, stats={"STRENGTH": 10}), id=1, name="Better Vest"),
        dict(gear("CHEST", wp.LEATHER, stats={"STRENGTH": 1}, ilvl=5), id=2, name="Worse Vest"),
        dict(gear("CHEST", wp.MAIL, stats={"STRENGTH": 30}), id=3, name="Mail Vest"),
        dict(gear("CHEST", wp.LEATHER, stats={"STRENGTH": 50}), id=4, name="Not For Sale"),
        dict(gear("FINGER", stats={"STRENGTH": 5}), id=5, name="Ring"),
        dict(gear("HEAD", wp.LEATHER, stats={"STRENGTH": 9}), id=6, name="Cheap Helm"),
        dict(gear("HEAD", wp.LEATHER, stats={"STRENGTH": 10}), id=7, name="Pricey Helm"),
    ]
    sources = [("H", book((1, 10000, 1), (2, 100, 1), (3, 100, 1), (5, 500, 1), (6, 100, 1),
                          (7, 1000000, 1)))]
    return {"items": items, "sources": sources}


def test_slot_view_scores_against_what_you_wear():
    c = char("Shaman", 20, gear=[dict(gear("CHEST", wp.LEATHER, stats={"STRENGTH": 3}), slot="CHEST", id=99)])
    rows, cur = wp.slot_view(c, "CHEST", upgrade_index(), W)
    by = {r["id"]: r for r in rows}
    assert set(by) == {1, 2, 3}                           # not-for-sale item left out
    assert by[1]["better"] and by[1]["biggest"] and by[1]["up_pct"] > 0
    assert not by[2]["better"]
    assert not by[3]["usable"] and by[3]["why"] == "mail - unlocks at 40" and not by[3]["better"]
    assert cur["eff"] > 0


def test_slot_view_marks_best_value():
    rows, _cur = wp.slot_view(char("Shaman", 20), "HEAD", upgrade_index(), W)
    by = {r["id"]: r for r in rows}
    assert by[7].get("biggest") and by[6].get("best_value")


def test_best_upgrades_suggests_a_ring_once():
    rows, current = wp.best_upgrades(char("Shaman", 20), upgrade_index(), W)
    rings = [r for r in rows if r["id"] == 5]
    assert len(rings) == 1
    assert set(current) == set(wp.SLOT_SEARCH)
    assert all(r["better"] for r in rows)


def test_remember_character_keeps_the_list(sandbox):
    wp.remember_character({"name": "A", "surname": "B", "game": "forever"})
    wp.remember_character({"name": "A", "surname": "B", "game": "forever"})
    wp.remember_character({"name": "C", "surname": "", "game": "forever"})
    chars = wp.load_characters()
    assert len(chars) == 2


def test_off_hand_weapon_below_dual_wield_level_is_never_suggested():
    sword = dict(gear("WEAPON", wp.SWORD1, wp.WEAPON, stats={"STRENGTH": 20}), id=11, name="Off Sword")
    index = {"items": [sword], "sources": [("H", book((11, 100, 1)))]}
    rows, _cur = wp.slot_view(char("Warrior", 12), "OFF_HAND", index, W)
    assert len(rows) == 1 and not rows[0]["usable"] and not rows[0]["better"]
    assert rows[0]["why"] == "dual wield at level 20"
    rows, _cur = wp.slot_view(char("Warrior", 20), "OFF_HAND", index, W)
    assert rows[0]["usable"] and rows[0]["better"]


def test_one_set_of_gear_rules():
    """check_use is the only usability rule; the old can_use/find_upgrades path (which skipped the
    dual-wield level) is gone, so nothing can quietly use the wrong rules again."""
    for old in ("can_use", "find_upgrades", "slot_members", "class_members", "ah_gear_pool", "item_gear"):
        assert not hasattr(wp, old), old
