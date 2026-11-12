"""Release checks: the things that go wrong when a version is packaged, not when it runs.
Version numbers that disagree, files the build forgets, personal data that slips into git."""

import ast
import json
import os
import py_compile
import re
import subprocess

import pytest

from conftest import ROOT

SOURCES = ["wow_price.py", "wow_monsters.py", "wow_dungeons.py", "wow_loot.py", "wow_progress.py",
           "wow_price_gui.pyw"]


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("name", SOURCES)
def test_source_compiles(name, tmp_path):
    py_compile.compile(os.path.join(ROOT, name), cfile=str(tmp_path / "x.pyc"), doraise=True)


def app_version():
    m = re.search(r'^APP_VERSION = "([^"]+)"', read("wow_price_gui.pyw"), re.M)
    assert m, "APP_VERSION not found"
    return m.group(1)


def test_version_matches_everywhere():
    v = app_version()                                          # "Beta 0.15"
    assert re.fullmatch(r"(Beta )?\d+\.\d+(\.\d+)?", v)
    bat = re.search(r"^set VERSION=(\S+)", read("build_exe.bat"), re.M)
    assert bat and bat.group(1) == v.replace(" ", "-"), "VERSION in build_exe.bat"
    assert v in read("README.md"), "README.md"
    assert v in read(os.path.join("package", "README.txt")), "package/README.txt"


BLIZZARD_DATA = ["item_info.json", "item_stats.json", "item_cache.json"]


def test_build_bundles_every_data_file_the_app_reads():
    needed = ["dungeon_travel.json", "ah_coin_icon.ico"]
    for script in ("build_exe.bat", os.path.join(".github", "workflows", "release.yml")):
        path = os.path.join(ROOT, script)
        if not os.path.exists(path):
            continue
        text = read(script)
        for f in needed:
            assert f in text, f"{f} missing from {script}"
        for f in needed:
            assert os.path.exists(os.path.join(ROOT, f)), f


@pytest.mark.parametrize("script", ["build_exe.bat", ".github/workflows/release.yml"])
def test_build_ships_no_blizzard_data(script):
    """Blizzard API Terms 2.5 and 2.18: item data comes from each user's own API key, not the download."""
    text = read(script)
    for f in BLIZZARD_DATA:
        assert f not in text, f"{f} still bundled by {script}"


def test_blizzard_data_files_are_git_ignored():
    ignored = read(".gitignore").split()
    for f in BLIZZARD_DATA:
        assert f in ignored, f


def test_gitignore_blocks_personal_files():
    ignored = read(".gitignore")
    for f in ["wow_price_config.json", ".wow_price_cache/", "watchlist.json", "price_history.db",
              "characters.json", "character_progress.json", "monster_tracking.json", "fishing_sessions.json",
              "guide_progress.json", "recipes.json", "fishing_spots.json"]:
        assert f in ignored, f


def test_gitignore_blocks_backups_and_damaged_copies():
    """Safe saves leave <name>.bak and <name>.corrupt-<time> copies of personal files (the config
    holds the API secret), plus .tmp files if a save is interrupted. None of them may be committed."""
    ignored = read(".gitignore").split()
    for pattern in ("*.bak", "*.corrupt-*", "*.tmp", "*.log"):
        assert pattern in ignored, pattern


def test_personal_files_are_not_tracked():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = set(out.stdout.split())
    personal = {"wow_price_config.json", "watchlist.json", "price_history.db", "characters.json",
                "character_progress.json", "monster_tracking.json", "fishing_sessions.json"}
    assert not tracked & personal
    assert not [t for t in tracked if t.startswith(".wow_price_cache/")]


def test_no_secrets_in_shipped_files():
    """Nothing that looks like a Blizzard client secret or token in the source or seed files."""
    pattern = re.compile(r"""(client_secret|access_token)["']?\s*[:=]\s*["'][A-Za-z0-9]{20,}""")
    for name in SOURCES + ["dungeon_travel.json", "README.md"]:
        assert not pattern.search(read(name)), name


def test_data_paths_live_next_to_the_app():
    """Every file the app writes must sit in its own folder (HERE), never somewhere else on the PC."""
    import wow_price as wp
    for name, val in vars(wp).items():
        if name.endswith(("_PATH", "_DB", "_DIR")) and isinstance(val, str) and name != "BUNDLE_DIR":
            assert os.path.isabs(val), name


def test_seed_json_files_parse():
    json.loads(read("dungeon_travel.json"))


def test_gui_has_no_leftover_debug_prints():
    tree = ast.parse(read("wow_price_gui.pyw"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "breakpoint"]
    assert not calls, "breakpoint() left in the window app"


# ---------------------------------------------------------------- Blizzard API terms and notices

TM_LINE = ("World of Warcraft and Blizzard Entertainment are trademarks or registered trademarks of "
           "Blizzard Entertainment, Inc., in the U.S. and/or other countries.")
SOURCE_LINE = "data comes from Blizzard Entertainment's API"
NOTICE_FILES = ["LICENSE", "package/LICENSE.txt", "package/README.txt", "README.md", "docs/index.html"]


def _function_source(path, name):
    import ast
    src = read(path)
    node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, node)


def test_setup_window_asks_for_no_donation():
    """Blizzard API Terms 2.2: no window asking for donations before the app can be used."""
    setup = _function_source("wow_price_gui.pyw", "ask_credentials")
    assert "DONATE_URL" not in setup and "paypal" not in setup.lower() and "support" not in setup.lower()


def test_blizzard_is_named_as_the_data_source():
    """Blizzard API Terms 2.13: the app names Blizzard as the source of the data."""
    assert SOURCE_LINE in _about_text()
    for f in ["README.md", "package/README.txt", "docs/index.html"]:
        assert SOURCE_LINE in " ".join(read(f).split()), f


def _about_text():
    """The About box's text: its string pieces joined, as Python joins them."""
    import ast
    node = ast.parse(_function_source("wow_price_gui.pyw", "open_about"))
    return "".join(n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))


def test_about_box_credits_blizzard_properly():
    about = " ".join(_about_text().split())
    assert TM_LINE in about and SOURCE_LINE in about


@pytest.mark.parametrize("f", NOTICE_FILES)
def test_trademark_credit_uses_blizzards_wording(f):
    text = " ".join(read(f).split())
    assert TM_LINE in text, f
    assert "World of Warcraft is a trademark of Blizzard Entertainment, Inc." not in text, f


def test_shipped_license_is_the_current_one():
    assert "Beta 0.14" not in read("package/LICENSE.txt")


def test_release_zip_carries_third_party_notices():
    """The exe bundles Python, OpenSSL, Tcl/Tk and more: their licenses require the notices to ship."""
    notices = read("package/THIRD-PARTY-NOTICES.txt")
    for name in ("Python", "OpenSSL", "Tcl", "Tk", "PYTHON-LICENSE.txt", "Pixelify Sans", "VT323", "PyInstaller"):
        assert name in notices, name
    tcl = open(os.path.join(ROOT, "tests", "data", "tcl-license.terms"), encoding="utf-8").read()
    assert " ".join(tcl.split()[:60]) in " ".join(notices.split())      # Tcl/Tk: "included verbatim"
    assert "THIRD-PARTY-NOTICES.txt" in read("LICENSE")


@pytest.mark.parametrize("build", ["build_exe.bat", ".github/workflows/release.yml"])
def test_builds_copy_pythons_own_license_file(build):
    text = read(build)
    assert "base_prefix" in text and "LICENSE.txt" in text and "PYTHON-LICENSE.txt" in text


def test_website_links_the_font_license():
    assert os.path.exists(os.path.join(ROOT, "docs", "FONTS-LICENSE.txt"))
    assert read("docs/FONTS-LICENSE.txt") == read("FONTS-LICENSE.txt")
    assert 'href="FONTS-LICENSE.txt"' in read("docs/index.html")


def test_privacy_policy_meets_blizzards_terms():
    """Blizzard API Terms 2.15: a posted privacy policy, consistent with Blizzard's, saying the data is
    provided "as is" and telling players how their data is used."""
    policy = " ".join(read("PRIVACY.md").split())
    for must in ('"as is"', "30 days", "Blizzard Entertainment Online Privacy Policy", "guild", "password",
                 "wow_price_config.json", "Google Fonts", "13"):
        assert must in policy, must
    assert read("package/PRIVACY.txt").replace("\r\n", "\n") == read("PRIVACY.md").replace("\r\n", "\n")
    for f in ("README.md", "package/README.txt", "docs/index.html", "SECURITY.md"):
        assert "PRIVACY" in read(f), f


QUESTIEDB_LICENSE = "https://github.com/Questie/QuestieDB/blob/master/LICENSE.md"


@pytest.mark.parametrize("f", ["LICENSE", "package/LICENSE.txt", "package/THIRD-PARTY-NOTICES.txt", "README.md",
                               "package/README.txt", "docs/index.html"])
def test_questiedb_is_credited_with_its_license(f):
    """Permission from the Questie team (Nov 12 2026) came with one condition: credit QuestieDB explicitly,
    and its license."""
    text = " ".join(read(f).split())
    assert "QuestieDB" in text and QUESTIEDB_LICENSE in text, f


def test_about_box_credits_questiedb_and_its_license():
    about = " ".join(_about_text().split())
    assert "QuestieDB" in about and QUESTIEDB_LICENSE.replace("https://", "") in about


def test_tests_use_made_up_names_only():
    """No real character or guild names in the repo. Names saved on this PC (personal, git-ignored files)
    must not appear in any test file."""
    names = set()
    for f, keys in (("character_progress.json", ("name", "surname", "guild")), ("characters.json", ("name", "surname"))):
        try:
            data = json.loads(read(f))
        except (OSError, ValueError):
            continue
        rows = data.get("chars", {}).values() if isinstance(data, dict) else data
        names |= {r.get(k) for r in rows if isinstance(r, dict) for k in keys if r.get(k)}
    if not names:
        pytest.skip("no saved characters on this PC")
    tests_dir = os.path.join(ROOT, "tests")
    for name in os.listdir(tests_dir):
        if name.endswith(".py"):
            text = read(os.path.join("tests", name))
            for n in names:
                assert not re.search(r"\b" + re.escape(n) + r"\b", text), f"{n!r} in tests/{name}"
