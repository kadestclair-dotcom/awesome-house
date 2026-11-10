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
gh attestation verify .\AwesomeHouse-Beta-0.14.zip --repo kadestclair-dotcom/awesome-house
```

A successful check means the file was built by this repository's workflow, not uploaded by a person.

## What the app connects to

- `*.api.blizzard.com` and `oauth.battle.net`: auction, item and character data, using the API key you created.
- `github.com` / `api.github.com`: only when you open the Monster Compendium for the first time (it asks first) or click **Update data**, to download the public QuestieDB release.
- Your web browser opens Wowhead, Warcraft Wiki, PayPal or your email app only when you click a link or button.

There's no telemetry and no account. Everything else stays in the app's folder.

## Antivirus false positives

Apps packed with PyInstaller are sometimes flagged by antivirus programs even when they're clean. If that happens, compare the checksum and build record above, and feel free to upload the file to [VirusTotal](https://www.virustotal.com/) to see a second opinion.

## Reporting a problem

If you find a security problem, please don't post details publicly. Use GitHub's **Report a vulnerability** button on the Security tab (if enabled), or email the address listed in the app under **Support › Report a bug**.
