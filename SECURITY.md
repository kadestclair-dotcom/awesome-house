# Security

## Only download from the Releases page

The only official place to get Awesome House is the [Releases page](https://github.com/kadestclair-dotcom/awesome-house/releases) of this repository (github.com/kadestclair-dotcom/awesome-house/releases). If someone sends you an `AwesomeHouse.exe` from anywhere else, don't run it.

## How releases are made

Nobody builds or uploads release files by hand. When a new version is tagged, GitHub Actions:

1. checks out the code in this repository,
2. builds `AwesomeHouse.exe` with PyInstaller on a fresh GitHub-hosted Windows machine,
3. zips it with `README.txt`, `LICENSE.txt`, `FONTS-LICENSE.txt` and the About PDF,
4. records SHA-256 checksums in `SHA256SUMS.txt`,
5. signs a build record ([artifact attestation](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations)) that ties the zip and the exe to the exact commit and workflow that built them,
6. publishes them as a release.

The full recipe is in [`.github/workflows/release.yml`](.github/workflows/release.yml).

## Check a download

**Checksum (PowerShell):**

```powershell
Get-FileHash .\AwesomeHouse-*.zip
```

The printed hash should match the zip's line in `SHA256SUMS.txt` on the release.

**Build record (GitHub CLI):**

```powershell
gh attestation verify .\AwesomeHouse-Beta-0.16.zip --repo kadestclair-dotcom/awesome-house
```

A successful check means the file was built by this repository's workflow, not uploaded by a person.

## What the app connects to

- `*.api.blizzard.com` and `oauth.battle.net`: auction, item and character data, using the API key you created.
- `github.com` / `api.github.com`: only when you first open the Monster Compendium, Dungeons or Progress tab (it asks first) or click **Update data**, to download the public QuestieDB release.
- Your web browser opens Wowhead, Warcraft Wiki, PayPal or your email app only when you click a link or button.

There's no telemetry and no account. Everything else stays in the app's folder.

Full details are in the [privacy policy](PRIVACY.md).

## Antivirus false positives

Apps packed with PyInstaller are sometimes flagged by antivirus programs even when they're clean. If that happens, please don't turn your antivirus off or add an exception for a file you can't verify. Compare the checksum and build record above, and feel free to upload the file to [VirusTotal](https://www.virustotal.com/) for a second opinion.

## Run it from source instead

You don't have to run the exe at all. The app is plain Python and uses only the standard library:

1. Install Python 3.12 or newer from [python.org](https://www.python.org/downloads/).
2. On this repository's page, click **Code › Download ZIP** and unzip it into a folder of its own.
3. Double-click `wow_price_gui.pyw`.

It works the same as the exe and keeps its files in that folder.

## Reporting a problem

If you find a security problem, please don't post details publicly. Use GitHub's **Report a vulnerability** button on the Security tab (if enabled), or email the address listed in the app under **Support › Report a bug**.
