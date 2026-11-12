Awesome House  -  Beta 0.15
===========================
Know what it's worth before you list it.
Copyright (c) 2026 Kade. All rights reserved. Free for personal use.

A Windows desktop companion app that reads the World of Warcraft auction house
for you. Built for WoW: Forever. Retail is supported too.

This is a beta: features are still being added, and you may run into bugs.
Please report them (see FOUND A BUG? below).

For the full illustrated tour, open "About Awesome House.pdf".


WHAT'S IN THIS FOLDER
---------------------
  AwesomeHouse.exe                    The app. Double-click to run.
  About Awesome House.pdf             Feature tour, privacy and limits (opens in any PDF viewer)
  README.txt                          This file
  LICENSE.txt                         What you can and can't do with the app


WHAT IT DOES
------------
  Search        Browse auction house categories, filter by quality, level and price,
                and see the price at each auction house side by side.
  Watchlist     Day / Week / Month trends, price history chart, sell helper
                (payout after the 5% cut), best time to sell, and price alerts.
  Character     Look up a character, scan every gear slot, and see which items for
                sale are an upgrade your class can actually use (Upgrade %).
  Professions   Every Blizzard recipe priced at current auction prices; material
                prices and gold-per-hour for gathering sessions.
  Guides        Leveling guides 1-300 for all 12 professions, priced live, with the
                cheapest option marked. Progress is saved.
  Monster       Every monster in each region, what it drops (priced on
  Compendium    the auction house), and the quests that need it or its drops.
                Names link to Wowhead or Warcraft Wiki. Track the monsters
                you're farming, with a kill counter and notes.
  Dungeons      NEW. Every Forever dungeon and raid in the monster data:
                where the entrance is, a route there for each faction,
                the monsters inside, what they drop (priced on the auction
                house), and the quests that send you in.
  Progress      NEW. Load a Forever character to see quests done per zone,
                the quest log, milestones, reputations, PvP, dungeon and
                raid progress and professions, plus what to do next. My
                characters lists everyone you've loaded side by side.
                Tonight's route orders your open quests into stops with
                waypoints. Guild crafters shows who can make a recipe.
  Also new      Copy waypoint (for the TomTom addon) on monsters, quest
                givers and dungeon entrances. Upgrades from dungeons on the
                Character tab scores dungeon drops against your gear.
  Tools         Flip finder, custom crafting recipes, fishing spot planner,
                CSV export.


GET STARTED (about 5 minutes)
-----------------------------
  1. Unzip this folder somewhere of its own, for example Desktop\Awesome House.
     The app saves its files next to the exe, so keep it in its own folder.
     Don't run it from inside the zip.

  2. Double-click AwesomeHouse.exe.
     Windows may say "Windows protected your PC". Click "More info",
     then "Run anyway". The first launch takes a few seconds.

  3. A "Blizzard API setup" window opens. Click its button to go to
     develop.battle.net, sign in with your Battle.net account, and choose
     "Create Client". Fill in the form like this:

       Client Name ...... anything, e.g. Awesome House
       Redirect URLs .... leave empty
                          (only used by websites with a "Log in with
                          Battle.net" button; this app never uses it.
                          If the form won't save without one, enter
                          http://localhost)
       Service URL ...... leave empty, or tick "I do not have a service
                          URL for this client" if you see it
                          (it asks for a website; you don't need one)
       Intended Use ..... Personal desktop app to check World of Warcraft
                          auction house prices.

     Save, open your new client, and paste its Client ID and Client Secret
     into the app's setup window. You only do this once. Treat the Client
     Secret like a password.

     If saving the form gives an error, wait a few minutes and try again.
     Blizzard's form sometimes fails for reasons unrelated to what you typed.

  4. Search for an item, add it to your Watchlist, and set an alert.
     Leave the app open and it checks prices again every hour.


CHECK YOUR DOWNLOAD
-------------------
  Only download Awesome House from its official page:
      github.com/kadestclair-dotcom/awesome-house/releases
  Each release lists a SHA256SUMS.txt file. To check your zip, open
  PowerShell in the folder you downloaded it to and run:

      Get-FileHash .\AwesomeHouse-*.zip

  The long code it prints should match the one in SHA256SUMS.txt.
  Every release is built by GitHub from the public source code, with a
  signed record of the build (see SECURITY.md on the GitHub page).


YOUR PRIVACY
------------
  The full privacy policy is in PRIVACY.txt, next to the app.
  - You use your own free Blizzard API key. Nobody else's key is in this app.
  - The app never asks for your Battle.net password.
  - Your key, watchlist, characters, guide progress, price history and tracked
    monsters are saved only on your computer, in the app's folder.
  - The app talks to Blizzard's servers, and to GitHub only to download the
    free QuestieDB monster data: once when you first open the Monster
    Compendium (it asks first, about 14 MB) and when you click Update data.
    Wowhead and Warcraft Wiki open in your browser only when you click a link.


THINGS TO KNOW
--------------
  - The app isn't code-signed, so Windows shows a warning (see step 2). Some
    antivirus programs also wrongly flag apps built with PyInstaller. Please
    don't turn your antivirus off for it: check the zip as described above,
    or run the app from its source code instead (see SECURITY.md on the
    GitHub page).
  - Your API secret is saved as plain text in wow_price_config.json next to the
    app. Don't zip up and share your folder once you've set it up. If it leaks,
    delete the client at develop.battle.net and make a new one.
  - Blizzard's WoW: Forever API isn't officially documented, so parts of the app
    could break if Blizzard changes it.
  - Blizzard is missing data for many Classic-era items, so some items will have
    no name, stats or upgrade score.
  - Price history only records while the app is open, so trends take time to fill in.
  - Prices update about once an hour, not in real time.
  - The 5% auction house cut and the upgrade scores are estimates.
  - Forever characters only show up in lookups from level 10, after logging out.
  - The Monster Compendium uses QuestieDB, the Questie addon's community
    database. Its Forever data is still filling in, so some new monsters,
    drops and quests are missing. Drop chances are only known for quest items.
    It covers WoW: Forever only.
  - The Dungeons tab's travel routes are written from Classic-era geography
    and haven't been checked in Forever yet. Routes for Forever's new
    dungeons aren't recorded. Click Edit routes in the tab to correct them
    (it opens dungeon_travel.json next to the app).
  - The Progress tab shows what Blizzard last saved for a character, which
    updates when the character logs out. Its quest suggestions depend on
    QuestieDB's quest list, so a quest can be missing or listed too early.


SUPPORT THE PROJECT
-------------------
  The app is free. If it saves you gold and you'd like to say thanks,
  you can donate at:  https://paypal.me/keedoyesyes
  (also under Help > Support the project, or Support > Donate in the app).
  Donations are optional and don't unlock anything.


FOUND A BUG?
------------
  Open an issue at github.com/kadestclair-dotcom/awesome-house/issues, or click
  Support > Report a bug in the app: your email app opens with a short report
  ready to fill in, and the same text is copied so you can paste it anywhere.
  Or email:  kadestclair@gmail.com
  Screenshots help. Never include your Client Secret.


LICENSE IN SHORT
----------------
  Free for your own personal use. Please don't re-share copies, sell, modify
  or rebrand it. Point friends to the official download page instead:
      github.com/kadestclair-dotcom/awesome-house/releases
  Full terms are in LICENSE.txt.


Auction, item and character data comes from Blizzard Entertainment's API.
Awesome House is a fan-made tool. Not affiliated with or endorsed by Blizzard Entertainment.
World of Warcraft and Blizzard Entertainment are trademarks or registered trademarks of
Blizzard Entertainment, Inc., in the U.S. and/or other countries.
Monster Compendium, Dungeons and Progress data: QuestieDB (github.com/Questie/QuestieDB)
by the Questie team and contributors, used with their permission. Downloaded separately;
it stays under QuestieDB's license: https://github.com/Questie/QuestieDB/blob/master/LICENSE.md
Pixel fonts Pixelify Sans and VT323 are used under the SIL Open Font License 1.1.
