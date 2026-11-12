Awesome House - Privacy Policy
==============================

Last updated: November 12, 2026

Awesome House is a free Windows app made by one person, Kade. This policy
covers the app and the data it gets from Blizzard's API. Kade runs no server
for the app: nothing you do in it is sent to Kade or to anyone else, and there
is no account, no tracking and no analytics.


Where the data comes from
-------------------------
Auction, item and character data comes from Blizzard Entertainment's API,
using the free API client (Client ID and Secret) that you create yourself at
develop.battle.net. That data is provided to you "as is", exactly as Blizzard
sends it, without any promise that it is complete, current or correct.
Blizzard's handling of its own data is described in the Blizzard Entertainment
Online Privacy Policy:
https://www.blizzard.com/en-us/legal/a4380ee5-5c8d-4e3b-83b7-ea26d01a9918/blizzard-entertainment-online-privacy-policy
This policy is meant to be consistent with it.

Awesome House is a fan-made tool, not affiliated with or endorsed by Blizzard.


What is stored, and where
-------------------------
Everything is stored only on your computer, in the app's own folder. Nothing
is uploaded anywhere.

- Your API Client ID and Secret, in wow_price_config.json (plain text), and a
  short-lived access token in .wow_price_cache. They are sent only to
  Blizzard (oauth.battle.net) to log in. Don't share that file or the folder.
- Data from Blizzard: auction prices and price history, item names and stats,
  characters you look up and their progress, quest text, and your guild's
  crafter list. Each piece is kept for at most 30 days after it was fetched,
  as Blizzard's Developer API Terms require, then deleted automatically. It
  is fetched again when you need it. The guild crafter list is refreshed after
  1 day.
- Your own lists and notes: watchlist and price alerts, fishing sessions,
  recipes, fishing spots, guide progress and tracked monsters. They stay
  until you delete them.
- Monster data from QuestieDB, downloaded from GitHub when you choose to.


Other players
-------------
When you look up a character or use Guild crafters, the app reads public
profile data from Blizzard's API: character names, levels, classes, guild
membership and professions. It shows that data to you, keeps it only on your
computer for at most 30 days (the guild list is read again after 1 day), and
never shares, sells or publishes it.


What the app never does
-----------------------
- It never asks for, sees or stores your Battle.net password.
- It never sells, shares or transfers any data. Donations unlock nothing.
- It contains no ads and does not use Blizzard's data for marketing.


Connections the app makes
-------------------------
- Blizzard (*.api.blizzard.com, oauth.battle.net): logging in with your own
  API client, and reading game, auction and character data.
- GitHub (github.com, api.github.com): downloading QuestieDB monster data
  when you choose to, and checking for a newer version of it.
- Your web browser opens Wowhead, Warcraft Wiki, PayPal, GitHub or your email
  app only when you click a link or button. Those sites have their own
  privacy policies.
- Report a bug opens your own email app; only what you choose to send reaches
  Kade.


The website and downloads
-------------------------
Downloads are hosted by GitHub, whose own privacy statement applies. The
project's web page loads fonts from Google Fonts, which receives your IP
address when the page loads.


Children
--------
Awesome House is not designed for or marketed to children under 13.


Deleting your data
------------------
Delete the app's folder to remove everything it stored. To revoke the app's
access to Blizzard's API, delete your API client at develop.battle.net.


Changes and questions
---------------------
Changes to this policy are listed in the app's release notes, and the date
above is updated. Questions: open an issue at
https://github.com/kadestclair-dotcom/awesome-house/issues
