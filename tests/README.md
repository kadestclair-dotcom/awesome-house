# Awesome House tests

About 290 automatic checks that run in roughly 20 seconds. They cover every module and every tab,
so you can make a change and find out straight away whether something else broke.

## Running them

- **Double-click `run_tests.bat`** in the app folder. It installs `pytest` the first time.
- `run_tests.bat fast` skips the window tests and takes about 2 seconds. Use it while you're coding.
- `run_tests.bat gui` runs only the window tests.
- From a terminal: `python -m pytest`, or `python -m pytest -k sell` to run only the tests with "sell" in their name.

The end of the output shows a summary. `passed` is good. `FAILED` names the test and shows what it
expected next to what it got.

## Safe to run

- Your real `wow_price_config.json`, watchlist, price history, characters and caches are never read
  or changed. Each test gets its own empty temporary folder.
- The network is blocked, so nothing talks to Blizzard or GitHub. Blizzard is replaced by a fake
  (`FakeApi` in `conftest.py`) that answers with data written in the tests.

## What's covered

| File | What it checks |
|---|---|
| `test_parsing.py` | Gold amounts (`1g 50s`), catch lists, reagent lists, drop tables, item-name matching, Blizzard's loose field formats |
| `test_item_lookup.py` | The Beta 0.14 name bug ("Heavy Leather" → Dwarven Leather Pants): paging, exact matches, cache self-repair, and the shipped `item_cache.json` |
| `test_prices.py` | Price summary math, the Forever auction download (several houses, duplicates, commodities), history and trends, the sell helper, best time to sell, the flip finder, crafting profit, fishing, CSV export, login token |
| `test_character.py` | Reading a character, armor, weapon, shield and dual-wield rules for every class, Efficiency scoring, the upgrade tables |
| `test_monsters.py` | The QuestieDB decoder (CBOR/TOC), waypoints, factions incl. Skyborne, spawn spots, every Compendium lookup, loading and update checks |
| `test_dungeons_and_loot.py` | Travel notes (and your own copy overriding them), level ranges, entrances, dungeon quests and drops, the loot finder |
| `test_progress.py` | Reading a character's progress, quest states (done, now, gray, later, closed), zones, What to do next, Tonight's route order, quest descriptions, guild crafters |
| `test_real_data.py` | The same features against your real QuestieDB index and saved character. Runs only on your PC, because those files are never committed |
| `test_gui.py` | Opens the real window with fake data, visits every tab, runs a search and a watchlist check, opens every tool window, and uses the Help and Export menus. Fails if anything raises an error |
| `test_release.py` | Everything compiles, the version matches in the app, `build_exe.bat` and both READMEs, the build includes every data file, `.gitignore` blocks personal files, and nothing secret is in the code |

## Known bugs

A test marked `xfail` describes a bug that has been found but not fixed yet. It shows up as `x` and
doesn't count as a failure. When the bug is fixed, that test starts to "unexpectedly pass" and the run
fails on purpose, as a reminder to remove the `xfail` line.

## Adding a test

Copy a nearby test and change it. Plain `assert` lines are all you need. Useful helpers in
`conftest.py`:

- `FakeApi({path: answer})` gives Blizzard answers.
- `book((item id, price, qty), ...)` builds an auction house.
- `use_sources([...])` makes the app use those houses.
- `know_item(id, name)` teaches the app an item name.
- The `db` fixture is a tiny monster database, and `snapshot()` is a level 8 Horde shaman.
