# Publishing Awesome House on GitHub

A one-time setup, then about two minutes per release. These steps use **GitHub Desktop**, so you never need the command line.

## One-time setup

1. **Make a GitHub account** at [github.com/signup](https://github.com/signup) if you don't have one. Turn on two-factor authentication (Settings › Password and authentication). It protects the account that publishes your app.
2. **Install GitHub Desktop** from [desktop.github.com](https://desktop.github.com/) and sign in.
3. **Add this folder as a repository:** File › Add local repository › choose this `awesome-house-github` folder. When it says it isn't a Git repository yet, click **create a repository** and name it exactly `awesome-house` (the app, README and license all link to github.com/kadestclair-dotcom/awesome-house). Leave "Git ignore" and "License" as **None** (both files are already here).
4. **Check what will be uploaded.** The Changes list should show only the app source, `item_*.json`, the icon, `package\`, `docs\`, `.github\` and the README/LICENSE files. If you ever see `wow_price_config.json`, **stop**: that's your Blizzard secret. (`.gitignore` is set up to keep it out.)
5. **First commit:** type "Awesome House Beta 0.14" in the Summary box and click **Commit to main**.
6. **Publish:** click **Publish repository**. **Untick "Keep this code private"**, since the trust features only work on a public repository. Click Publish.
7. **Add the automatic build.** GitHub needs two files inside a hidden `.github` folder, which are waiting in the `setup-github` folder here. On github.com, in your repository, click **Add file › Create new file** and:
   - type the name `.github/workflows/release.yml` (typing the slashes creates the folders), open `setup-github\release.yml` in Notepad, copy everything, paste it in, and click **Commit changes**;
   - do the same with the name `.github/ISSUE_TEMPLATE/bug_report.md` and the contents of `setup-github\bug_report.md`.

   Then click **Fetch origin › Pull origin** in GitHub Desktop so your folder has them too. After that you can delete the `setup-github` folder.
8. On github.com, open the repository › **Settings**:
   - *General › Features*: tick **Issues**.
   - *Security › Advanced Security* (or *Code security*): turn on **Private vulnerability reporting**.
   - *Actions › General*: make sure Actions are allowed.

## Making a release

1. Put the new version number in every place it appears (the tests check these):
   - `APP_VERSION` near the top of `wow_price_gui.pyw` (e.g. `"Beta 0.16.1"`), plus the first line of that file
   - `VERSION` in `build_exe.bat` (e.g. `Beta-0.16.1`), for local builds
   - `README.md`, `package/README.txt`, `SECURITY.md` and `docs/index.html`
   - a new section at the top of `CHANGELOG.md`
2. In GitHub Desktop, commit the changes with a short summary, then **Push origin**.
3. In the **History** tab, right-click the new commit › **Create Tag…**, name it like `v0.16.1-beta` (**lowercase v**: the build only starts for tags beginning with `v`), then **Push origin** again. Pushing the tag starts the build. Get the name right before pushing: GitHub Desktop can't delete a tag once it's pushed, and Windows treats `V0.16.1-beta` and `v0.16.1-beta` as the same name.
4. On github.com, open the **Actions** tab. The *Build and release* run takes about 3–5 minutes. When it turns green, the **Releases** page has `AwesomeHouse-Beta-0.16.1.zip` and `SHA256SUMS.txt`. Beta versions are marked *Pre-release* automatically.
5. Open the new release, click **Edit**, and add the "What's new" notes under the download section. The build writes only the download and checking part.
6. Optional: upload the zip to [virustotal.com](https://www.virustotal.com/) and paste the result link into the release notes (Edit release).
7. Send friends the **Releases page link** (github.com/kadestclair-dotcom/awesome-house/releases), not the zip itself.

To test a build without publishing, use **Actions › Build and release › Run workflow**. The zip appears under *Artifacts* on that run's page.

## Keep the working copy and the GitHub copy in sync

This folder is now your project. Make changes here (or copy changed files in from your old `wowprice` folder), then commit and push. Keep your personal files (config, watchlist, history) in a separate folder where you run the app day to day.

## Later: removing the Windows warning

The "Windows protected your PC" warning goes away only with code signing. Microsoft's Artifact Signing (about $9.99 a month, open to individual developers in the USA and Canada) can be added to the workflow once you want it. Even then, the warning fades gradually as more people download signed releases.
