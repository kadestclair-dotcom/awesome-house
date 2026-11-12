# What's new in Beta 0.16.1, and why

*Nov 12 2026. Covers everything that changed since the Beta 0.15 download.*

**In short:** 0.16.1 is the first download that follows Blizzard's API rules, and it protects your data much better than 0.15 did. Saves can't be cut in half, and a damaged file no longer wipes a list. The app tries again when Blizzard is busy and tells you when an auction house didn't answer. Data from Blizzard is deleted after 30 days. Your own lists are never touched.

The Dungeons and Progress tabs from 0.15 work the same as before.

**[Download Beta 0.16.1](https://github.com/kadestclair-dotcom/awesome-house/releases)** · [How to update without losing anything](#updating-from-an-older-version) · [Full technical changelog](../CHANGELOG.md)

---

## Your data is safer

| What changed | Why |
| --- | --- |
| **Saves can't be cut in half.** The app writes each file to a temporary copy first, then swaps it in. | Before, a crash, power cut or full disk during a save could leave a half-written file. Now the previous version stays whole. |
| **A damaged file no longer wipes your list.** Your watchlist, characters, fishing log, recipes, spots, guide progress and tracked monsters each keep a backup (`<name>.bak`) that's put back automatically. The damaged file is kept too, as `<name>.corrupt-<date>`. | Before, a file that couldn't be read loaded as empty, and the next save overwrote it for good. |
| **Monster data updates are safe.** "Update data" keeps your current monster data until the new download has been read successfully. If a new release is laid out in a way the app doesn't understand, it says so in plain words and keeps your data. | Before, a bad or changed download could break the Monster Compendium, Dungeons and Progress tabs. |
| **No leftover download file on Windows.** A failed monster-data update no longer leaves `QuestieDB-Forever.zip.new` in your data folder. | The app forgot to close the downloaded file. Windows can't delete a file that's still open. |

## Steadier connection to Blizzard

| What changed | Why |
| --- | --- |
| **It tries again when Blizzard is busy.** Busy or server errors and dropped connections are retried up to 3 times, with a short wait in between (longer if Blizzard asks for it, never more than 30 seconds). | Before, one busy moment on Blizzard's side failed the whole price check. |
| **New in the status bar:** if some auction houses don't answer, you'll see e.g. *"14 of 15 auction houses answered - prices may be incomplete"*. That snapshot isn't saved to your price history, price alerts wait for complete data, and the missing houses are asked again after 5 minutes. | Before, a house that didn't answer was saved as empty for the hour. That skewed history, trends and alerts. A missing house can make a price look higher than it is. |
| **Connection problems are handled properly.** A dropped connection or timeout shows a clear message and is never remembered as "Blizzard has no data". | Before, a network blip could close the app, show "Something went wrong: timed out", or be remembered for days as missing data. |
| **A damaged or rejected access token is replaced automatically.** | Before, a damaged token file broke every lookup until you deleted it by hand. |

## Following Blizzard's API rules

Awesome House runs on Blizzard's API, and breaking its terms would put the app and everyone's API keys at risk. These changes bring it in line. The section numbers are from Blizzard's Developer API Terms of Use.

| What changed | Why |
| --- | --- |
| **Blizzard data is kept for at most 30 days.** Item names and stats, lookups, Progress snapshots, quest text and price history are cleared after 30 days and fetched again when needed. Your own lists are never touched. | §2.18 limits how long Blizzard data can be kept. Records saved by older versions have no date on them, so they're cleared the first time you start 0.16 or later. Your first lookups after updating will be a bit slower. |
| **No item data ships with the download any more.** Your copy fetches it with your own API key. | §2.5 and §2.18: Blizzard data can't be handed out to others. A few Classic-era items that Forever's API doesn't return may now show without a name. |
| **The first-run setup window no longer mentions donations.** *Support the project* is still in the Help menu. | §2.2: no asking for money before the app can be used. |
| **A privacy policy:** Help › Privacy policy..., `PRIVACY.txt` in the zip, and [PRIVACY.md](../PRIVACY.md) here. | §2.15: every app using the API must say how it uses player data. In short: everything stays on your PC. |
| **Credits.** The About box names Blizzard as the source of the data and uses Blizzard's trademark wording. It credits QuestieDB "by the Questie team and contributors, used with their permission", with a link to QuestieDB's license. | §2.13 requires crediting Blizzard. The Questie team gave permission to use QuestieDB and asked for exactly this credit. |
| **License notices in the zip:** `THIRD-PARTY-NOTICES.txt` and `PYTHON-LICENSE.txt`. | The app is built with Python, Tcl/Tk, OpenSSL and more, and their licenses require these notices to come with it. |

## Other fixes

- **Monster-data update check:** the app no longer offers an "update" that's actually an older QuestieDB release. It now compares version numbers properly (1.0.10 is newer than 1.0.9).
- **Upgrade results:** the Character tab now uses one set of rules for which gear your class can use, including the level you can start dual-wielding.

## In the zip

- **About Awesome House.pdf** is reprinted with everything above, plus the Dungeons and Progress tabs.
- **README.txt** now lists every file in the folder and explains how to update.

## Updating from an older version

1. Close Awesome House.
2. Unzip the new version over your old Awesome House folder and let it replace the files.

Your API key, watchlist, characters and other lists are kept. They live in their own files next to the app, and the zip doesn't contain any of them. If you unzipped into a new folder instead, copy `wow_price_config.json` (your key) and your list files over from the old folder.

## Coming next

- An error log file (`awesome_house.log`) to make bug reports easier. No extra pop-ups.
- Sturdier saving of price history, and faster background work so slow downloads don't hold up quick lookups.
- A daily check for new versions, so you know when an update is out.

Found a bug? [Open an issue](https://github.com/kadestclair-dotcom/awesome-house/issues) or use Support › Report a bug in the app.
