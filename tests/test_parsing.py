"""Text the user types and data Blizzard sends: gold amounts, catch lists, recipes, gear fields."""

import pytest

import wow_price as wp


# ---------------------------------------------------------------- money

@pytest.mark.parametrize("copper, text", [
    (0, "0c"), (5, "5c"), (100, "1s 0c"), (150, "1s 50c"), (10000, "1g 0s 0c"),
    (123456, "12g 34s 56c"), (12345678, "1,234g 56s 78c"), (99.6, "1s 0c"),
])
def test_fmt_gold(copper, text):
    assert wp.fmt_gold(copper) == text


@pytest.mark.parametrize("text, copper", [
    ("1g 50s", 15000), ("8s", 800), ("2.5g", 25000), ("75c", 75), ("3", 30000), ("1,000g", 10000000),
    ("1G 2S 3C", 10203), ("  4s  ", 400), ("1g50s", 15000),
])
def test_parse_gold(text, copper):
    assert wp.parse_gold(text) == copper


def test_parse_gold_blank_is_none():
    assert wp.parse_gold("   ") is None


@pytest.mark.parametrize("bad", ["lots", "5 gold", "1g abc", "g"])
def test_parse_gold_rejects_nonsense(bad):
    with pytest.raises(ValueError):
        wp.parse_gold(bad)


def test_gold_round_trip():
    for copper in (1, 99, 100, 101, 9999, 10000, 10001, 987654):
        text = wp.fmt_gold(copper).replace(",", "")
        assert wp.parse_gold(text) == copper


# ---------------------------------------------------------------- fishing catch / reagents / drops

def test_parse_catch_formats():
    text = "\n".join(["20 Raw Mackerel", "Raw Mackerel x20", "Raw Mackerel 20", "6303", "5 6303",
                      "6303 x5", "20x Raw Mackerel", "# a comment", "", "Oily Blackmouth"])
    assert wp.parse_catch(text) == [
        (20, "Raw Mackerel"), (20, "Raw Mackerel"), (20, "Raw Mackerel"), (1, "6303"), (5, "6303"),
        (5, "6303"), (20, "Raw Mackerel"), (1, "Oily Blackmouth")]


def test_parse_catch_two_numbers_larger_is_item_id():
    assert wp.parse_catch("6303 12") == [(12, "6303")]


def test_parse_reagents_with_fixed_prices():
    out = wp.parse_reagents("2 Raw Mackerel\n1 Mild Spices @ 10c\n# note\nCoarse Thread @ 1s")
    assert out == [(2, "Raw Mackerel", None), (1, "Mild Spices", 10), (1, "Coarse Thread", 100)]


def test_parse_reagents_bad_price():
    with pytest.raises(ValueError):
        wp.parse_reagents("1 Thread @ cheap")


def test_parse_drops_formats():
    assert wp.parse_drops("45% Raw Mackerel\nOily Blackmouth 30%\nFirefin 25") == [
        (45.0, "Raw Mackerel"), (30.0, "Oily Blackmouth"), (25.0, "Firefin")]


def test_parse_drops_rejects_line_without_share():
    with pytest.raises(ValueError):
        wp.parse_drops("Raw Mackerel")


# ---------------------------------------------------------------- names

@pytest.mark.parametrize("a, b", [
    ("Heavy Leather", "heavy leather"), ("  Heavy   Leather ", "Heavy Leather"),
    ("Kel’Thuzad's Robe", "Kel'Thuzad's Robe"), ("‘Quoted’", "'quoted'"),
])
def test_norm_name_ignores_case_space_and_curly_quotes(a, b):
    assert wp.norm_name(a) == wp.norm_name(b)


def test_norm_name_none():
    assert wp.norm_name(None) == ""


@pytest.mark.parametrize("name, surname, slug", [
    ("Example", "Person", "example-person"), ("Example", None, "example"), (" Two Words ", "", "two-words"),
    ("Zoë", "Ash", "zo%C3%AB-ash"),
])
def test_char_slug(name, surname, slug):
    assert wp.char_slug(name, surname) == slug


def test_category_label():
    assert wp.category_label(None, None) == "Uncategorized"
    assert wp.category_label("Trade Goods", None) == "Trade Goods"
    assert wp.category_label("Trade Goods", "Trade Goods") == "Trade Goods"
    assert wp.category_label("Trade Goods", "Leather") == "Trade Goods › Leather"


def test_quality_rank_orders_qualities():
    assert wp.quality_rank("POOR") < wp.quality_rank("COMMON") < wp.quality_rank("EPIC")
    assert wp.quality_rank("NOPE") is None


# ---------------------------------------------------------------- Blizzard's loose field shapes

@pytest.mark.parametrize("x, v", [
    (5, 5), (2.5, 2.5), ("5", 5.0), ("Requires Level 12", 12.0), ("1,250 Armor", 1250.0),
    ({"value": 7}, 7), ({"display_string": "+3 Stamina"}, 3.0), ({"display": {"value": 4}}, 4),
    (True, None), (None, None), ("none", None), ({}, None),
])
def test_val(x, v):
    assert wp._val(x) == v


@pytest.mark.parametrize("x, inv", [
    ({"type": "INVTYPE_CHEST"}, "CHEST"), ("2HWEAPON", "TWOHWEAPON"), ({"type": "HANDS"}, "HAND"),
    ("BACK", "CLOAK"), ("WEAPON_MAIN_HAND", "WEAPONMAINHAND"), (None, None), (5, None),
])
def test_norm_inv(x, inv):
    assert wp.norm_inv(x) == inv


def test_parse_gear_reads_every_field_shape():
    g = wp.parse_gear({
        "stats": [{"type": {"type": "STAMINA"}, "value": 5}, {"type": "stamina", "value": {"value": 2}},
                  {"type": {"type": "AGILITY"}, "value": "3"}, "junk"],
        "armor": {"value": 30}, "weapon": {"dps": {"value": 12.5}},
        "requirements": {"level": {"value": 10}}, "level": 15,
        "item_subclass": {"id": 3, "name": {"en_US": "Mail"}},
        "inventory_type": {"type": "INVTYPE_CHEST"}, "quality": {"type": "uncommon"},
    })
    assert g == {"stats": {"STAMINA": 7, "AGILITY": 3.0}, "armor": 30, "dps": 12.5, "req": 10, "ilvl": 15,
                 "sub_id": 3, "sub": "Mail", "inv": "CHEST", "q": "UNCOMMON"}


def test_parse_gear_survives_garbage():
    g = wp.parse_gear(None)
    assert g["stats"] == {} and g["armor"] == 0 and g["req"] is None and g["inv"] is None
    assert wp.parse_gear({"required_level": "Requires Level 8"})["req"] == 8
