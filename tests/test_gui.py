"""Window app smoke tests: opens the real Awesome House window (with fake Blizzard data), visits
every tab and opens every tool window, and fails if any button or background job raises an error.

Needs a screen (they flash windows briefly). Skipped automatically where Tk can't open a window.
Run only these with:   python -m pytest tests/test_gui.py
Skip them with:        python -m pytest -m "not gui"
"""

import importlib.machinery
import importlib.util
import json
import os
import sys
import time

import pytest

import wow_monsters as wm
import wow_price as wp
import wow_progress as wpr
from conftest import ROOT, FakeApi, book, know_item, snapshot, tiny_index

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.gui


def _load_gui():
    if "wow_price_gui" in sys.modules:
        return sys.modules["wow_price_gui"]
    path = os.path.join(ROOT, "wow_price_gui.pyw")
    loader = importlib.machinery.SourceFileLoader("wow_price_gui", path)
    spec = importlib.util.spec_from_loader("wow_price_gui", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wow_price_gui"] = mod
    loader.exec_module(mod)
    return mod


gui = _load_gui()

try:                                    # can this computer open a window at all?
    _probe = tk.Tk()
    _probe.destroy()
except tk.TclError as e:                # e.g. a server with no screen
    pytest.skip(f"no screen for Tk: {e}", allow_module_level=True)


SOURCES = [("Orgrimmar", book((2318, 100, 40), (2318, 120, 10), (200, 50000, 1))),
           ("Ironforge", book((2318, 95, 5)))]


class Harness:
    """The running app plus everything it tried to show the user."""

    def __init__(self, app, root, errors, dialogs, opened):
        self.app, self.root, self.errors, self.dialogs, self.opened = app, root, errors, dialogs, opened

    def pump(self, seconds=0.6, until=None):
        """Let the window and its background jobs run for a while (or until a condition holds)."""
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if until and until():
                return True
            time.sleep(0.01)
        return bool(until and until())

    def show_tab(self, tab):
        """Switch tabs and make sure the tab starts loading (the <Map> event isn't reliable
        when windows are opened and closed quickly)."""
        self.app.tabs.select(tab)
        self.pump(0.2)
        if hasattr(tab, "on_show") and not getattr(tab, "loading", False):
            tab.on_show()

    def windows(self, cls):
        return [w for w in self.root.winfo_children() if isinstance(w, cls)]


@pytest.fixture
def app(monkeypatch, tmp_path):
    errors, dialogs, opened = [], [], []

    # Blizzard and GitHub: fakes only
    api = FakeApi({"/data/wow/item-class/index": {"item_classes": [{"id": 7, "name": "Trade Goods"}]},
                   "/data/wow/item-class/7": {"item_subclasses": [{"id": 6, "name": "Leather"}]},
                   "/data/wow/search/item": {"results": [], "pageCount": 1}})
    monkeypatch.setattr(wp, "connect", lambda game="forever", region="us": api)
    monkeypatch.setattr(wp, "has_credentials", lambda: True)
    monkeypatch.setattr(wp, "get_sources", lambda a, realm=None: SOURCES)
    monkeypatch.setattr(wm, "newer_release", lambda: None)

    # nothing may block the test with a dialog or open a browser
    for name in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(gui.messagebox, name, lambda *a, _n=name, **k: dialogs.append((_n, a)))
    for name in ("askokcancel", "askyesno", "askyesnocancel"):
        monkeypatch.setattr(gui.messagebox, name, lambda *a, _n=name, **k: dialogs.append((_n, a)) or False)
    monkeypatch.setattr(gui.filedialog, "asksaveasfilename", lambda **k: str(tmp_path / k.get("initialfile", "x")))
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **k: "")
    monkeypatch.setattr(gui.webbrowser, "open", lambda url, *a, **k: opened.append(url))
    monkeypatch.setattr(gui.webbrowser, "open_new_tab", lambda url, *a, **k: opened.append(url))

    # data the app finds on disk
    know_item(2318, "Light Leather", cls="Trade Goods", sub="Leather", q="COMMON")
    wp.save_watchlist([{"id": 2318, "name": "Light Leather", "cls": "Trade Goods", "sub": "Leather"}])
    os.makedirs(wm.DATA_DIR, exist_ok=True)
    with open(wm.INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(tiny_index(), f)
    wpr.save(snapshot(guild="Example Guild", guild_slug="example-guild"))
    wp.save_json(wpr._guild_path("example-guild"), {
        "name": "Example Guild", "fetched": int(time.time()), "listed": 1,
        "members": [{"name": "Ann", "level": 30, "cls": "Mage", "read": True,
                     "profs": [{"name": "Tailoring", "skill": 150, "max": 225, "recipes": ["Bolt of Silk Cloth"]}]}]})

    gui.register_fonts()
    root = tk.Tk()
    root.report_callback_exception = lambda exc, val, tb: errors.append(val)
    gui.setup_theme(root)
    a = gui.App(root)
    h = Harness(a, root, errors, dialogs, opened)
    h.pump(0.3)
    yield h
    h.pump(0.2)                     # let finished background jobs report back
    try:
        root.destroy()
    except tk.TclError:
        pass
    # Free the closed window's Tk objects now, on this thread. Otherwise Python may clean them up
    # later on some worker thread, where tkinter waits ~30 s for a main loop that's gone.
    import gc
    gc.collect()
    assert not errors, f"the window raised errors: {errors!r}"


def test_window_opens_with_every_tab(app):
    title = app.root.title()
    assert gui.APP_NAME in title and gui.APP_VERSION in title
    names = [app.app.tabs.tab(t, "text").strip() for t in app.app.tabs.tabs()]
    assert names == ["Search", "Watchlist", "Character", "Monster Compendium", "Dungeons", "Progress"]


def test_visit_every_tab(app):
    for t in app.app.tabs.tabs():
        app.show_tab(app.root.nametowidget(t))
        app.pump(0.4)
    assert app.pump(8, until=lambda: app.app.monster_tab.db is not None), \
        "Monster Compendium didn't load the saved index"
    assert not [d for d in app.dialogs if d[0] == "showerror"]


def test_search_finds_an_item(app):
    app.app.tabs.select(0)
    app.app.item.delete(0, "end")
    app.app.item.insert(0, "Light Leather")
    app.app.lookup()
    assert app.pump(5, until=lambda: app.app.cards.entries), "no result cards appeared"
    e = app.app.cards.entries[0]
    assert e["id"] == 2318 and e["lowest"] == 95


def test_search_for_nothing_says_so(app):
    app.app.item.delete(0, "end")
    app.app.lookup()
    app.pump(0.3)


def test_check_watchlist_fills_the_table(app):
    app.app.tabs.select(1)
    app.app.check_all()
    assert app.pump(5, until=lambda: app.app.last_check is not None)
    assert wp.price_history("forever", 2318, 0), "price history wasn't recorded"


def test_categories_load(app):
    app.app.load_categories()
    app.pump(3, until=lambda: bool(app.app.cat_names))


def test_monster_and_dungeon_tabs(app):
    app.show_tab(app.app.monster_tab)
    assert app.pump(8, until=lambda: app.app.monster_tab.db is not None)
    app.show_tab(app.app.dungeon_tab)
    app.pump(1)


def test_progress_tab_adopts_the_saved_character(app):
    app.show_tab(app.app.progress_tab)
    assert app.pump(5, until=lambda: getattr(app.app.progress_tab, "snap", None) is not None)
    app.pump(1)
    assert app.app.progress_tab.snap["name"] == "Testy"


def test_tool_windows_open(app):
    entry = {"id": 2318, "name": "Light Leather", "cls": "Trade Goods", "sub": "Leather"}
    opened = [
        gui.FishingWindow(app.app),
        gui.SellWindow(app.app, "Light Leather", {"id": 2318, "name": "Light Leather"}),
        gui.TimingWindow(app.app, entry, "forever"),
        gui.HistoryWindow(app.app, entry, "forever"),
        gui.AlertDialog(app.app, entry),
        gui.FlipWindow(app.app),
        gui.CraftingWindow(app.app),
        gui.SpotWindow(app.app),
        gui.ProfessionsWindow(app.app),
    ]
    app.pump(2)
    for w in opened:
        try:
            w.destroy()
        except tk.TclError:
            pass


def test_guild_crafters_window(app):
    app.show_tab(app.app.progress_tab)
    app.pump(1)
    app.app.open_guild()
    app.pump(1.5)
    assert app.windows(gui.GuildWindow), "Guild crafters window didn't open"


def test_help_menu(app):
    app.app.open_about()
    app.app.report_bug()
    app.app.open_donate()
    assert any("paypal" in u.lower() for u in app.opened)
    assert any(u.startswith("mailto:") for u in app.opened)
    assert [d[0] for d in app.dialogs].count("showinfo") >= 2


def test_export_menu(app, tmp_path):
    wp.record_history("forever", 1000, [{"id": 2318, "found": True, "lowest": 100, "cheap10": 100,
                                         "quantity": 5}])
    app.app.export_history()
    assert (tmp_path / "wow_price_history.csv").exists()
    app.app.export_sessions()
    assert (tmp_path / "fishing_sessions.csv").exists()


def test_copy_waypoint(app):
    app.app.copy_way("/way Testlands 50 50 Boar")
    assert app.root.clipboard_get() == "/way Testlands 50 50 Boar"


def test_capture_shows_a_network_problem_in_plain_words():
    def offline():
        raise wp.NetworkError("Could not reach Blizzard API: no internet")
    result, err = gui.capture(offline)
    assert result is None and err == "Could not reach Blizzard API: no internet"


def _rows(price, partial=False):
    r = {"id": 2318, "name": "Light Leather", "found": True, "lowest": price, "cheap10": price,
         "quantity": 5, "ts": int(time.time()), "cls": "Trade Goods", "sub": "Leather"}
    if partial:
        r["partial"] = True
    return [r]


def test_status_bar_says_when_auction_houses_did_not_answer(app):
    wp._houses["us"] = (14, 15)
    app.app.set_status()
    assert "14 of 15 auction houses answered" in app.app.status.cget("text")
    wp._houses["us"] = (15, 15)
    app.app.set_status()
    assert "auction houses answered" not in app.app.status.cget("text")


def test_alerts_wait_for_whole_auction_data(app, monkeypatch):
    toasts = []
    monkeypatch.setattr(gui, "Toast", lambda root, msg: toasts.append(msg))
    app.app.watch[0]["alert_above"] = 100
    app.app.handle_rows(_rows(500, partial=True), "forever", show=False)
    assert toasts == [] and not app.app.watch[0].get("alerted_above")
    app.app.handle_rows(_rows(500), "forever", show=False)
    assert len(toasts) == 1 and "rose to" in toasts[0]


def test_old_blizzard_data_is_cleaned_up_after_start_and_daily(app, monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "enforce_data_ttl", lambda now=None: calls.append("wp") or 0)
    monkeypatch.setattr(wpr, "enforce_data_ttl", lambda now=None: calls.append("wpr") or 0)
    app.app.sweep_old_data()
    app.pump(1.0, until=lambda: len(calls) == 2)
    assert calls == ["wp", "wpr"]
    app.app._last_sweep = time.time() - 2 * 86400              # a day later, the hourly check sweeps again
    app.app.auto_check()
    app.pump(1.0, until=lambda: len(calls) == 4)
    assert calls[2:] == ["wp", "wpr"]


def test_help_menu_opens_the_privacy_policy(app):
    app.app.open_privacy()
    assert gui.PRIVACY_URL in app.opened and gui.PRIVACY_URL.endswith("/PRIVACY.md")
    menubar = app.root.nametowidget(app.root.cget("menu"))
    labels = []
    for i in range(menubar.index("end") + 1):
        if menubar.type(i) != "cascade":      # Tk 8.6 (Windows) puts a hidden tear-off entry first
            continue
        sub = menubar.nametowidget(menubar.entrycget(i, "menu"))
        labels += [sub.entrycget(j, "label") for j in range(sub.index("end") + 1) if sub.type(j) == "command"]
    assert "Privacy policy..." in labels
