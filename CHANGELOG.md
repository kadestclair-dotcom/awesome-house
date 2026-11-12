# Changelog

## Beta 0.16.1 — up-to-date documents (Nov 12 2026)

The app itself is the same as 0.16; this release brings the files that ship with it up to date.
- **About Awesome House.pdf** is reprinted from the current website: the Dungeons and Progress tabs,
  the 30-day data limit, the privacy policy, the QuestieDB credit and Blizzard's trademark wording.
- **README.txt in the zip** lists every file in the folder (PRIVACY.txt, THIRD-PARTY-NOTICES.txt,
  PYTHON-LICENSE.txt and FONTS-LICENSE.txt were missing), explains how to update from an older version
  without losing your data, and says that data from Blizzard is deleted after 30 days.
- `docs/publishing.md`: every place the version number goes, how to tag a commit in GitHub Desktop
  (lowercase `v`), and adding the release notes.

## Beta 0.16 — Windows fix (Nov 12 2026)

- **Monster data updates no longer leave a `QuestieDB-Forever.zip.new` file behind on Windows.** The
  downloaded zip was never closed, and Windows can't delete a file that is still open. It is now always
  closed, whether the update works or not.
- Beta 0.16 is the first release with everything below. (The Beta 0.15 download was built before these
  changes and still bundled Blizzard item data.)
- Tests: 374 passed, 9 skipped (Linux, Python 3.12 and 3.10, GUI included); the GitHub Windows run is green.

## Beta 0.16 — compliance with Blizzard's Developer API Terms (Nov 12 2026)

From the licenses and permissions check. Section numbers are the items under Section 2 of Blizzard's
Developer API Terms of Use (last updated Oct 1 2019).

### Changed (users will notice)
- **Data from Blizzard is kept for at most 30 days (§2.18).** Item names and stats, item-name lookups,
  recent character lookups, Progress snapshots, quest text, cached snapshots and price history carry the
  time they were fetched and are deleted after 30 days; they are fetched again when needed. The cleanup runs
  in the background shortly after start and once a day while the app is open. Records saved by older
  versions have no time stamp and are removed on the first start, so the first lookups after updating are
  slower. Price history keeps 30 days; the Month trend still works. The user's own lists (watchlist,
  alerts, fishing log, recipes, spots, guide progress, tracked monsters) are not touched.
- **No item data ships with the app any more (§2.5, §2.18).** `item_info.json`, `item_stats.json` and
  `item_cache.json` are no longer in the repo, the exe or the zip, and aren't copied out on first run. Each
  user's app fetches them with their own key. They're now git-ignored per-user caches. Some Classic-era
  items that Forever's API doesn't return now show without a name.
- **The first-run API setup window no longer asks for a donation (§2.2).** Help › Support the project
  and the Support button are unchanged.
- **Privacy policy (§2.15):** `PRIVACY.md`, `PRIVACY.txt` in the zip, Help › Privacy policy..., and links
  from the README, SECURITY.md, the package README and the website.

### Added
- **QuestieDB credit and license.** The Questie team gave permission to use QuestieDB (Nov 12 2026), asking that QuestieDB and its license be credited explicitly. The About box, LICENSE, THIRD-PARTY-NOTICES.txt, both READMEs and the website now credit "QuestieDB by the Questie team and contributors, used with their permission" and link https://github.com/Questie/QuestieDB/blob/master/LICENSE.md.
- About box, README, package README, license and website name Blizzard as the source of the data
  (§2.13) and use Blizzard's trademark wording: "World of Warcraft and Blizzard Entertainment are
  trademarks or registered trademarks of Blizzard Entertainment, Inc., in the U.S. and/or other countries."
- `THIRD-PARTY-NOTICES.txt` in the zip (Tcl and Tk licenses verbatim, as they require). Both builds copy
  Python's own `LICENSE.txt` in as `PYTHON-LICENSE.txt`; it holds the licenses of Python, OpenSSL, libffi,
  bzip2, zstd and Tcl/Tk. The CI build stops if it's missing.
- `docs/FONTS-LICENSE.txt`, linked from the website footer.
- `package/LICENSE.txt` is the current license again (it was an older Beta 0.14 copy).

### Tests
- New: `tests/test_data_ttl.py` (the 30-day limit), release checks for the notices, privacy policy,
  trademark and source wording, no bundled Blizzard data, and the setup window. Existing tests now use
  recent time stamps.
- 373 passed, 8 skipped on Python 3.12 and 3.10 (GUI included, Linux/Xvfb).

### Dry run on real data
On a copy of the working folder's data, the first cleanup removes 3,297 item names, 4,297 item stats,
27 name lookups, 1 recent character lookup and 1 cached quest text (all unstamped). It keeps all 459 price
points (under 30 days old), the saved Progress character and the 17-item watchlist.

## Beta 0.16 — hardening, Phase A: correctness and data safety (Nov 12 2026)

Nothing changes on screen except one new status-bar note (A8). File names and file formats are the
same as before, so existing setups keep working. The finding IDs (D1…) refer to the hardening review.

### Fixed
- **A1 · Monster data update check (D1).** `newer_release()` compared versions as text with `!=`, so an
  older QuestieDB tag was announced as an update. Versions are now compared as numbers
  (1.0.10 is newer than 1.0.9), and a version it can't read never counts as newer.
- **A2 · One set of gear rules (D2).** `can_use()` skipped the dual-wield level that `check_use()`
  enforces. Its only caller, `find_upgrades()`, wasn't used by the window or the command line, so both
  were removed with their helpers (`slot_members`, `class_members`, `ah_gear_pool`, `item_gear`,
  `_search_all`, `_member`): about 230 lines.
- **A3 · Safe saves (D4, D7).** Every JSON file the app writes (config, token, watchlist, fishing log,
  characters, recipes, spots, guide progress, tracking list, Progress snapshots, caches, the monster
  index, the QuestieDB zip and the font files) is written to a temporary file next to it and then
  swapped in. A crash, power cut or full disk mid-save leaves the previous file whole. On Windows the
  swap is retried for up to 2 seconds while antivirus or the search indexer holds the file.
- **A4 · Damaged files no longer wipe data (D3).** Before, a file that couldn't be read loaded as
  empty, and the next save overwrote it. Now the damaged file is kept as `<name>.corrupt-<date-time>`.
  The user's own data files also keep their previous version as `<name>.bak`, which is put back
  automatically. Caches simply start over. No message is shown (decision Q1); a log line is written.
- **A5 · Access token (D5).** A damaged `token.json` no longer breaks every lookup. If Blizzard
  rejects a token before its expiry time (401), the app gets a new one once and retries.
- **A6 · Network failures (D8).** "Could not reach Blizzard API" is now a `NetworkError` instead of
  `SystemExit`, and read timeouts and dropped connections count as one too; before, they surfaced as
  "Something went wrong: timed out". The messages are the same. A network failure is never cached as
  "Blizzard has no data", and a failed login over the network no longer says to check your key.
- **A7 · Retries and timeouts (D9, D10).** Busy (429) and server errors (500–504) and dropped
  connections are retried up to 3 times, with waits that double each time (0.5 s, 1 s, plus a
  little random jitter), or as long as Blizzard's `Retry-After` asks, up to 30 s. Small calls time out
  after 30 s; auction downloads keep 120 s.
- **A8 · An auction house that doesn't answer (D6).** Before, it was saved as empty for the hour, and
  its missing listings went into price history, trends and alerts. Now a snapshot missing houses isn't
  saved to the hour-long cache, adds no history point, and is asked for again after 5 minutes. Price
  alerts wait for whole data, because a missing house can make a price look higher than it is.
  **New on screen (decision Q2):** the status bar says, for example, "14 of 15 auction houses
  answered - prices may be incomplete", in the main window and in the Monster and Dungeon tabs.
- **A9 · QuestieDB updates (D13, D12).** "Update data" keeps the old zip and monster index until the
  new release has been read successfully. A release in a layout this version can't read is reported
  in plain words ("…Your current monster data is kept.") instead of a raw `KeyError`. Picking one of
  several items that share a name now uses the API's region instead of always US.

### Added
- `.gitignore` blocks `*.bak`, `*.corrupt-*`, `*.tmp` and `*.log`. The config's backup holds the API
  secret, so it must never be committed.
- Tests: `tests/test_storage.py` (safe saves, backups, damaged files) and `tests/test_network.py`
  (retries, `Retry-After`, timeouts, tokens, network failures), plus new cases in `test_character`,
  `test_monsters`, `test_prices`, `test_item_lookup`, `test_gui` and `test_release`. The known-bug
  xfail for `newer_release()` is now a normal passing test.

### Test results
- Before: 286 passed, 8 skipped, 1 xfailed (Python 3.12 and 3.10 with Tk under Xvfb); 281 passed,
  1 skipped, 1 xfailed in the PC copy (Python 3.10, no Tk).
- After: 338 passed, 8 skipped (3.12 and 3.10 with Tk). PC copy: see the project notes for this
  change.

### Not verified
- Against the live Blizzard API: real 429/503 replies, and how a real failing house looks.
- On Windows itself: the file swap under antivirus, and the new status-bar note in the real window.
  The GUI tests run on Linux under a virtual screen.
