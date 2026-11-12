"""
Awesome House (Beta 0.16.1) - the window app for wow_price.py
Keep this file in the same folder as wow_price.py and double-click it to open.

Features: price lookup, watchlist with Day/Week/Month trends, price history chart,
price alerts (checked hourly while the app is open), fishing session value,
Monster Compendium (monsters per region, their drops and quests, tracking list),
Dungeons (entrances, routes, monsters, drops and quests per dungeon),
Progress (a character's quests per zone, milestones, reputations, PvP, raids, and what to do next).
"""

import base64
import contextlib
import io
import os
import platform
import queue
import re
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont

import wow_price as wp
import wow_monsters as wm
import wow_dungeons as wd
import wow_progress as wpg
import wow_loot as wl

HERE = os.path.dirname(os.path.abspath(__file__))
AUTO_CHECK_MS = 61 * 60 * 1000   # Blizzard refreshes data about hourly
COPYRIGHT = "\u00a9 2026 Kade. All rights reserved."
DONATE_URL = "https://paypal.me/keedoyesyes"
RELEASES_URL = "https://github.com/kadestclair-dotcom/awesome-house/releases"   # the official download page
PRIVACY_URL = "https://github.com/kadestclair-dotcom/awesome-house/blob/main/PRIVACY.md"   # Blizzard API Terms 2.15
BUG_EMAIL = "kadestclair@gmail.com"
APP_NAME = "Awesome House"
APP_VERSION = "Beta 0.16.1"


# ================================================================ pixel-art WoW theme
# Fonts: Pixelify Sans and VT323, both under the SIL Open Font License 1.1
# (https://openfontlicense.org). Bundled here so nothing needs installing.

BG = "#120d09"          # window background (dark leather)
PANEL = "#211810"       # panels
PANEL_2 = "#2d2116"     # raised panels / cards
INSET = "#0c0806"       # text areas and inputs
BORDER = "#6b4f26"      # bronze frame
GOLD_EDGE = "#c9a24a"   # bright gold frame
TEXT = "#f1e3bd"        # parchment text
MUTED = "#a08f6c"
GOLD = "#ffd100"        # WoW yellow
LINK = "#7cc4ff"
UP = "#3ee26b"
DOWN = "#ff6a55"
GRID = "#3a2c1c"
HILITE = "#5a3d12"      # selection background
BTN, BTN_HI, BTN_LO, BTN_ACTIVE = "#7a1414", "#c0392b", "#350505", "#9c1d1d"
COIN_TEXT = {"g": "#ffd100", "s": "#d9d9e3", "c": "#e8955a"}
QUALITY_COLORS = {"POOR": "#9d9d9d", "COMMON": "#ffffff", "UNCOMMON": "#1eff00", "RARE": "#3d9bff",
                  "EPIC": "#c06bff", "LEGENDARY": "#ff8000", "ARTIFACT": "#e6cc80", "HEIRLOOM": "#00ccff"}

UI_FONT, UI_SCALE = "Segoe UI", 1.0          # replaced by the pixel fonts when they load
MONO_FONT, MONO_SCALE = "Consolas", 1.0
IMG = {}                                    # pixel sprites, built once the window exists


def F(size, *mods):
    """Interface font (Pixelify Sans)."""
    return (UI_FONT, max(6, int(round(size * UI_SCALE))), *mods)


def M(size, *mods):
    """Monospace font for tables (VT323)."""
    return (MONO_FONT, max(6, int(round(size * MONO_SCALE))), *mods)


def register_fonts():
    """Write the bundled fonts to disk and register them for this app only (Windows).
    Must run before the Tk window is created. Returns True if registered."""
    folder = os.path.join(wp.CACHE_DIR, "fonts")
    try:
        os.makedirs(folder, exist_ok=True)
        paths = []
        for name, chunks in FONT_DATA.items():
            path = os.path.join(folder, name)
            if not os.path.exists(path):           # written whole or not at all, so never half a font
                wp.atomic_write_bytes(path, base64.b64decode("".join(chunks)), backup=False)
            paths.append(path)
        if sys.platform == "win32":
            import ctypes
            FR_PRIVATE = 0x10
            for path in paths:
                ctypes.windll.gdi32.AddFontResourceExW(path, FR_PRIVATE, 0)
            return True
    except Exception:
        pass
    return False


def _sprite(size, scale, color_at):
    """Build a PhotoImage from a function (x, y) -> colour or None (transparent)."""
    img = tk.PhotoImage(width=size * scale, height=size * scale)
    for y in range(size):
        for x in range(size):
            col = color_at(x, y)
            if col:
                img.put(col, to=(x * scale, y * scale, x * scale + scale, y * scale + scale))
    return img


def _coin(size, scale, light, mid, dark, edge):
    c = (size - 1) / 2

    def color_at(x, y):
        d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
        if d > size / 2:
            return None
        if d > size / 2 - 1:
            return edge
        if size >= 10 and size / 2 - 2.6 < d < size / 2 - 1.7:
            return dark                      # engraved rim on big coins
        v = (x + y) / (2 * (size - 1))
        return light if v < 0.38 else mid if v < 0.62 else dark
    return _sprite(size, scale, color_at)


def build_sprites():
    tones = {"g": ("#fff3a0", "#ffd100", "#c48a00", "#5a3a00"),
             "s": ("#ffffff", "#c9c9d6", "#8a8a99", "#3a3a44"),
             "c": ("#ffc89a", "#d9773a", "#97481c", "#4a2208")}
    for k, (li, mi, da, ed) in tones.items():
        IMG["coin_" + k] = _coin(7, 2, li, mi, da, ed)
    IMG["coin_big"] = _coin(12, 3, *tones["g"])

    def radio_off(x, y):
        if x in (0, 6) or y in (0, 6):
            return BORDER
        return INSET
    IMG["radio_off"] = _sprite(7, 2, radio_off)

    def radio_on(x, y):
        d = abs(x - 3) + abs(y - 3)
        if d > 3:
            return None
        return "#5a3a00" if d == 3 else "#fff3a0" if (x + y) < 5 else GOLD
    IMG["radio_on"] = _sprite(7, 2, radio_on)


def setup_theme(root):
    """Pick fonts, build sprites and style every widget."""
    global UI_FONT, UI_SCALE, MONO_FONT, MONO_SCALE
    families = set(tkfont.families(root))
    if "Pixelify Sans" in families:
        UI_FONT, UI_SCALE = "Pixelify Sans", 1.1
    if "VT323" in families:
        MONO_FONT, MONO_SCALE = "VT323", 1.6
    build_sprites()

    for name, spec in (("TkDefaultFont", F(10)), ("TkTextFont", M(10)), ("TkMenuFont", F(10)),
                       ("TkHeadingFont", F(10, "bold")), ("TkCaptionFont", F(11, "bold")),
                       ("TkFixedFont", M(10))):
        try:
            fam, size, *mods = spec
            tkfont.nametofont(name).configure(family=fam, size=size,
                                              weight="bold" if "bold" in mods else "normal")
        except tk.TclError:
            pass

    root.configure(bg=BG)
    opt = root.option_add
    opt("*Toplevel.background", PANEL)
    opt("*Frame.background", PANEL)
    opt("*Label.background", PANEL)
    opt("*Label.foreground", TEXT)
    opt("*Canvas.background", INSET)
    for w in ("Text", "Listbox"):
        opt(f"*{w}.background", INSET)
        opt(f"*{w}.foreground", TEXT)
        opt(f"*{w}.selectBackground", HILITE)
        opt(f"*{w}.selectForeground", GOLD)
        opt(f"*{w}.highlightThickness", 2)
        opt(f"*{w}.highlightBackground", BORDER)
        opt(f"*{w}.highlightColor", GOLD_EDGE)
        opt(f"*{w}.relief", "flat")
    opt("*Text.insertBackground", GOLD)
    opt("*TCombobox*Listbox.background", INSET)
    opt("*TCombobox*Listbox.foreground", TEXT)
    opt("*TCombobox*Listbox.selectBackground", HILITE)
    opt("*TCombobox*Listbox.selectForeground", GOLD)
    opt("*TCombobox*Listbox.font", M(10))
    opt("*Menu.background", PANEL_2)
    opt("*Menu.foreground", TEXT)
    opt("*Menu.activeBackground", HILITE)
    opt("*Menu.activeForeground", GOLD)
    opt("*Menu.relief", "flat")

    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=PANEL, foreground=TEXT, fieldbackground=INSET, bordercolor=BORDER,
                 lightcolor=PANEL_2, darkcolor=BG, troughcolor=INSET, selectbackground=HILITE,
                 selectforeground=GOLD, insertcolor=GOLD, arrowcolor=GOLD, focuscolor=GOLD_EDGE,
                 font=F(10))
    st.configure("TFrame", background=PANEL)
    st.configure("TLabel", background=PANEL, foreground=TEXT)
    st.configure("Banner.TFrame", background=BG)
    st.configure("Banner.TLabel", background=BG, foreground=MUTED)
    st.configure("Status.TLabel", background=BG, foreground=MUTED, font=M(10))

    st.configure("TButton", background=BTN, foreground=GOLD, bordercolor="#000000",
                 lightcolor=BTN_HI, darkcolor=BTN_LO, padding=(10, 4), font=F(10, "bold"),
                 focuscolor=BTN, relief="raised")
    st.map("TButton",
           background=[("disabled", "#3a2c20"), ("pressed", BTN_LO), ("active", BTN_ACTIVE)],
           foreground=[("disabled", "#7d6a52")],
           lightcolor=[("disabled", "#4a3828"), ("pressed", BTN_LO)],
           darkcolor=[("disabled", "#241a12"), ("pressed", BTN_HI)])

    for w in ("TEntry", "TCombobox"):
        st.configure(w, fieldbackground=INSET, foreground=TEXT, bordercolor=BORDER,
                     lightcolor=INSET, darkcolor=INSET, insertcolor=GOLD, padding=4)
        st.map(w, bordercolor=[("focus", GOLD_EDGE)], lightcolor=[("focus", INSET)])
    st.configure("TCombobox", background=PANEL_2, arrowcolor=GOLD, arrowsize=14)
    st.map("TCombobox", fieldbackground=[("readonly", INSET)], foreground=[("readonly", TEXT)],
           selectbackground=[("readonly", INSET)], selectforeground=[("readonly", GOLD)],
           background=[("active", HILITE)])

    for w in ("Treeview", "Side.Treeview"):
        st.configure(w, background=INSET, fieldbackground=INSET, foreground=TEXT, bordercolor=BORDER,
                     lightcolor=INSET, darkcolor=INSET, rowheight=24, font=F(10), indent=16)
        st.map(w, background=[("selected", HILITE)], foreground=[("selected", GOLD)])
    st.configure("Treeitem.indicator", foreground=GOLD)
    st.configure("Data.Treeview", background=INSET, fieldbackground=INSET, foreground=TEXT,
                 bordercolor=BORDER, lightcolor=INSET, darkcolor=INSET, rowheight=26, font=M(11))
    st.map("Data.Treeview", background=[("selected", HILITE)], foreground=[("selected", GOLD)])
    st.configure("Data.Treeview.Heading", background=PANEL_2, foreground=GOLD, bordercolor=BORDER,
                 lightcolor=PANEL_2, darkcolor=PANEL, font=F(9, "bold"), padding=(6, 4))
    st.map("Data.Treeview.Heading", background=[("active", HILITE)])
    st.configure("Big.TButton", font=F(11, "bold"), padding=(14, 8))

    st.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=(0, 4, 0, 0),
                 lightcolor=BORDER, darkcolor=BORDER)
    for w in ("TNotebook.Tab", "Main.TNotebook.Tab"):
        st.configure(w, background=PANEL, foreground=MUTED, bordercolor=BORDER, lightcolor=PANEL_2,
                     darkcolor=PANEL, padding=(16, 6), font=F(11, "bold"))
        st.map(w, background=[("selected", PANEL_2), ("active", PANEL_2)],
               foreground=[("selected", GOLD), ("active", TEXT)],
               lightcolor=[("selected", GOLD_EDGE)], expand=[("selected", (0, 2, 0, 0))])
    st.configure("Main.TNotebook", background=BG)

    st.configure("TLabelframe", background=PANEL, bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL)
    st.configure("TLabelframe.Label", background=PANEL, foreground=GOLD, font=F(10, "bold"))
    for w in ("TCheckbutton", "TRadiobutton"):
        st.configure(w, background=PANEL, foreground=TEXT, indicatorbackground=INSET,
                     indicatorforeground=GOLD, upperbordercolor=BORDER, lowerbordercolor=GOLD_EDGE,
                     focuscolor=PANEL)
        st.map(w, background=[("active", PANEL)], indicatorbackground=[("selected", INSET)])
    st.configure("Card.TCheckbutton", background=PANEL_2)
    st.map("Card.TCheckbutton", background=[("active", PANEL_2)])
    st.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=INSET, bordercolor=BORDER,
                 arrowcolor=GOLD, lightcolor=BORDER, darkcolor=BG, gripcount=0)
    st.map("Vertical.TScrollbar", background=[("active", HILITE)])


def money(parent, copper, bg, size=10):
    """In-game style price: 12[g] 34[s] 56[c] with pixel coin icons."""
    copper = int(round(copper or 0))
    g, rem = divmod(copper, 10000)
    s_, c = divmod(rem, 100)
    parts = [(g, "g"), (s_, "s"), (c, "c")]
    while len(parts) > 1 and parts[0][0] == 0:
        parts.pop(0)
    f = tk.Frame(parent, bg=bg)
    for n, k in parts:
        tk.Label(f, text=f"{n:,}", fg=COIN_TEXT[k], bg=bg, font=M(size + 1)).pack(side="left")
        tk.Label(f, image=IMG["coin_" + k], bg=bg).pack(side="left", padx=(1, 5))
    return f


class Banner(tk.Frame):
    """Pixel-art title bar with a gold coin and a gold pixel trim underneath."""

    def __init__(self, master):
        super().__init__(master, bg=BG)
        self.logo = tk.Canvas(self, height=54, width=430, bg=BG, highlightthickness=0)
        self.logo.pack(side="left", padx=(8, 0))
        self.logo.create_image(6, 9, image=IMG["coin_big"], anchor="nw")
        for dx, dy, col in ((2, 2, "#000000"), (0, 0, GOLD)):
            self.logo.create_text(56 + dx, 8 + dy, text="AWESOME HOUSE", anchor="nw",
                                  fill=col, font=F(19, "bold"))
        self.logo.create_text(58, 36, text=f"price checker  ·  {APP_VERSION}", anchor="nw",
                              fill=MUTED, font=F(9))
        self.controls = tk.Frame(self, bg=BG)
        self.controls.pack(side="right", padx=10)

    @staticmethod
    def trim(master):
        c = tk.Canvas(master, height=8, bg=BG, highlightthickness=0)

        def draw(_e=None):
            c.delete("all")
            w = c.winfo_width()
            c.create_rectangle(0, 2, w, 4, fill=GOLD_EDGE, outline="")
            c.create_rectangle(0, 4, w, 6, fill=BORDER, outline="")
            for x in range(40, w, 160):           # little pixel diamonds along the trim
                for dx, dy, col in ((0, -2, GOLD), (-2, 0, GOLD), (2, 0, GOLD), (0, 2, GOLD), (0, 0, "#fff3a0")):
                    c.create_rectangle(x + dx, 3 + dy, x + dx + 2, 5 + dy, fill=col, outline="")
        c.bind("<Configure>", draw)
        return c



def wowhead_url(item_id, game):
    if game == "forever":
        return f"https://www.wowhead.com/forever/item={item_id}"
    return f"https://www.wowhead.com/item={item_id}"


def clock(ts, fmt="%I:%M %p"):
    return datetime.fromtimestamp(ts).strftime(fmt).lstrip("0")


def capture(fn):
    """Run fn, returning (result, anything it printed or any error as text)."""
    buf = io.StringIO()
    result = None
    try:
        with contextlib.redirect_stdout(buf):
            result = fn()
    except SystemExit as e:
        if e.code not in (None, 0):
            buf.write(f"\n{e.code}")
    except (wp.ApiError, wp.NetworkError) as e:
        buf.write(f"\n{e}")
    except Exception as e:
        buf.write(f"\nSomething went wrong: {e}")
    lines = [l for l in buf.getvalue().splitlines() if not l.startswith("Downloading fresh")]
    return result, "\n".join(lines).strip()


# ---------------------------------------------------------------- output box

class OutputText(tk.Text):
    """Read-only text area that supports colored text and clickable Wowhead links."""

    def __init__(self, master, **kw):
        super().__init__(master, wrap="none", font=M(10), padx=12, pady=10, bg=INSET, fg=TEXT,
                         insertbackground=GOLD, selectbackground=HILITE, selectforeground=GOLD,
                         relief="flat", highlightthickness=2, highlightbackground=BORDER,
                         highlightcolor=BORDER, spacing1=1, **kw)
        self.tag_config("link", foreground=LINK, underline=True)
        for k, col in COIN_TEXT.items():
            self.tag_config("coin_" + k, foreground=col)
        self.tag_config("up", foreground=UP)
        self.tag_config("down", foreground=DOWN)
        self.tag_config("muted", foreground=MUTED)
        self.tag_config("gold", foreground=GOLD)
        self.tag_config("bold", font=M(10, "bold"))
        self.tag_bind("link", "<Enter>", lambda e: self.config(cursor="hand2"))
        self.tag_bind("link", "<Leave>", lambda e: self.config(cursor=""))
        self.tag_bind("link", "<ButtonRelease-1>", self._open)
        self.urls = {}
        self._last_open = 0.0
        self.config(state="disabled")

    def begin(self):
        self.config(state="normal")
        self.delete("1.0", "end")
        for tag in list(self.urls):
            self.tag_delete(tag)
        self.urls = {}

    def emit(self, text, *tags):
        self.insert("end", text, tags)

    def emit_link(self, text, url, *tags):
        tag = f"link_{len(self.urls)}"
        self.urls[tag] = url
        self.insert("end", text, ("link", tag) + tags)

    def emit_action(self, text, fn, *tags):
        """A link that runs fn() instead of opening a web page."""
        self.emit_link(text, fn, *tags)

    MONEY = re.compile(r"(?<![\w.])(\d[\d,]*)([gsc])(?![\w])")

    def end(self):
        """Colour every price like the game does: gold, silver and copper."""
        for n, line in enumerate(self.get("1.0", "end").split("\n"), start=1):
            for m in self.MONEY.finditer(line):
                self.tag_add("coin_" + m.group(2), f"{n}.{m.start()}", f"{n}.{m.end()}")
        self.config(state="disabled")

    def show(self, text):
        self.begin()
        self.emit(text)
        self.end()

    def _open(self, event):
        now = time.monotonic()
        if now - self._last_open < 1.0:      # one click = one tab
            return "break"
        idx = self.index(f"@{event.x},{event.y}")
        for tag in self.tag_names(idx):
            if tag in self.urls:
                self._last_open = now
                target = self.urls[tag]
                if callable(target):
                    target()
                else:
                    webbrowser.open_new_tab(target)
                break
        return "break"


def trend_tag(p):
    if p is None:
        return "muted"
    return "up" if p > 0.05 else "down" if p < -0.05 else "muted"


# ---------------------------------------------------------------- search result cards

CARD_BG = PANEL_2
CARD_BORDER = BORDER
SELECT_BG = "#3b2913"


# (quality colours are defined with the theme above)


class ResultCards(ttk.Frame):
    """Scrollable list of clickable item cards, filtered by the Search tab's filters.
    Click a card to select it (it expands to show each auction house)."""
    MAX_CARDS = 40
    ALL = "All categories"

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.all_entries, self.entries, self.cards = [], [], []
        self.selected = None
        self.game = "forever"
        self.result = None

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 2))
        self.title = ttk.Label(bar, font=F(11, "bold"), foreground=GOLD)
        self.title.pack(side="left")
        self.bar_right = ttk.Frame(bar)
        self.bar_right.pack(side="right")
        self.cat_filter = ttk.Combobox(bar, state="readonly", width=30)
        self.cat_filter.bind("<<ComboboxSelected>>", lambda e: self.render())
        self.cat_label = ttk.Label(bar, text="Show:")

        self.hint = ttk.Label(self, foreground=MUTED)
        self.hint.pack(fill="x", pady=(0, 4))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=INSET, highlightthickness=1, highlightbackground=CARD_BORDER)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=INSET)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.win, width=e.width))
        self.canvas.bind("<Enter>", lambda e: self._wheel(True))
        self.canvas.bind("<Leave>", lambda e: self._wheel(False))

    def _wheel(self, on):
        if on:
            self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
        else:
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.canvas.unbind_all(ev)

    def _clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.cards, self.entries, self.selected = [], [], None

    def message(self, text):
        """Show a note instead of cards (start-up, loading, errors)."""
        self._clear()
        self.all_entries, self.result = [], None
        self.title.config(text="")
        self.hint.config(text="", foreground=MUTED)
        self.cat_filter.pack_forget()
        self.cat_label.pack_forget()
        tk.Label(self.inner, text=text, bg=INSET, fg=TEXT, justify="left",
                 font=F(10), wraplength=700).pack(anchor="w", padx=14, pady=14)
        self.canvas.yview_moveto(0)
        self.app.update_add_button()

    # --- data in ---
    def show(self, result, game):
        self.game = game
        self.result = result
        self.all_entries = result["items"]
        for i, e in enumerate(self.all_entries):
            e["cat"] = wp.category_label(e.get("cls"), e.get("sub"))
            e["order"] = i
        counts = {}
        for e in self.all_entries:
            counts[e["cat"]] = counts.get(e["cat"], 0) + 1
        if len(counts) > 1:
            self.cat_filter.config(values=[f"{self.ALL} ({len(self.all_entries)})"] +
                                   [f"{c} ({n})" for c, n in sorted(counts.items())])
            self.cat_filter.current(0)
            self.cat_filter.pack(side="right", padx=(0, 14))
            self.cat_label.pack(side="right", padx=(0, 4))
        else:
            self.cat_filter.set("")
            self.cat_filter.pack_forget()
            self.cat_label.pack_forget()
        self.render()

    def _passes(self, e, f, cat):
        if cat and e["cat"] != cat:
            return False
        if f["listed"] and not e["found"]:
            return False
        if f["quality"]:
            r = wp.quality_rank(e.get("q"))
            if r is None or r < wp.quality_rank(f["quality"]):
                return False
        if f["lmin"] is not None or f["lmax"] is not None:
            req = e.get("req")
            if req is None:
                return False
            if (f["lmin"] is not None and req < f["lmin"]) or (f["lmax"] is not None and req > f["lmax"]):
                return False
        if f["pmin"] is not None or f["pmax"] is not None:
            if not e["found"]:
                return False
            if (f["pmin"] is not None and e["lowest"] < f["pmin"]) or \
               (f["pmax"] is not None and e["lowest"] > f["pmax"]):
                return False
        return True

    def render(self):
        if self.result is None:
            return
        self._clear()
        f = self.app.filters()
        cat = self.cat_filter.get().rsplit(" (", 1)[0] if self.cat_filter.get() else ""
        cat = "" if cat == self.ALL else cat
        matches = [e for e in self.all_entries if self._passes(e, f, cat)]
        sort = f["sort"]
        if sort == "Most listed":
            matches.sort(key=lambda e: -(e.get("quantity") or 0))
        elif sort == "Lowest price":
            matches.sort(key=lambda e: (not e["found"], e.get("lowest") or 0))
        elif sort == "Highest price":
            matches.sort(key=lambda e: (not e["found"], -(e.get("lowest") or 0)))
        elif sort == "Name (A-Z)":
            matches.sort(key=lambda e: e["name"].lower())
        else:
            matches.sort(key=lambda e: e["order"])
        self.entries = matches[:self.MAX_CARDS]

        r = self.result
        if r.get("browse"):
            title = f"{r['query']}:  {r['total']:,} item{'s' if r['total'] != 1 else ''} for sale"
        else:
            title = f'{r["total"]} result{"s" if r["total"] != 1 else ""} for "{r["query"]}"'
        self.title.config(text=title)
        hidden = len(self.all_entries) - len(matches)
        hint = f"Showing {len(self.entries)} of {len(matches)}"
        if hidden:
            hint += f"  ({hidden} hidden by filters)"
        if len(matches) > len(self.entries):
            hint += " - narrow it down with the filters"
        hint += ".   Click a result to select it; double-click adds it."
        if f["error"]:
            self.hint.config(text=f["error"] + "  (that filter is ignored)", foreground=DOWN)
        else:
            self.hint.config(text=hint, foreground=MUTED)

        if not self.entries:
            tk.Label(self.inner, text="Nothing matches these filters. Try Reset.", bg=INSET, fg=MUTED,
                     font=F(10)).pack(pady=20)
        for i, e in enumerate(self.entries):
            self.cards.append(self._card(i, e))
        if len(self.entries) == 1:
            self.select(0)
        self.canvas.yview_moveto(0)
        self.app.update_add_button()

    # --- cards ---
    def _card(self, i, e):
        card = tk.Frame(self.inner, bg=CARD_BG, highlightthickness=2,
                        highlightbackground=CARD_BORDER, padx=10, pady=6)
        card.pack(fill="x", padx=8, pady=3)

        top = tk.Frame(card, bg=CARD_BG)
        top.pack(fill="x")
        dot = tk.Label(top, image=IMG["radio_off"], bg=CARD_BG)
        dot.pack(side="left", padx=(0, 2))
        name = tk.Label(top, text=e["name"], bg=CARD_BG, fg=QUALITY_COLORS.get(e.get("q"), LINK),
                        cursor="hand2", font=F(12, "bold"))
        name.pack(side="left", padx=(6, 10))
        name.bind("<Button-1>", lambda ev, u=wowhead_url(e["id"], self.game): (webbrowser.open_new_tab(u), "break")[1])
        name.bind("<Enter>", lambda ev: name.config(font=F(12, "bold", "underline")))
        name.bind("<Leave>", lambda ev: name.config(font=F(12, "bold")))
        meta = e["cat"]
        if e.get("req"):
            meta += f"   ·   Req. level {e['req']}"
        tk.Label(top, text=meta, bg=CARD_BG, fg=MUTED, font=M(10)).pack(side="left")
        btn = ttk.Button(top, command=lambda: self.app.add_entry(e))
        btn.pack(side="right")
        tag = tk.Label(top, text="SELECTED", bg=CARD_BG, fg=GOLD, font=F(8, "bold"))

        row = tk.Frame(card, bg=CARD_BG)
        row.pack(fill="x", padx=(24, 0), pady=(4, 0))
        if e["found"]:
            nh = len(e["houses"])
            for label, val in (("Lowest", e["lowest"]), ("Market", e["cheap10"])):
                tk.Label(row, text=label, bg=CARD_BG, fg=MUTED, font=F(10)).pack(side="left")
                money(row, val, CARD_BG).pack(side="left", padx=(5, 16))
            tk.Label(row, text=f"{e['quantity']:,} listed in {nh} auction house{'s' if nh != 1 else ''}",
                     bg=CARD_BG, fg=TEXT, font=M(11)).pack(side="left")
        else:
            tk.Label(row, text="Not listed on the auction house right now.", bg=CARD_BG, fg=MUTED,
                     font=F(10)).pack(side="left")

        info = {"frame": card, "dot": dot, "btn": btn, "tag": tag, "name": name, "detail": None}
        self._bind_clicks(card, i, skip=(name, btn))
        self._refresh_button(info, e)
        return info

    def _detail(self, info, e):
        """Per-auction-house table, shown only on the selected card."""
        if not e["houses"]:
            return
        grid = tk.Frame(info["frame"], bg=SELECT_BG, highlightthickness=1, highlightbackground=BORDER,
                        padx=8, pady=4)
        grid.pack(anchor="w", padx=(24, 0), pady=(8, 2))
        for c, h in enumerate(("AUCTION HOUSE", "LOWEST", "MARKET", "QTY")):
            tk.Label(grid, text=h, bg=SELECT_BG, fg=GOLD_EDGE, font=F(8, "bold"),
                     anchor="w" if c == 0 else "e").grid(row=0, column=c, sticky="we", padx=(0, 20))
        for r, h in enumerate(e["houses"], start=1):
            tk.Label(grid, text=h["label"], bg=SELECT_BG, fg=TEXT, font=F(10),
                     anchor="w").grid(row=r, column=0, sticky="w", padx=(0, 20))
            money(grid, h["lowest"], SELECT_BG, 9).grid(row=r, column=1, sticky="e", padx=(0, 20))
            money(grid, h["cheap10"], SELECT_BG, 9).grid(row=r, column=2, sticky="e", padx=(0, 20))
            tk.Label(grid, text=f"{h['quantity']:,}", bg=SELECT_BG, fg=TEXT, font=M(11),
                     anchor="e").grid(row=r, column=3, sticky="e")
        info["detail"] = grid
        self._bind_clicks(grid, self.cards.index(info), skip=())

    def _bind_clicks(self, widget, i, skip):
        if widget in skip:
            return
        widget.bind("<Button-1>", lambda ev: self.select(i))
        widget.bind("<Double-Button-1>", lambda ev: self.app.add_entry(self.entries[i]))
        for child in widget.winfo_children():
            self._bind_clicks(child, i, skip)

    def _paint(self, widget, bg):
        if isinstance(widget, ttk.Widget):
            return
        try:
            widget.config(bg=bg)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._paint(child, bg)

    # --- selection ---
    def _unselect(self):
        if self.selected is not None and self.selected < len(self.cards):
            old = self.cards[self.selected]
            if old["detail"]:
                old["detail"].destroy()
                old["detail"] = None
            old["frame"].config(highlightbackground=CARD_BORDER)
            self._paint(old["frame"], CARD_BG)
            old["dot"].config(image=IMG["radio_off"])
            old["tag"].pack_forget()
        self.selected = None

    def select(self, i):
        if self.selected == i:
            return
        self._unselect()
        self.selected = i
        c = self.cards[i]
        c["frame"].config(highlightbackground=GOLD_EDGE)
        self._paint(c["frame"], SELECT_BG)
        c["dot"].config(image=IMG["radio_on"])
        c["tag"].pack(side="right", padx=(0, 10))
        self._detail(c, self.entries[i])
        self.hint.config(foreground=MUTED)
        self.app.update_add_button()

    def clear_selection(self):
        self._unselect()
        self.app.update_add_button()

    def selected_entry(self):
        return self.entries[self.selected] if self.selected is not None else None

    def nudge(self):
        self.hint.config(foreground=DOWN, text="Click one of the results below to select it first "
                                               "(or use a result's own + Watchlist button).")

    def _refresh_button(self, info, e):
        on = any(w["id"] == e["id"] for w in self.app.watch)
        info["btn"].config(text="✓ On watchlist" if on else "+ Watchlist",
                           state="disabled" if on else "normal")

    def refresh_buttons(self):
        for info, e in zip(self.cards, self.entries):
            self._refresh_button(info, e)


# ---------------------------------------------------------------- main window

class App:
    QUALITY_OPTIONS = [("Any quality", None), ("Common or better", "COMMON"),
                       ("Uncommon or better", "UNCOMMON"), ("Rare or better", "RARE"),
                       ("Epic or better", "EPIC")]
    SORT_OPTIONS = ["Best match", "Most listed", "Lowest price", "Highest price", "Name (A-Z)"]

    def __init__(self, root):
        self.root = root
        root.title(f"{APP_NAME} ({APP_VERSION})")
        root.geometry("1260x840")
        root.minsize(980, 560)
        self.watch = wp.load_watchlist()
        self.lock = threading.Lock()          # one Blizzard download at a time
        self.results = queue.Queue()
        self.view = "intro"                   # what the Watchlist tab's text area shows
        self.last_check = None
        self.scope = None                     # (class_id, subclass_id, class_name, sub_name) or None
        self.cat_names = {}
        self._filter_job = None


        # --- menu bar ---
        menubar = tk.Menu(root)
        tools = tk.Menu(menubar, tearoff=0)
        tools.add_command(label="Professions...", command=self.open_professions)
        tools.add_separator()
        tools.add_command(label="Sell-price helper...", command=self.open_sell)
        tools.add_command(label="Best time to sell...", command=self.open_timing)
        tools.add_command(label="Flip finder...", command=lambda: FlipWindow(self))
        tools.add_separator()
        tools.add_command(label="Crafting profit...", command=lambda: CraftingWindow(self))
        tools.add_separator()
        tools.add_command(label="Guild crafters...", command=self.open_guild)
        tools.add_separator()
        tools.add_command(label="Fishing session...", command=self.open_fishing)
        tools.add_command(label="Fishing spot planner...", command=lambda: SpotWindow(self))
        menubar.add_cascade(label="Tools", menu=tools)
        export = tk.Menu(menubar, tearoff=0)
        export.add_command(label="Price history to CSV...", command=self.export_history)
        export.add_command(label="Fishing sessions to CSV...", command=self.export_sessions)
        menubar.add_cascade(label="Export", menu=export)
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="Support the project (PayPal)...", command=self.open_donate)
        helpm.add_command(label="Report a bug...", command=self.report_bug)
        helpm.add_command(label="Get the latest version (GitHub)...",
                          command=lambda: webbrowser.open_new_tab(RELEASES_URL))
        helpm.add_separator()
        helpm.add_command(label="About and license...", command=self.open_about)
        helpm.add_command(label="Privacy policy...", command=self.open_privacy)
        menubar.add_cascade(label="Help", menu=helpm)
        root.config(menu=menubar)

        # --- pixel-art banner with the game picker and fishing button ---
        banner = Banner(root)
        banner.pack(fill="x", pady=(4, 0))
        Banner.trim(root).pack(fill="x", pady=(2, 6))
        ctl = banner.controls
        ttk.Label(ctl, text="Game", style="Banner.TLabel").pack(side="left")
        self.game = ttk.Combobox(ctl, values=["WoW: Forever", "Retail"], state="readonly", width=14)
        self.game.set("WoW: Forever")
        self.game.pack(side="left", padx=(6, 12))
        self.game.bind("<<ComboboxSelected>>", self.on_game_change)
        ttk.Button(ctl, text="Professions", command=self.open_professions).pack(side="left", padx=(0, 6))
        ttk.Button(ctl, text="Fishing session", command=self.open_fishing).pack(side="left")
        self.support_btn = ttk.Button(ctl, text="Support", command=self.open_support_menu)
        self.support_btn.pack(side="left", padx=(6, 0))

        self.status = ttk.Label(root, anchor="w", padding=(12, 2, 12, 6), style="Status.TLabel")
        self.status.pack(side="bottom", fill="x")

        self.tabs = ttk.Notebook(root, style="Main.TNotebook")
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self._build_search_tab()
        self._build_watch_tab()
        self.char_tab = CharacterTab(self.tabs, self)
        self.tabs.add(self.char_tab, text="  Character  ")
        self.monster_tab = MonsterTab(self.tabs, self)
        self.tabs.add(self.monster_tab, text="  Monster Compendium  ")
        self.dungeon_tab = DungeonTab(self.tabs, self)
        self.tabs.add(self.dungeon_tab, text="  Dungeons  ")
        self.progress_tab = ProgressTab(self.tabs, self)
        self.tabs.add(self.progress_tab, text="  Progress  ")

        self.refresh_list()
        self.show("Your watchlist, grouped by auction-house category.\n\n"
                  "Check all prices your whole list, with Day / Week / Month trends.\n"
                  "Price history shows a chart for the selected item.\n"
                  "Sell helper and Best time to sell help you pick when and how to list.\n"
                  "Set alert pops up a notice when an item crosses a price you pick.\n"
                  "Double-click an item to see it on the Search tab.\n\n"
                  "Add items from the Search tab with + Watchlist.\n\n"
                  "History and alerts are checked every hour while this window is open\n"
                  "(minimized is fine), so trends fill in over the coming days.\n\n"
                  "The Tools menu has the flip finder, crafting profit and fishing spot\n"
                  "planner. Export saves your data as CSV.")
        self.set_status()
        root.after(100, self.poll_results)
        root.after(1000, self.load_categories)
        root.after(3000, self.auto_check)
        root.after(1500, self.sweep_old_data)

    # ------------------------------------------------------------ layout
    def _build_search_tab(self):
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="  Search  ")
        self.search_tab = tab

        left = ttk.Frame(tab, width=250)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        ttk.Label(left, text="Categories", font=F(10, "bold"), foreground=GOLD).pack(anchor="w")
        ttk.Label(left, text="Click one to search inside it.\nWith no search text, it lists\n"
                             "everything for sale in it.", foreground=MUTED).pack(anchor="w", pady=(0, 4))
        cbox = ttk.Frame(left)
        cbox.pack(fill="both", expand=True)
        self.ctree = ttk.Treeview(cbox, show="tree", selectmode="browse", style="Side.Treeview")
        csb = ttk.Scrollbar(cbox, orient="vertical", command=self.ctree.yview)
        self.ctree.configure(yscrollcommand=csb.set)
        csb.pack(side="right", fill="y")
        self.ctree.pack(side="left", fill="both", expand=True)
        self.ctree.tag_configure("all", font=F(10, "bold"), foreground=GOLD)
        self.ctree.bind("<<TreeviewSelect>>", self.on_category)
        self.ctree.insert("", "end", iid="all", text="All categories", tags=("all",))
        self.ctree.selection_set("all")

        right = ttk.Frame(tab)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        row = ttk.Frame(right)
        row.pack(fill="x")
        self.item = ttk.Entry(row, font=F(11))
        self.item.pack(side="left", fill="x", expand=True)
        self.item.bind("<Return>", lambda e: self.lookup())
        self.item.bind("<Key>", self.on_typing)
        self.item.focus()
        self.btn_check = ttk.Button(row, text="Search", command=self.lookup)
        self.btn_check.pack(side="left", padx=6)
        self.btn_add = ttk.Button(row, text="Add to watchlist", width=24, command=self.add_item)
        self.btn_add.pack(side="left")
        self.scope_label = ttk.Label(right, text="Searching in: All categories", foreground=MUTED)
        self.scope_label.pack(anchor="w", pady=(3, 4))

        f = ttk.LabelFrame(right, text="Filters", padding=(8, 4))
        f.pack(fill="x", pady=(0, 6))
        self.f_quality = ttk.Combobox(f, state="readonly", width=18,
                                      values=[q for q, _ in self.QUALITY_OPTIONS])
        self.f_quality.current(0)
        self.f_quality.pack(side="left")
        ttk.Label(f, text="   Req. level").pack(side="left")
        self.f_lmin = ttk.Entry(f, width=4)
        self.f_lmin.pack(side="left", padx=(4, 0))
        ttk.Label(f, text="-").pack(side="left", padx=2)
        self.f_lmax = ttk.Entry(f, width=4)
        self.f_lmax.pack(side="left")
        ttk.Label(f, text="   Price").pack(side="left")
        self.f_pmin = ttk.Entry(f, width=8)
        self.f_pmin.pack(side="left", padx=(4, 0))
        ttk.Label(f, text="-").pack(side="left", padx=2)
        self.f_pmax = ttk.Entry(f, width=8)
        self.f_pmax.pack(side="left")
        self.f_listed = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="For sale only", variable=self.f_listed,
                        command=self.apply_filters).pack(side="left", padx=(12, 0))
        ttk.Button(f, text="Reset", width=6, command=self.reset_filters).pack(side="right")
        self.f_quality.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
        for en in (self.f_lmin, self.f_lmax, self.f_pmin, self.f_pmax):
            en.bind("<KeyRelease>", lambda e: self.apply_filters(delay=350))

        self.cards = ResultCards(right, self)
        self.cards.pack(fill="both", expand=True)
        ttk.Label(self.cards.bar_right, text="Sort:").pack(side="left", padx=(0, 4))
        self.f_sort = ttk.Combobox(self.cards.bar_right, state="readonly", width=13, values=self.SORT_OPTIONS)
        self.f_sort.current(0)
        self.f_sort.pack(side="left")
        self.f_sort.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
        self.cards.message("Type an item name (or ID) and press Enter, or pick a category on the left.\n\n"
                           "Click a result to select it, then Add to watchlist - or use its own "
                           "+ Watchlist button.\nClick an item's name to open it on Wowhead.")

    def _build_watch_tab(self):
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="  Watchlist  ")
        self.watch_tab = tab

        left = ttk.Frame(tab, width=280)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.wtree = ttk.Treeview(left, show="tree", selectmode="browse", style="Side.Treeview")
        self.wtree.pack(fill="both", expand=True)
        self.wtree.tag_configure("cat", foreground=GOLD_EDGE, font=F(9, "bold"))
        self.wtree.bind("<Double-Button-1>", self.lookup_selected)
        self.btn_all = ttk.Button(left, text="Check all", command=self.check_all)
        self.btn_all.pack(fill="x", pady=(6, 0))
        ttk.Button(left, text="Price history", command=self.open_history).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="Sell helper", command=self.open_sell).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="Best time to sell", command=self.open_timing).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="Set alert...", command=self.open_alert).pack(fill="x", pady=(4, 0))
        ttk.Button(left, text="Remove selected", command=self.remove_item).pack(fill="x", pady=(4, 0))

        self.out = OutputText(tab)
        self.out.pack(side="left", fill="both", expand=True, padx=(10, 0))

    # ------------------------------------------------------------ helpers
    def game_key(self):
        return "retail" if self.game.get() == "Retail" else "forever"

    def use_text(self):
        pass        # the watchlist tab's text area is always visible on its tab

    def show(self, text):
        """Message in the Watchlist tab's text area."""
        self.view = "text"
        self.out.show(text)

    def on_search_tab(self):
        return self.tabs.index("current") == 0

    def update_add_button(self):
        picked = self.cards.selected is not None
        self.btn_add.config(text="Add selected to watchlist" if picked else "Add to watchlist")

    def on_typing(self, event):
        # typing a new search means the old selection no longer applies
        if event.keysym not in ("Return", "Tab") and self.cards.selected is not None:
            self.cards.clear_selection()

    def selected_entry(self, action):
        e = self.selected_watch()
        if not e:
            self.show(f"Click an item in the watchlist first, then {action}.")
        return e

    def busy(self, on, msg=None, where="out"):
        for b in (self.btn_check, self.btn_add, self.btn_all):
            b.config(state="disabled" if on else "normal")
        if msg:
            if where == "cards":
                self.cards.message(msg)
            else:
                self.show(msg)

    # ------------------------------------------------------------ filters
    def filters(self):
        """Current filter settings. Bad entries are reported and ignored."""
        f, errors = {}, []
        f["quality"] = dict(self.QUALITY_OPTIONS).get(self.f_quality.get())
        for key, entry, label in (("lmin", self.f_lmin, "level"), ("lmax", self.f_lmax, "level")):
            t = entry.get().strip()
            if t and not t.isdigit():
                errors.append(f"Level should be a number, like 20.")
            f[key] = int(t) if t.isdigit() else None
        for key, entry in (("pmin", self.f_pmin), ("pmax", self.f_pmax)):
            try:
                f[key] = wp.parse_gold(entry.get())
            except ValueError as e:
                errors.append(str(e))
                f[key] = None
        f["listed"] = self.f_listed.get()
        f["sort"] = self.f_sort.get()
        f["error"] = errors[0] if errors else None
        return f

    def apply_filters(self, delay=0):
        if self._filter_job:
            self.root.after_cancel(self._filter_job)
            self._filter_job = None
        if delay:
            self._filter_job = self.root.after(delay, self.apply_filters)
            return
        if self.cards.all_entries:
            self.cards.render()

    def reset_filters(self):
        self.f_quality.current(0)
        self.f_sort.current(0)
        for en in (self.f_lmin, self.f_lmax, self.f_pmin, self.f_pmax):
            en.delete(0, "end")
        self.f_listed.set(True)
        self.apply_filters()

    # ------------------------------------------------------------ search and browse
    def lookup(self, item=None, by_id=False):
        item = item or self.item.get().strip()
        game = self.game_key()
        scope = None if by_id else self.scope
        if not item:
            if scope:
                return self.browse()
            self.cards.message("Type an item name (or ID), or pick a category on the left.")
            return
        where = f" in {wp.category_label(scope[2], scope[3])}" if scope else ""
        self.busy(True, f"Searching for {item}{where}...\n(The first check each hour downloads fresh "
                        "data and can take up to a minute.)", where="cards")

        def done(res):
            result, err = res
            self.busy(False)
            if result is None:
                self.cards.message(err or f'Couldn\'t look up "{item}".')
                return
            if not result["items"]:
                self.cards.message(f'No item found matching "{item}"{where}. Check the spelling, try the '
                                   "item ID from Wowhead, or search All categories.")
                return
            self.cards.show(result, game)
            if wp.snapshot_note():
                self.set_status()

        cid, sid = (scope[0], scope[1]) if scope else (None, None)
        self.in_background(lambda: capture(lambda: wp.lookup_items(
            wp.connect(game), item, class_id=cid, subclass_id=sid)), done)

    def browse(self):
        cid, sid, cname, sname = self.scope
        label = wp.category_label(cname, sname)
        game = self.game_key()
        self.busy(True, f"Loading everything listed in {label}...\n(The first time you open a category "
                        "it can take a few seconds; after that it's remembered for a week.)", where="cards")

        def done(res):
            result, err = res
            self.busy(False)
            if result is None:
                self.cards.message(err or f"Couldn't load {label}.")
                return
            if not result["items"]:
                self.cards.message(f"Nothing in {label} is listed on the auction house right now.")
                return
            self.cards.show(result, game)
            if wp.snapshot_note():
                self.set_status()

        self.in_background(lambda: capture(lambda: wp.browse_category(
            wp.connect(game), cid, sid, cname, sname)), done)

    def lookup_selected(self, _event=None):
        e = self.selected_watch()
        if e:
            self.tabs.select(0)
            self.item.delete(0, "end")
            self.item.insert(0, e["name"])
            self.lookup(str(e["id"]), by_id=True)

    def on_game_change(self, _event=None):
        if hasattr(self, "char_tab"):
            self.char_tab.on_game_change()
        self.scope = None
        self.scope_label.config(text="Searching in: All categories")
        self.load_categories()

    def load_categories(self):
        game = self.game_key()
        for iid in self.ctree.get_children():
            if iid != "all":
                self.ctree.delete(iid)
        self.ctree.insert("", "end", iid="loading", text="Loading categories...")
        self.ctree.selection_set("all")

        def done(res):
            cats, err = res
            if self.ctree.exists("loading"):
                self.ctree.delete("loading")
            if not cats:
                self.ctree.insert("", "end", iid="retry", text="Couldn't load - click to retry")
                self.set_status("couldn't load categories")
                return
            self.cat_names = {}
            for c in cats:
                cid = f"c:{c['id']}"
                self.cat_names[cid] = (c["id"], None, c["name"], None)
                self.ctree.insert("", "end", iid=cid, text=c["name"], open=False)
                for sc in c["subs"]:
                    sid = f"s:{c['id']}:{sc['id']}"
                    self.cat_names[sid] = (c["id"], sc["id"], c["name"], sc["name"])
                    self.ctree.insert(cid, "end", iid=sid, text=sc["name"])

        self.in_background(lambda: capture(lambda: wp.get_categories(wp.connect(game))), done)

    def on_category(self, _event=None):
        sel = self.ctree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid == "retry":
            return self.load_categories()
        if iid == "all":
            self.scope = None
        elif iid in self.cat_names:
            self.scope = self.cat_names[iid]
            if self.scope[1] is None:
                self.ctree.item(iid, open=True)
        else:
            return
        label = wp.category_label(self.scope[2], self.scope[3]) if self.scope else "All categories"
        self.scope_label.config(text=f"Searching in: {label}")
        if self.item.get().strip() or self.scope:
            self.lookup()

    # ------------------------------------------------------------ watchlist
    def add_entry(self, entry):
        """Add an item (dict with id and name) straight to the watchlist."""
        if any(e["id"] == entry["id"] for e in self.watch):
            self.set_status(f"{entry['name']} is already on your watchlist")
            return
        self.watch.append({"id": entry["id"], "name": entry["name"],
                           "cls": entry.get("cls"), "sub": entry.get("sub")})
        wp.save_watchlist(self.watch)
        self.refresh_list(select_id=entry["id"])
        self.cards.refresh_buttons()
        self.set_status(f"added {entry['name']} to your watchlist")

    def add_item(self):
        picked = self.cards.selected_entry()
        if picked:
            self.add_entry(picked)
            return
        if len(self.cards.entries) > 1:
            self.cards.nudge()
            return
        if len(self.cards.entries) == 1:
            self.add_entry(self.cards.entries[0])
            return
        query = self.item.get().strip()
        if not query:
            self.cards.message("Search for an item first, then add it to your watchlist.")
            return
        game = self.game_key()
        self.busy(True)

        def done(res):
            entry, err = res
            self.busy(False)
            if not entry:
                self.cards.message(err or f'Couldn\'t find "{query}". Check the spelling or use the item ID.')
                return
            info = wp.cached_info(game, entry["id"])
            self.add_entry({**entry, "cls": info.get("cls"), "sub": info.get("sub")})

        self.in_background(lambda: capture(lambda: wp.resolve_cached(wp.connect(game), query)), done)

    def remove_item(self):
        e = self.selected_entry("Remove selected")
        if not e:
            return
        self.watch.remove(e)
        wp.save_watchlist(self.watch)
        self.refresh_list()
        self.cards.refresh_buttons()
        self.set_status(f"removed {e['name']}")

    def open_guild(self):
        """Who in the guild can craft what, for the guild of the character on the Progress tab."""
        snap = getattr(self.progress_tab, "snap", None)
        if not snap or not snap.get("guild"):
            saved = wpg.load_saved()["chars"]
            snap = next((c for c in saved.values() if c.get("guild")), None)
        if not snap:
            messagebox.showinfo("Guild crafters", "Load a character that's in a guild on the Progress tab first.",
                                parent=self.root)
            return
        GuildWindow(self, snap.get("guild_slug") or wpg.guild_slug(snap["guild"]), snap["guild"])

    def copy_way(self, text):
        """Put a TomTom waypoint command on the clipboard."""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        Toast(self.root, "Copied. Paste it into the game's chat box (needs the TomTom addon):\n" + text)

    def in_background(self, work, done):
        """Run work() on a worker thread; done(result) runs back on the window thread."""
        def run():
            with self.lock:
                result = work()
            self.results.put((done, result))
        threading.Thread(target=run, daemon=True).start()

    def poll_results(self):
        while True:
            try:
                done, result = self.results.get_nowait()
            except queue.Empty:
                break
            try:
                done(result)
            except tk.TclError:
                pass        # the window it was for was closed
        self.root.after(100, self.poll_results)

    def refresh_list(self, select_id=None):
        """Watchlist grouped by auction-house category, like the in-game AH."""
        sel = self.wtree.selection()
        keep = f"item:{select_id}" if select_id is not None else (sel[0] if sel else None)
        closed = {iid for iid in self.wtree.get_children() if not self.wtree.item(iid, "open")}
        self.wtree.delete(*self.wtree.get_children())
        groups = {}
        for e in self.watch:
            groups.setdefault(wp.category_label(e.get("cls"), e.get("sub")), []).append(e)
        for cat in sorted(groups, key=lambda c: (c == "Uncategorized", c)):
            gid = f"cat:{cat}"
            self.wtree.insert("", "end", iid=gid, text=f"{cat}  ({len(groups[cat])})",
                              open=gid not in closed, tags=("cat",))
            for e in sorted(groups[cat], key=lambda x: x["name"].lower()):
                has_alert = e.get("alert_below") is not None or e.get("alert_above") is not None
                self.wtree.insert(gid, "end", iid=f"item:{e['id']}",
                                  text=e["name"] + ("   [alert]" if has_alert else ""))
        if keep and self.wtree.exists(keep):
            self.wtree.selection_set(keep)
            self.wtree.see(keep)

    def set_status(self, extra=None):
        parts = ["Auto-checks every hour while open"]
        if self.last_check:
            parts.append(f"last checked {clock(self.last_check)}")
        alerts = sum(1 for e in self.watch
                     if e.get("alert_below") is not None or e.get("alert_above") is not None)
        if alerts:
            parts.append(f"{alerts} alert{'s' if alerts != 1 else ''} active")
        if extra:
            parts.append(extra)
        note = wp.snapshot_note()               # e.g. "14 of 15 auction houses answered - ..."
        if note:
            parts.append(note)
        self.status.config(text="  ·  ".join(parts))

    def selected_watch(self):
        sel = self.wtree.selection()
        if not sel or not sel[0].startswith("item:"):
            return None
        item_id = int(sel[0][5:])
        return next((e for e in self.watch if e["id"] == item_id), None)

    def check_all(self):
        if not self.watch:
            self.show("Your watchlist is empty. Type an item and click Add to watchlist.")
            return
        game = self.game_key()
        entries = list(self.watch)
        self.busy(True, f"Checking {len(entries)} items...\n(The first check each hour "
                        "downloads fresh data and can take up to a minute.)")

        def done(res):
            rows, err = res
            self.busy(False)
            if rows is None:
                self.show(err or "Couldn't check prices.")
                return
            self.handle_rows(rows, game, show=True)

        self.in_background(lambda: capture(lambda: wp.check_watchlist(wp.connect(game), entries)), done)

    def handle_rows(self, rows, game, show):
        self.last_check = time.time()
        # older watchlist entries learn their category the first time they're checked
        cats = {r["id"]: (r.get("cls"), r.get("sub")) for r in rows if r.get("cls")}
        changed = False
        for e in self.watch:
            if e["id"] in cats and (e.get("cls"), e.get("sub")) != cats[e["id"]]:
                e["cls"], e["sub"] = cats[e["id"]]
                changed = True
        if changed:
            wp.save_watchlist(self.watch)
            self.refresh_list()
        if show:
            self.render_table(rows, game)
        # with auction houses missing, a price can look higher than it is: alerts wait for whole data
        fired = [] if any(r.get("partial") for r in rows) else self.evaluate_alerts(rows)
        for msg in fired:
            Toast(self.root, msg)
        self.set_status(f"{len(fired)} alert{'s' if len(fired) != 1 else ''} triggered" if fired else None)

    def render_table(self, rows, game):
        self.view = "table"
        self.use_text()
        o = self.out
        o.begin()
        w = max(10, min(26, max(len(r["name"]) for r in rows)))
        o.emit(f"{'Item':<{w}} {'Lowest':>11} {'Market':>11} {'Qty':>7} "
               f"{'Day':>7} {'Week':>7} {'Month':>7}\n", "bold")
        o.emit("-" * (w + 56) + "\n", "muted")
        groups = {}
        for r in rows:
            groups.setdefault(wp.category_label(r.get("cls"), r.get("sub")), []).append(r)
        ordered = []
        for cat in sorted(groups, key=lambda c: (c == "Uncategorized", c)):
            ordered.append(cat)
            ordered.extend(sorted(groups[cat], key=lambda x: x["name"].lower()))
        for r in ordered:
            if isinstance(r, str):
                o.emit(("\n" if r != ordered[0] else "") + r + "\n", "gold", "bold")
                continue
            name = r["name"][:w]
            o.emit_link(name, wowhead_url(r["id"], game))
            o.emit(" " * (w - len(name)))
            if r["found"]:
                o.emit(f" {wp.fmt_gold(r['lowest']):>11} {wp.fmt_gold(r['cheap10']):>11}"
                       f" {r['quantity']:>7,}")
                for k in ("day", "week", "month"):
                    p = r.get(k)
                    o.emit(f" {wp.fmt_pct(p):>7}", trend_tag(p))
            else:
                o.emit(f" {'not listed':>11}", "muted")
            o.emit("\n")
        ts = rows[0].get("ts") if rows else None
        o.emit("\nMarket = average of the cheapest 10% listed.\n"
               "Day / Week / Month = change in market price since then.\n", "muted")
        o.emit("-- means not enough history yet; it fills in as the app runs.", "muted")
        if ts:
            o.emit(f"\nAuction data as of {clock(ts)}.", "muted")
        o.end()

    def evaluate_alerts(self, rows):
        by_id = {r["id"]: r for r in rows if r.get("found")}
        fired, changed = [], False
        for e in self.watch:
            r = by_id.get(e["id"])
            if not r:
                continue
            low = r["lowest"]
            for kind, test, word in (("below", lambda lim: low <= lim, "dropped to"),
                                     ("above", lambda lim: low >= lim, "rose to")):
                lim = e.get(f"alert_{kind}")
                if lim is None:
                    continue
                hit = test(lim)
                if hit and not e.get(f"alerted_{kind}"):
                    fired.append(f"{e['name']} {word} {wp.fmt_gold(low)}\n"
                                 f"(your alert: {kind} {wp.fmt_gold(lim)})")
                if hit != bool(e.get(f"alerted_{kind}")):
                    e[f"alerted_{kind}"] = hit
                    changed = True
        if changed:
            wp.save_watchlist(self.watch)
        return fired

    def sweep_old_data(self):
        """Delete Blizzard data older than 30 days (Blizzard Developer API Terms 2.18), in the background."""
        self._last_sweep = time.time()

        def work():
            try:
                return (wp.enforce_data_ttl() or 0) + (wpg.enforce_data_ttl() or 0)
            except Exception:
                wp.log.exception("couldn't clean up old Blizzard data")
                return 0
        self.in_background(work, lambda _n: None)

    def auto_check(self):
        self.root.after(AUTO_CHECK_MS, self.auto_check)
        if time.time() - getattr(self, "_last_sweep", 0) > 86400:     # once a day while the app stays open
            self.sweep_old_data()
        if not self.watch:
            return
        game = self.game_key()
        entries = list(self.watch)
        self.set_status("checking now...")

        def done(res):
            rows, err = res
            if rows is None:
                self.set_status(f"auto-check failed ({(err or 'unknown error').splitlines()[-1][:60]})")
                return
            self.handle_rows(rows, game, show=(self.view == "table"))

        self.in_background(lambda: capture(lambda: wp.check_watchlist(wp.connect(game), entries)), done)

    def open_alert(self):
        e = self.selected_entry("Set alert")
        if e:
            AlertDialog(self, e)

    def open_history(self):
        e = self.selected_entry("Price history")
        if e:
            HistoryWindow(self, e, self.game_key())

    def open_fishing(self):
        FishingWindow(self)

    def open_donate(self):
        webbrowser.open_new_tab(DONATE_URL)

    def open_support_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Donate on PayPal...", command=self.open_donate)
        menu.add_command(label="Report a bug...", command=self.report_bug)
        b = self.support_btn
        try:
            menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        finally:
            menu.grab_release()

    def report_bug(self):
        try:
            game = self.game.get()
        except Exception:
            game = "?"
        subject = f"{APP_NAME} {APP_VERSION} - bug report"
        body = (
            "What happened?\n\n\n"
            "What did you expect to happen?\n\n\n"
            "Steps to make it happen again:\n1.\n2.\n3.\n\n"
            "--- details (please leave these in) ---\n"
            f"App version: {APP_VERSION}\n"
            f"Game: {game}\n"
            f"Windows: {platform.platform()}\n"
            f"Time: {datetime.now():%Y-%m-%d %H:%M}\n")
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(f"To: {BUG_EMAIL}\nSubject: {subject}\n\n{body}")
        except tk.TclError:
            pass
        url = "mailto:" + BUG_EMAIL + "?" + urllib.parse.urlencode(
            {"subject": subject, "body": body}, quote_via=urllib.parse.quote)
        try:
            webbrowser.open(url)
        except Exception:
            pass
        messagebox.showinfo(
            "Report a bug",
            "Your email app should open with a bug report ready to fill in.\n\n"
            f"If it doesn't, send an email to {BUG_EMAIL}.\n"
            "The report template has been copied, so you can paste it into any email.\n\n"
            "Screenshots help a lot. Please don't include your Client Secret.",
            parent=self.root)

    def open_privacy(self):
        """The privacy policy (also PRIVACY.txt next to the app)."""
        webbrowser.open_new_tab(PRIVACY_URL)

    def open_about(self):
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME}  ·  {APP_VERSION}\n" + COPYRIGHT + "\n\n"
            "Free for personal, non-commercial use.\n"
            "Please don't redistribute, sell, modify or rebrand it without permission.\n"
            "Official download: " + RELEASES_URL.replace("https://", "") + "\n"
            "Full terms are in LICENSE.txt next to the app.\n\n"
            "If it saves you gold, you can support the project at:\n" + DONATE_URL + "\n"
            "Donations are optional and don't unlock anything.\n\n"
            "Monster Compendium, Dungeons and Progress data comes from QuestieDB "
            "(github.com/Questie/QuestieDB), the Questie addon's community database by the Questie team and "
            "contributors, used with their permission. It is downloaded from GitHub on your computer, isn't "
            "part of this app, and stays under QuestieDB's license: "
            "github.com/Questie/QuestieDB/blob/master/LICENSE.md\n\n"
            "Auction, item and character data comes from Blizzard Entertainment's API.\n"
            "Fan-made. Not affiliated with or endorsed by Blizzard Entertainment.\n"
            "World of Warcraft and Blizzard Entertainment are trademarks or registered trademarks of "
            "Blizzard Entertainment, Inc., in the U.S. and/or other countries.",
            parent=self.root)

    def open_professions(self):
        existing = [w for w in self.root.winfo_children() if isinstance(w, ProfessionsWindow)]
        if existing:
            existing[0].deiconify()
            existing[0].lift()
        else:
            ProfessionsWindow(self)

    def browse_materials(self, cat):
        """Show a category on the main Search tab (cat = class_id, subclass_id, names)."""
        iid = f"s:{cat[0]}:{cat[1]}" if cat[1] is not None else f"c:{cat[0]}"
        if not self.ctree.exists(iid):
            self.set_status("categories are still loading - try again in a moment")
            return
        self.tabs.select(0)
        self.item.delete(0, "end")
        self.ctree.item(f"c:{cat[0]}", open=True)
        self.ctree.see(iid)
        self.ctree.selection_set(iid)
        self.root.deiconify()
        self.root.lift()

    def open_timing(self):
        e = self.selected_entry("Best time to sell")
        if e:
            TimingWindow(self, e, self.game_key())

    def open_sell(self):
        query, picked = "", None
        if self.on_search_tab() and self.cards.selected_entry():
            picked = self.cards.selected_entry()
        elif not self.on_search_tab() and self.selected_watch():
            picked = self.selected_watch()
        if picked and picked.get("id") and picked.get("name"):
            query, picked = picked["name"], {"id": picked["id"], "name": picked["name"]}
        else:
            picked = None
            query = self.item.get().strip() or (self.selected_watch() or {}).get("name", "")
        SellWindow(self, query, picked)

    def export_history(self):
        self._export("Export price history", "wow_price_history.csv", wp.export_history_csv, "price points")

    def export_sessions(self):
        self._export("Export fishing sessions", "fishing_sessions.csv", wp.export_sessions_csv,
                     "rows (one per item per session)")

    def _export(self, title, filename, fn, what):
        path = filedialog.asksaveasfilename(parent=self.root, title=title, defaultextension=".csv",
                                            initialfile=filename, filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            n = fn(path)
            messagebox.showinfo("Export done", f"Exported {n:,} {what} to:\n{path}\n\n"
                                "Opens in Excel or Google Sheets. Prices are in gold (0.08 = 8 silver).",
                                parent=self.root)
        except OSError as e:
            messagebox.showerror("Export failed", f"Couldn't save the file: {e}\n\n"
                                 "Is it open in Excel? Close it and try again.", parent=self.root)


# ---------------------------------------------------------------- alert pop-up

class Toast(tk.Toplevel):
    """Small always-on-top notice in the bottom-right corner. Click to dismiss."""
    active = []

    def __init__(self, root, message):
        super().__init__(root)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        frame = tk.Frame(self, bg=PANEL_2, highlightbackground=GOLD, highlightthickness=2,
                         padx=14, pady=10)
        frame.pack()
        tk.Label(frame, text="Price alert", bg=PANEL_2, fg=GOLD,
                 font=F(11, "bold")).pack(anchor="w")
        tk.Label(frame, text=message, bg=PANEL_2, fg=TEXT, justify="left",
                 wraplength=320, font=M(11)).pack(anchor="w", pady=(4, 6))
        tk.Label(frame, text="click to dismiss", bg=PANEL_2, fg=MUTED,
                 font=F(8)).pack(anchor="e")
        for wdg in [self, frame, *frame.winfo_children()]:
            wdg.bind("<Button-1>", lambda e: self.close())
        Toast.active.append(self)
        self.place_me()
        try:
            root.bell()
        except tk.TclError:
            pass

    def place_me(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        n = Toast.active.index(self)
        x = self.winfo_screenwidth() - w - 20
        y = self.winfo_screenheight() - 70 - (h + 10) * (n + 1)
        self.geometry(f"+{x}+{max(y, 10)}")

    def close(self):
        if self in Toast.active:
            Toast.active.remove(self)
        self.destroy()
        for t in Toast.active:
            t.place_me()


class AlertDialog(tk.Toplevel):
    def __init__(self, app, entry):
        super().__init__(app.root)
        self.app, self.entry = app, entry
        self.title("Set price alert")
        self.resizable(False, False)
        self.transient(app.root)
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=entry["name"], font=F(11, "bold"), foreground=GOLD).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Alert me when the lowest price...").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 8))

        def prefill(key):
            v = entry.get(key)
            return wp.fmt_gold(v) if v is not None else ""

        ttk.Label(f, text="drops to or below:").grid(row=2, column=0, sticky="w")
        self.below = ttk.Entry(f, width=18)
        self.below.insert(0, prefill("alert_below"))
        self.below.grid(row=2, column=1, sticky="w", padx=(8, 0))
        ttk.Label(f, text="rises to or above:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.above = ttk.Entry(f, width=18)
        self.above.insert(0, prefill("alert_above"))
        self.above.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        ttk.Label(f, text="Examples: 8s   1g 50s   2.5g   (leave blank to skip)",
                  foreground=MUTED).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.err = ttk.Label(f, text="", foreground=DOWN)
        self.err.grid(row=5, column=0, columnspan=2, sticky="w")

        btns = ttk.Frame(f)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Clear alerts", command=self.clear).pack(side="left")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(btns, text="Save", command=self.save).pack(side="left")
        self.below.focus()
        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())

    def save(self):
        try:
            below = wp.parse_gold(self.below.get())
            above = wp.parse_gold(self.above.get())
        except ValueError as ex:
            self.err.config(text=str(ex))
            return
        if below is not None and above is not None and below >= above:
            self.err.config(text="The 'below' price should be lower than the 'above' price.")
            return
        self.apply(below, above)
        parts = []
        if below is not None:
            parts.append(f"drops to {wp.fmt_gold(below)} or less")
        if above is not None:
            parts.append(f"rises to {wp.fmt_gold(above)} or more")
        if parts:
            self.app.show(f"Alert set: you'll get a pop-up when {self.entry['name']} "
                          f"{' or '.join(parts)}.\n\nPrices are checked every hour while the app "
                          "is open, and whenever you click Check all.")
        else:
            self.app.show(f"Alerts cleared for {self.entry['name']}.")
        self.destroy()

    def clear(self):
        self.apply(None, None)
        self.app.show(f"Alerts cleared for {self.entry['name']}.")
        self.destroy()

    def apply(self, below, above):
        e = self.entry
        e["alert_below"], e["alert_above"] = below, above
        e["alerted_below"] = e["alerted_above"] = False
        for k in ("alert_below", "alert_above"):
            if e[k] is None:
                del e[k]
        wp.save_watchlist(self.app.watch)
        self.app.refresh_list()
        self.app.set_status()


# ---------------------------------------------------------------- history chart

class HistoryWindow(tk.Toplevel):
    def __init__(self, app, entry, game):
        super().__init__(app.root)
        self.entry, self.game = entry, game
        self.title(f"Price history - {entry['name']}")
        self.geometry("820x480")
        self.minsize(520, 320)

        top = ttk.Frame(self, padding=(12, 10, 12, 0))
        top.pack(fill="x")
        ttk.Label(top, text=entry["name"], font=F(12, "bold"), foreground=GOLD).pack(side="left")
        self.period = tk.StringVar(value="day")
        for label, key in (("Month", "month"), ("Week", "week"), ("Day", "day")):
            ttk.Radiobutton(top, text=label, value=key, variable=self.period,
                            command=self.draw).pack(side="right", padx=4)

        legend = ttk.Frame(self, padding=(12, 2, 12, 0))
        legend.pack(fill="x")
        tk.Label(legend, text="━ Market price", fg=GOLD, font=F(9, "bold")).pack(side="left")
        tk.Label(legend, text="   ━ Lowest price", fg=LINK, font=F(9, "bold")).pack(side="left")

        self.canvas = tk.Canvas(self, bg=INSET, highlightthickness=2, highlightbackground=BORDER)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=6)
        self.stats = ttk.Label(self, padding=(12, 0, 12, 10), font=M(11), wraplength=780)
        self.stats.pack(fill="x")
        self.canvas.bind("<Configure>", lambda e: self.draw())

    def draw(self):
        c = self.canvas
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50 or H < 50:
            return
        key = self.period.get()
        span = wp.PERIODS[key]
        data = wp.price_history(self.game, self.entry["id"], time.time() - span)
        if len(data) < 2:
            c.create_text(W / 2, H / 2, fill=MUTED, font=F(11), justify="center",
                          text=f"Not enough history for this {key} yet "
                               f"({len(data)} price point{'s' if len(data) != 1 else ''}).\n\n"
                               "A point is saved each hour while the app is open\n"
                               "and this item is on your watchlist.")
            self.stats.config(text="")
            return

        ts = [d[0] for d in data]
        low = [d[1] for d in data]
        mkt = [d[2] for d in data]
        lo, hi = min(low + mkt), max(low + mkt)
        rng = (hi - lo) or max(hi * 0.1, 1)
        lo, hi = max(0, lo - rng * 0.1), hi + rng * 0.1
        L, R, T, B = 118, 20, 16, 34
        x0, x1 = ts[0], ts[-1]

        def X(t):
            return L + (t - x0) / ((x1 - x0) or 1) * (W - L - R)

        def Y(v):
            return T + (hi - v) / (hi - lo) * (H - T - B)

        for i in range(5):
            v = lo + (hi - lo) * i / 4
            y = Y(v)
            c.create_line(L, y, W - R, y, fill=GRID, dash=(2, 4))
            c.create_text(L - 8, y, text=wp.fmt_gold(v), anchor="e", fill=MUTED, font=M(9))
        fmt = "%I:%M %p" if key == "day" else "%b %d"
        for frac, anchor in ((0, "w"), (0.5, "center"), (1, "e")):
            t = x0 + (x1 - x0) * frac
            c.create_text(X(t), H - B + 14, text=clock(t, fmt), anchor=anchor,
                          fill=MUTED, font=M(9))

        for series, color, width in ((low, LINK, 1.5), (mkt, GOLD, 2.5)):
            pts = [coord for t, v in zip(ts, series) for coord in (X(t), Y(v))]
            c.create_line(*pts, fill=color, width=width)
            if len(ts) <= 48:
                for t, v in zip(ts, series):
                    c.create_rectangle(X(t) - 3, Y(v) - 3, X(t) + 3, Y(v) + 3, fill=color, outline="#000000")

        avg = sum(mkt) / len(mkt)
        change = (mkt[-1] - mkt[0]) / mkt[0] * 100 if mkt[0] else None
        self.stats.config(text=f"Market now {wp.fmt_gold(mkt[-1])}   Low {wp.fmt_gold(min(mkt))}   "
                               f"High {wp.fmt_gold(max(mkt))}   Avg {wp.fmt_gold(avg)}   "
                               f"Change {wp.fmt_pct(change).strip()}    ({len(data)} points)")


# ---------------------------------------------------------------- fishing

GATHER_EXAMPLES = {
    "Fishing": "20 Raw Slitherskin Mackerel\n       Oily Blackmouth x12",
    "Mining": "20 Copper Ore\n       Rough Stone x8",
    "Herbalism": "15 Peacebloom\n       Silverleaf x9",
    "Skinning": "30 Light Leather\n       Ruined Leather Scraps x6",
}


class FishingWindow(tk.Toplevel):
    """Session value logger for fishing - or any gathering profession."""

    def __init__(self, app, profession="Fishing"):
        super().__init__(app.root)
        self.app = app
        self.prof = profession
        self.result = None
        self.title(f"{profession} session value")
        self.geometry("1100x660")
        self.minsize(760, 420)

        left = ttk.Frame(self, padding=12)
        left.pack(side="left", fill="y")
        ttk.Label(left, text=("What did you catch?" if profession == "Fishing" else "What did you gather?")
                  + " One item per line:",
                  font=F(10, "bold")).pack(anchor="w")
        self.catch = tk.Text(left, width=34, height=12, font=M(11), wrap="none")
        self.catch.pack(fill="y", expand=True, pady=(4, 2))
        ttk.Label(left, foreground=MUTED, justify="left",
                  text="e.g.  " + GATHER_EXAMPLES.get(profession, "20 Item Name\n       Other Item x5")
                       + "\n       6303 x5   (item IDs work too)").pack(anchor="w")

        form = ttk.Frame(left)
        form.pack(fill="x", pady=(10, 0))
        ttk.Label(form, text="Spot / route (optional):").grid(row=0, column=0, sticky="w")
        self.spot = ttk.Entry(form, width=22)
        self.spot.grid(row=0, column=1, sticky="we", padx=(6, 0))
        ttk.Label(form, text="Minutes fished:" if profession == "Fishing" else "Minutes spent:").grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        self.minutes = ttk.Entry(form, width=8)
        self.minutes.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(10, 0))
        self.btn_calc = ttk.Button(btns, text="Calculate value", command=self.calculate)
        self.btn_calc.pack(fill="x")
        self.btn_save = ttk.Button(btns, text="Save session", command=self.save, state="disabled")
        self.btn_save.pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="Past sessions & best spots", command=self.show_past).pack(fill="x", pady=(4, 0))

        self.out = OutputText(self)
        self.out.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)
        self.out.show(f"Enter what you {'caught' if profession == 'Fishing' else 'gathered'} on the left "
                      "and click Calculate value.\n\n"
                      "Add the spot or route and how long it took to get gold per hour,\n"
                      "then Save session to compare spots over time.")
        self.catch.focus()

    def read_minutes(self):
        t = self.minutes.get().strip()
        if not t:
            return None
        try:
            m = float(t)
            return m if m > 0 else None
        except ValueError:
            raise ValueError("Minutes fished should be a number, like 45.")

    def calculate(self):
        catch = wp.parse_catch(self.catch.get("1.0", "end"))
        if not catch:
            self.out.show("Type at least one item on the left first.")
            return
        try:
            minutes = self.read_minutes()
        except ValueError as ex:
            self.out.show(str(ex))
            return
        game = self.app.game_key()
        self.btn_calc.config(state="disabled")
        self.btn_save.config(state="disabled")
        self.out.show(f"Pricing {len(catch)} item{'s' if len(catch) != 1 else ''}...\n"
                      "(The first check each hour downloads fresh data and can take up to a minute.)")

        def done(res):
            result, err = res
            self.btn_calc.config(state="normal")
            if result is None:
                self.out.show(err or "Couldn't price your catch.")
                return
            result["minutes"], result["game"] = minutes, game
            self.result = result
            self.render(result)
            if result["rows"]:
                self.btn_save.config(state="normal")

        self.app.in_background(lambda: capture(lambda: wp.value_catch(wp.connect(game), catch)), done)

    def render(self, r):
        o = self.out
        o.begin()
        rows = sorted(r["rows"], key=lambda x: -x["total"])
        if rows:
            w = max(12, min(30, max(len(x["name"]) for x in rows)))
            o.emit(f"{'Qty':>5}  {'Item':<{w}}  {'Each':>12}  {'Total':>13}\n", "bold")
            o.emit("-" * (w + 38) + "\n", "muted")
            for x in rows:
                name = x["name"][:w]
                o.emit(f"{x['qty']:>5}  ")
                o.emit_link(name, wowhead_url(x["id"], r["game"]))
                o.emit(" " * (w - len(name)))
                if x["found"]:
                    o.emit(f"  {wp.fmt_gold(x['each']):>12}  {wp.fmt_gold(x['total']):>13}\n")
                else:
                    o.emit(f"  {'not listed':>12}  {'-':>13}\n", "muted")
            o.emit("-" * (w + 38) + "\n", "muted")
            o.emit(f"{'Total value:':<22}{wp.fmt_gold(r['total'])}\n", "bold")
            o.emit(f"{'After 5% AH cut:':<22}")
            o.emit(f"{wp.fmt_gold(r['after_cut'])}\n", "gold", "bold")
            if r.get("minutes"):
                gph = r["after_cut"] / r["minutes"] * 60
                r["gph"] = gph
                o.emit(f"{'Gold per hour:':<22}")
                o.emit(f"{wp.fmt_gold(gph)}", "gold", "bold")
                o.emit(f"   ({r['minutes']:g} min, after AH cut)\n", "muted")
        if r["unresolved"]:
            o.emit("\nCouldn't find: " + ", ".join(r["unresolved"]) +
                   "\nCheck the spelling, or use the item ID from Wowhead.\n", "down")
        o.emit("\nEach = market price (average of the cheapest 10% listed).", "muted")
        o.end()

    def save(self):
        r = self.result
        if not r:
            return
        spot = self.spot.get().strip() or "Unnamed spot"
        wp.save_session({
            "date": datetime.now().isoformat(timespec="minutes"),
            "game": r["game"], "profession": self.prof, "spot": spot, "minutes": r.get("minutes"),
            "total": int(r["total"]), "after_cut": int(r["after_cut"]),
            "gph": int(r["gph"]) if r.get("gph") else None,
            "items": [{"id": x["id"], "name": x["name"], "qty": x["qty"], "each": int(x["each"])}
                      for x in r["rows"]],
        })
        self.btn_save.config(state="disabled")
        self.out.config(state="normal")
        self.out.emit(f"\n\nSaved session at {spot}.", "up")
        self.out.end()

    def show_past(self):
        sessions = [x for x in wp.load_sessions() if x.get("profession", "Fishing") == self.prof]
        o = self.out
        o.begin()
        if not sessions:
            o.emit("No saved sessions yet. Calculate a catch, then click Save session.")
            o.end()
            return
        o.emit("Best spots (average gold per hour, after AH cut)\n", "bold")
        o.emit("-" * 58 + "\n", "muted")
        spots = {}
        for s in sessions:
            if s.get("gph"):
                spots.setdefault(s["spot"], []).append(s["gph"])
        if spots:
            ranked = sorted(spots.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
            for spot, g in ranked:
                o.emit(f"{spot[:28]:<28}  ")
                o.emit(f"{wp.fmt_gold(sum(g) / len(g)):>14}/hr", "gold")
                o.emit(f"   {len(g)} session{'s' if len(g) != 1 else ''}\n", "muted")
        else:
            o.emit("Add minutes fished when you calculate to rank spots by gold per hour.\n", "muted")

        o.emit("\nRecent sessions\n", "bold")
        o.emit(f"{'When':<12} {'Spot':<18} {'Time':>7} {'Value':>12} {'Per hour':>15}\n", "muted")
        o.emit("-" * 68 + "\n", "muted")
        for s in reversed(sessions[-15:]):
            when = datetime.fromisoformat(s["date"]).strftime("%b %d %H:%M")
            mins = f"{s['minutes']:g}m" if s.get("minutes") else ""
            gph = f"{wp.fmt_gold(s['gph'])}/hr" if s.get("gph") else ""
            o.emit(f"{when:<12} {s['spot'][:18]:<18} {mins:>7} "
                   f"{wp.fmt_gold(s['after_cut']):>12} {gph:>15}\n")
        o.end()


# ---------------------------------------------------------------- shared bits

def bar(pct, scale, width=18):
    n = int(round(abs(pct) / scale * width)) if scale else 0
    return "█" * max(n, 1 if abs(pct) >= 0.05 else 0)


def pct_tag(p):
    return "up" if p is not None and p > 0.05 else "down" if p is not None and p < -0.05 else "muted"


class ToolWindow(tk.Toplevel):
    def __init__(self, app, title, size):
        super().__init__(app.root)
        self.app = app
        self.title(title)
        self.geometry(size)
        self.minsize(640, 380)

    def run(self, fn, done, msg):
        game = self.app.game_key()
        self.out.show(msg + "\n(The first check each hour downloads fresh data and can take up to a minute.)")
        self.app.in_background(lambda: capture(lambda: fn(wp.connect(game))),
                               lambda res: done(res[0], res[1], game))


# ---------------------------------------------------------------- sell helper

class SellWindow(ToolWindow):
    def __init__(self, app, query="", picked=None):
        super().__init__(app, "Sell-price helper", "820x560")
        self.picked = picked               # {'id', 'name'} when opened from a selected item
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Item:").grid(row=0, column=0, sticky="w")
        self.item = ttk.Entry(top, width=34)
        self.item.insert(0, query)
        self.item.grid(row=0, column=1, sticky="we", padx=6)
        ttk.Label(top, text="How many you're selling (optional):").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.qty = ttk.Entry(top, width=8)
        self.qty.grid(row=0, column=3, sticky="w", padx=6)
        self.btn = ttk.Button(top, text="Analyze", command=self.analyze)
        self.btn.grid(row=0, column=4)
        top.columnconfigure(1, weight=1)
        self.out = OutputText(self)
        self.out.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.out.show("Enter an item and click Analyze for a suggested listing price,\n"
                      "how crowded the market is, and the cheapest listings you'd compete with.")
        self.bind("<Return>", lambda e: self.analyze())
        self.item.focus()
        if query:
            self.analyze()

    def analyze(self):
        query = self.item.get().strip()
        if not query:
            return
        q = self.qty.get().strip().replace(",", "")
        if q and not q.isdigit():
            self.out.show("How many you're selling should be a whole number, like 20.")
            return
        my_qty = int(q) if q else None
        self.btn.config(state="disabled")
        picked = self.picked if self.picked and self.picked["name"].lower() == query.lower() else None
        self.run(lambda api: wp.sell_advice(api, query, my_qty, picked), self.render, f"Analyzing {query}...")

    def render(self, r, err, game):
        self.btn.config(state="normal")
        o = self.out
        if r is None:
            o.show(err or f"Couldn't find that item. Check the spelling or use the item ID.")
            return
        o.begin()
        it = r["item"]
        o.emit_link(it["name"], wowhead_url(it["id"], game), "bold")
        o.emit("\n\n")
        if not r["listed"]:
            o.emit("Nobody is selling this right now, so you set the price.\n")
            h = r["hist"]
            if h:
                o.emit(f"Its usual market price over the last week was {wp.fmt_gold(h['median_market'])}.\n"
                       "Listing near that is a reasonable start.\n")
            o.end()
            return
        o.emit(f"Lowest {wp.fmt_gold(r['lowest'])}    Market {wp.fmt_gold(r['cheap10'])}    "
               f"Listed {r['quantity']:,} ({r['listings']:,} listings)\n\n")
        o.emit("Suggested listing price:  ", "bold")
        o.emit(wp.fmt_gold(r["suggested"]) + "\n", "gold", "bold")
        out = r["outlier"]
        if out:
            o.emit(f"   1c under the next real price. A small batch of {out['qty']} is listed at "
                   f"{wp.fmt_gold(out['price'])},\n   well below everyone else - consider buying it "
                   f"out instead of racing it down.\n")
        else:
            o.emit("   1c under the current lowest listing.\n")

        o.emit("\nMarket check\n", "bold")
        f = r["flood"]
        if f is None:
            o.emit("   Supply: not enough history yet to compare with normal.\n", "muted")
        elif f >= 1.5:
            o.emit(f"   Flooded: {f:.1f}x more listed than usual. Prices may dip - consider waiting\n"
                   "   or undercutting a bit more to sell fast.\n", "down")
        elif f <= 0.6:
            o.emit(f"   Low supply: only {f * 100:.0f}% of the usual amount listed. Good time to sell.\n", "up")
        else:
            o.emit(f"   Supply is normal ({f * 100:.0f}% of usual).\n")
        v = r["vs_usual"]
        if v is None:
            o.emit("   Price: not enough history yet to compare with the past week.\n", "muted")
        elif v >= 5:
            o.emit(f"   Price is {v:.0f}% above its usual level this week. Good time to sell.\n", "up")
        elif v <= -5:
            o.emit(f"   Price is {-v:.0f}% below its usual level this week. If you can wait, it may recover.\n", "down")
        else:
            o.emit(f"   Price is close to its usual level ({v:+.0f}%).\n")

        if r["my_qty"]:
            o.emit(f"\nSelling {r['my_qty']:,} at {wp.fmt_gold(r['suggested'])}\n", "bold")
            ahead = r["ahead"]
            o.emit("   You'd be the cheapest listing.\n" if not ahead else
                   f"   {ahead:,} units are cheaper than you and sell first.\n")
            o.emit(f"   You'd receive about {wp.fmt_gold(r['payout'])} after the 5% AH cut.\n")

        o.emit("\nCheapest listings\n", "bold")
        o.emit(f"   {'Price':>12}  {'Qty':>8}  {'Running total':>14}\n", "muted")
        for price, qty, cum in r["ladder"]:
            o.emit(f"   {wp.fmt_gold(price):>12}  {qty:>8,}  {cum:>14,}\n")
        o.end()


# ---------------------------------------------------------------- best time to sell

class TimingWindow(ToolWindow):
    def __init__(self, app, entry, game):
        super().__init__(app, f"Best time to sell - {entry['name']}", "700x560")
        self.out = OutputText(self)
        self.out.pack(fill="both", expand=True, padx=12, pady=12)
        r = wp.sell_timing(game, entry["id"])
        o = self.out
        o.begin()
        o.emit_link(entry["name"], wowhead_url(entry["id"], game), "bold")
        o.emit(f"\nBased on {r['points']} price point{'s' if r['points'] != 1 else ''} "
               f"over {r['span_days']:.1f} days.\n\n", "muted")
        if not r["hours"] and not r["weekdays"]:
            o.emit("Not enough history yet.\n\n"
                   "Time-of-day patterns need about 2 days of hourly prices,\n"
                   "and day-of-week patterns need about a week.\n"
                   "Prices are saved each hour while the app is open with this item\n"
                   "on your watchlist.", "muted")
            o.end()
            return
        best = []
        if r["weekdays"]:
            best.append(self.section("By day of week", "compared with that week's typical price",
                                     wp.WEEKDAYS, r["weekdays"], 5))
        else:
            o.emit("By day of week: needs about a week of history.\n\n", "muted")
        if r["hours"]:
            best.append(self.section("By time of day", "compared with that day's typical price",
                                     wp.HOUR_BLOCKS, r["hours"], 11))
        o.emit("Best time to post: ", "bold")
        o.emit(", ".join(b for b in best if b) or "no clear pattern yet", "gold", "bold")
        o.emit("\n\nThese are averages. Differences under about 2% are mostly noise,\n"
               "and patterns get more reliable the longer the app collects history.", "muted")
        o.end()

    def section(self, title, sub, labels, data, w):
        o = self.out
        o.emit(f"{title}", "bold")
        o.emit(f"  ({sub})\n", "muted")
        vals = [v for v, c in data if v is not None]
        scale = max([abs(v) for v in vals] + [0.5])
        for label, (v, c) in zip(labels, data):
            if v is None:
                o.emit(f"  {label:<{w}}      --\n", "muted")
                continue
            o.emit(f"  {label:<{w}} ")
            o.emit(f"{v:+6.1f}%  ", pct_tag(v))
            o.emit(bar(v, scale), pct_tag(v))
            o.emit(f"  ({c})\n", "muted")
        o.emit("\n")
        scored = [(v, l) for l, (v, c) in zip(labels, data) if v is not None and c >= 2]
        if not scored:
            return None
        top = max(scored)
        return top[1] if top[0] >= 1 else None


# ---------------------------------------------------------------- flip finder

class FlipWindow(ToolWindow):
    def __init__(self, app):
        super().__init__(app, "Flip finder", "900x520")
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Show items listed at least").pack(side="left")
        self.th = ttk.Entry(top, width=5)
        self.th.insert(0, "15")
        self.th.pack(side="left", padx=4)
        ttk.Label(top, text="% below their usual price").pack(side="left")
        self.btn = ttk.Button(top, text="Find flips", command=self.search)
        self.btn.pack(side="left", padx=10)
        self.out = OutputText(self)
        self.out.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.out.show("Scans your watchlist and items you've looked up for anything listed well\n"
                      "below its usual price (the median of the past 7 days), so you can buy\n"
                      "it cheap and relist at the usual price.\n\nClick Find flips.")

    def search(self):
        try:
            th = float(self.th.get().strip().rstrip("%"))
            assert 1 <= th <= 90
        except (ValueError, AssertionError):
            self.out.show("Enter a percent between 1 and 90, like 15.")
            return
        self.btn.config(state="disabled")
        self.run(lambda api: wp.find_flips(api, th / 100), self.render, "Scanning for flips...")

    def render(self, r, err, game):
        self.btn.config(state="normal")
        o = self.out
        if r is None:
            o.show(err or "Couldn't scan.")
            return
        o.begin()
        flips = r["flips"]
        if flips:
            w = max(10, min(26, max(len(f["name"]) for f in flips)))
            o.emit(f"{'Item':<{w}} {'Lowest':>11} {'Usual':>11} {'Off':>5} {'Cheap units':>11} "
                   f"{'Cost':>13} {'Profit':>13}\n", "bold")
            o.emit("-" * (w + 70) + "\n", "muted")
            for f in flips:
                name = f["name"][:w]
                o.emit_link(name, wowhead_url(f["id"], game))
                o.emit(" " * (w - len(name)))
                o.emit(f" {wp.fmt_gold(f['lowest']):>11} {wp.fmt_gold(f['typical']):>11}"
                       f" {f['discount']:>4.0f}% {f['units']:>11,} {wp.fmt_gold(f['cost']):>13} ")
                o.emit(f"{wp.fmt_gold(f['profit']):>13}\n", "up")
            o.emit("\nProfit = buying every cheap unit and relisting at the usual price, after the 5% AH cut.\n"
                   "Check the Sell helper before buying a lot - a big batch can be slow to resell.\n", "muted")
        else:
            o.emit("No flips right now - nothing is listed far enough below its usual price.\n")
        if r["skipped"]:
            o.emit(f"\nNot enough history yet ({len(r['skipped'])}): " + ", ".join(r["skipped"][:12])
                   + (" ..." if len(r["skipped"]) > 12 else "") +
                   "\nItems need about half a day of hourly prices before they can be judged.", "muted")
        o.end()


# ---------------------------------------------------------------- guild crafters

class GuildWindow(ToolWindow):
    """Who in the guild can craft what: every member's professions and known recipes."""

    def __init__(self, app, slug, name):
        super().__init__(app, f"Guild crafters - {name}", "980x600")
        self.slug, self.name, self.guild, self.busy = slug, name, None, False
        top = ttk.Frame(self, padding=(12, 12, 12, 6))
        top.pack(fill="x")
        ttk.Label(top, text="Recipe or item").pack(side="left")
        self.q = ttk.Entry(top, width=26, font=M(11))
        self.q.pack(side="left", padx=(6, 6))
        self.q.bind("<Return>", lambda e: self.show())
        ttk.Button(top, text="Find", command=self.show).pack(side="left")
        ttk.Button(top, text="All professions", command=lambda: (set_entry(self.q, ""), self.show())).pack(
            side="left", padx=6)
        self.btn = ttk.Button(top, text="Refresh from Blizzard", command=lambda: self.load(True))
        self.btn.pack(side="right")
        self.status = ttk.Label(self, foreground=MUTED, font=M(10), padding=(12, 0, 12, 6))
        self.status.pack(fill="x")
        self.table = DataTable(self, [(f"c{i}", "", w, a) for i, (w, a) in
                                      enumerate([(260, "w"), (190, "w"), (150, "w"), (110, "e"), (70, "e")], 1)],
                               height=16)
        self.table.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.load()

    def load(self, force=False):
        if self.busy:
            return
        cached = wpg.guild_cached(self.slug)
        if cached and not force:
            self.guild = cached
            self.show()
            if time.time() - cached.get("fetched", 0) < wpg.GUILD_SECONDS:
                return
        if not wp.has_credentials():
            self.status.config(text="Add your Blizzard API key first (restart the app to enter it).")
            return
        self.busy = True
        self.btn.config(state="disabled")
        self.status.config(text=f"Reading the roster of {self.name} from Blizzard...")

        def progress(i, n):
            self.app.results.put((lambda _r, i=i, n=n: self.status.config(
                text=f"Reading members' professions: {i:,} of {n:,}..."), None))

        def done(res):
            guild, err = res
            self.busy = False
            self.btn.config(state="normal")
            if guild is None:
                self.status.config(text=(err or "Couldn't read the guild.").strip().replace("\n", " ")[:220])
                return
            self.guild = guild
            self.show()
        self.app.in_background(lambda: capture(lambda: wpg.guild_crafters(self.slug, progress, force=True)), done)

    def show(self):
        g = self.guild
        if g is None:
            return
        text = self.q.get().strip()
        tv = self.table.tree
        tv.delete(*tv.get_children())
        if text:
            heads = ["RECIPE", "CRAFTER", "PROFESSION", "SKILL", "LEVEL"]
            rows = [list(r) for r in wpg.find_crafters(g, text)[:600]]
        else:
            heads = ["PROFESSION", "MEMBER", "SKILL", "RECIPES KNOWN", "LEVEL"]
            rows = [[p, m, f"{s} / {c}" if c else s, n or "", lv] for p, m, s, c, n, lv in wpg.guild_professions(g)]
        for i, h in enumerate(heads, 1):
            tv.heading(f"c{i}", text=h)
        for n, r in enumerate(rows):
            tv.insert("", "end", iid=str(n), values=r)
        read = sum(1 for m in g["members"] if m.get("read"))
        self.status.config(text=(f"{len(rows)} match{'es' if len(rows) != 1 else ''} for \"{text}\"  ·  " if text else "")
                           + f"{g['name']}: {g.get('listed', len(g['members']))} members, professions read for {read}"
                           f"  ·  read {clock(g.get('fetched', 0), '%b %d, %I:%M %p')}"
                           "  ·  members under level 10 or not logged out yet can't be read")


# ---------------------------------------------------------------- saved-list editor base

class LibraryWindow(ToolWindow):
    """Left: saved list. Middle: editor. Right: results."""
    path = None
    noun = "item"

    def __init__(self, app, title):
        super().__init__(app, title, "1200x620")
        self.items = wp.load_json(self.path, [])
        self.current = None

        left = ttk.Frame(self, padding=(12, 12, 6, 12))
        left.pack(side="left", fill="y")
        ttk.Label(left, text=f"Saved {self.noun}s", font=F(10, "bold"), foreground=GOLD).pack(anchor="w")
        self.listbox = tk.Listbox(left, width=20, activestyle="none", font=F(10), exportselection=False)
        self.listbox.pack(fill="y", expand=True, pady=(4, 6))
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        ttk.Button(left, text=f"New {self.noun}", command=self.new).pack(fill="x")
        ttk.Button(left, text="Delete", command=self.delete).pack(fill="x", pady=(4, 0))

        self.editor = ttk.Frame(self, padding=(6, 12, 6, 12))
        self.editor.pack(side="left", fill="y")
        self.build_editor(self.editor)

        self.out = OutputText(self)
        self.out.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)
        self.refresh()
        self.new()

    def refresh(self):
        self.listbox.delete(0, "end")
        for it in self.items:
            self.listbox.insert("end", it["name"])

    def on_select(self, _e=None):
        sel = self.listbox.curselection()
        if sel:
            self.current = sel[0]
            self.fill(self.items[sel[0]])

    def new(self):
        self.current = None
        self.listbox.selection_clear(0, "end")
        self.fill(None)

    def delete(self):
        if self.current is None:
            return
        del self.items[self.current]
        wp.save_json(self.path, self.items)
        self.refresh()
        self.new()

    def save(self):
        try:
            data = self.collect()
        except ValueError as e:
            self.out.show(str(e))
            return None
        names = [i["name"].lower() for n, i in enumerate(self.items) if n != self.current]
        if data["name"].lower() in names:
            self.out.show(f'You already have a {self.noun} called "{data["name"]}".')
            return None
        if self.current is None:
            self.items.append(data)
            self.current = len(self.items) - 1
        else:
            self.items[self.current] = data
        wp.save_json(self.path, self.items)
        self.refresh()
        self.listbox.selection_set(self.current)
        return data


def labeled_text(parent, label, height, width=30):
    ttk.Label(parent, text=label).pack(anchor="w", pady=(8, 0))
    t = tk.Text(parent, width=width, height=height, font=M(11), wrap="none")
    t.pack(fill="x", pady=(2, 0))
    return t


def labeled_entry(parent, label, width=30):
    ttk.Label(parent, text=label).pack(anchor="w", pady=(8, 0))
    e = ttk.Entry(parent, width=width)
    e.pack(fill="x", pady=(2, 0))
    return e


def set_entry(e, value):
    e.delete(0, "end")
    e.insert(0, "" if value is None else str(value))


def set_text(t, value):
    t.delete("1.0", "end")
    t.insert("1.0", value or "")


# ---------------------------------------------------------------- crafting

class CraftingWindow(LibraryWindow):
    path = wp.RECIPES_PATH
    noun = "recipe"

    def __init__(self, app):
        super().__init__(app, "Crafting profit")
        if not self.items:
            self.out.show("Add a recipe in the middle, then click Save recipe.\n\n"
                          "Reagents go one per line, the same way as the fishing window:\n"
                          "    2 Raw Brilliant Smallfish\n"
                          "Things you buy from a vendor (not the AH) get a set price:\n"
                          "    1 Mild Spices @ 10c\n\n"
                          "Calculate all compares every saved recipe at today's prices.")

    def build_editor(self, f):
        ttk.Label(f, text="Recipe", font=F(10, "bold"), foreground=GOLD).pack(anchor="w")
        self.name = labeled_entry(f, "Name (anything you like):")
        self.makes = labeled_entry(f, "Crafted item (name or ID):")
        self.makes_qty = labeled_entry(f, "How many one craft makes:", 8)
        self.reagents = labeled_text(f, "Reagents, one per line:", 7)
        ttk.Label(f, text="e.g.  2 Raw Brilliant Smallfish\n"
                          "       1 Mild Spices @ 10c   (vendor)", foreground=MUTED).pack(anchor="w")
        ttk.Button(f, text="Save recipe", command=self.save).pack(fill="x", pady=(10, 0))
        self.btn = ttk.Button(f, text="Calculate all", command=self.calculate)
        self.btn.pack(fill="x", pady=(4, 0))

    def fill(self, r):
        set_entry(self.name, r and r["name"])
        set_entry(self.makes, r and r["makes"])
        set_entry(self.makes_qty, r["makes_qty"] if r else 1)
        set_text(self.reagents, r and r["reagents"])

    def collect(self):
        name, makes = self.name.get().strip(), self.makes.get().strip()
        q = self.makes_qty.get().strip() or "1"
        reagents = self.reagents.get("1.0", "end").strip()
        if not name or not makes or not reagents:
            raise ValueError("Fill in a name, the crafted item, and at least one reagent.")
        if not q.isdigit() or int(q) < 1:
            raise ValueError("How many one craft makes should be a whole number, like 1.")
        wp.parse_reagents(reagents)      # raises a readable error on a bad @ price
        return {"name": name, "makes": makes, "makes_qty": int(q), "reagents": reagents}

    def calculate(self):
        if self.name.get().strip() and self.save() is None:
            return
        if not self.items:
            self.out.show("Save a recipe first.")
            return
        recipes = list(self.items)
        self.btn.config(state="disabled")
        self.run(lambda api: wp.craft_profit(api, recipes), self.render,
                 f"Pricing {len(recipes)} recipe{'s' if len(recipes) != 1 else ''}...")

    def render(self, results, err, game):
        self.btn.config(state="normal")
        o = self.out
        if results is None:
            o.show(err or "Couldn't price recipes.")
            return
        o.begin()
        ok = sorted([r for r in results if r["ok"]], key=lambda r: -r["profit"])
        if ok:
            w = max(8, min(22, max(len(r["name"]) for r in ok)))
            o.emit(f"{'Recipe':<{w}} {'Mats cost':>11} {'Sells for':>11} {'Buy & craft':>12} {'vs sell raw':>12}\n", "bold")
            o.emit("-" * (w + 50) + "\n", "muted")
            for r in ok:
                o.emit(f"{r['name'][:w]:<{w}} {wp.fmt_gold(r['cost']):>11} {wp.fmt_gold(r['sell']):>11} ")
                o.emit(f"{('+' if r['profit'] >= 0 else '-') + wp.fmt_gold(abs(r['profit'])):>12}", pct_tag(r["profit"]))
                o.emit(f" {('+' if r['vs_raw'] >= 0 else '-') + wp.fmt_gold(abs(r['vs_raw'])):>12}\n", pct_tag(r["vs_raw"]))
            o.emit("\nBuy & craft = profit if you buy all mats on the AH,\n"
                   "  craft, and sell.\n"
                   "vs sell raw = extra you get by crafting mats you already\n"
                   "  have instead of selling them as-is.\n"
                   "Both include the 5% AH cut.\n", "muted")
        for r in results:
            o.emit(f"\n{r['name']}", "bold")
            if r.get("product"):
                o.emit("  makes ")
                o.emit_link(r["product"]["name"], wowhead_url(r["product"]["id"], game))
                if r["ok"]:
                    o.emit(f" x{r['makes']} @ {wp.fmt_gold(r['product_each'])} each")
            o.emit("\n")
            for p in r["parts"]:
                o.emit(f"   {p['qty']:>3} x ")
                if p.get("id"):
                    o.emit_link(p["name"], wowhead_url(p["id"], game))
                else:
                    o.emit(p["name"])
                o.emit(f"  @ {wp.fmt_gold(p['each'])}" + ("  (set price)" if p["how"] != "AH" else "") + "\n",
                       "muted")
            for e in r["errors"]:
                o.emit(f"   {e}\n", "down")
        o.end()


# ---------------------------------------------------------------- fishing spot planner

class SpotWindow(LibraryWindow):
    path = wp.SPOTS_PATH
    noun = "spot"

    def __init__(self, app):
        super().__init__(app, "Fishing spot planner")
        if not self.items:
            self.out.show("Add a fishing spot: how many fish you catch per hour there,\n"
                          "and what share of catches is each fish.\n\n"
                          "If you've saved fishing sessions with minutes, type the same spot\n"
                          "name and click Fill from my sessions - it works out both for you.\n\n"
                          "Rank all spots shows estimated gold per hour at today's prices.")

    def build_editor(self, f):
        ttk.Label(f, text="Fishing spot", font=F(10, "bold"), foreground=GOLD).pack(anchor="w")
        self.name = labeled_entry(f, "Spot name:")
        ttk.Button(f, text="Fill from my sessions", command=self.fill_sessions).pack(fill="x", pady=(6, 0))
        self.cph = labeled_entry(f, "Catches per hour:", 8)
        self.drops = labeled_text(f, "What it drops (share of catches):", 7)
        ttk.Label(f, text="e.g.  60% Raw Slitherskin Mackerel\n"
                          "       30% Raw Brilliant Smallfish\n"
                          "       10% Oily Blackmouth", foreground=MUTED).pack(anchor="w")
        ttk.Button(f, text="Save spot", command=self.save).pack(fill="x", pady=(10, 0))
        self.btn = ttk.Button(f, text="Rank all spots", command=self.calculate)
        self.btn.pack(fill="x", pady=(4, 0))

    def fill(self, sp):
        set_entry(self.name, sp and sp["name"])
        set_entry(self.cph, sp and sp.get("catches_per_hour"))
        set_text(self.drops, sp and sp.get("drops"))

    def collect(self):
        name = self.name.get().strip()
        drops = self.drops.get("1.0", "end").strip()
        if not name or not drops:
            raise ValueError("Fill in a spot name and what it drops.")
        try:
            cph = float(self.cph.get().strip())
            assert cph > 0
        except (ValueError, AssertionError):
            raise ValueError("Catches per hour should be a number, like 120.")
        wp.parse_drops(drops)
        return {"name": name, "catches_per_hour": cph, "drops": drops}

    def fill_sessions(self):
        name = self.name.get().strip()
        if not name:
            self.out.show("Type the spot name you used when saving fishing sessions first.")
            return
        sp = wp.spot_from_sessions(name)
        if not sp:
            self.out.show(f'No saved sessions with minutes at "{name}".\n\n'
                          "In the Fishing session window, fill in the spot and minutes fished,\n"
                          "then Save session.")
            return
        set_entry(self.cph, sp["catches_per_hour"])
        set_text(self.drops, sp["drops"])
        self.out.show(f"Filled from {sp['sessions']} session{'s' if sp['sessions'] != 1 else ''} "
                      f"({sp['minutes']:g} minutes) at {name}.\nClick Save spot to keep it.")

    def calculate(self):
        if self.name.get().strip() and self.save() is None:
            return
        if not self.items:
            self.out.show("Save a spot first.")
            return
        spots = list(self.items)
        self.btn.config(state="disabled")
        self.run(lambda api: wp.plan_spots(api, spots), self.render,
                 f"Pricing {len(spots)} spot{'s' if len(spots) != 1 else ''}...")

    def render(self, results, err, game):
        self.btn.config(state="normal")
        o = self.out
        if results is None:
            o.show(err or "Couldn't price spots.")
            return
        o.begin()
        ok = [r for r in results if r["ok"]]
        if ok:
            w = max(8, min(24, max(len(r["name"]) for r in ok)))
            o.emit(f"{'Spot':<{w}} {'Catches/hr':>10} {'Per catch':>11} {'Gold per hour':>14}\n", "bold")
            o.emit("-" * (w + 40) + "\n", "muted")
            for r in ok:
                o.emit(f"{r['name'][:w]:<{w}} {r['cph']:>10g} {wp.fmt_gold(r['per_catch']):>11} ")
                o.emit(f"{wp.fmt_gold(r['gph']):>14}\n", "gold", "bold")
            o.emit("\nGold per hour is after the 5% AH cut, at today's market prices.\n", "muted")
        for r in results:
            o.emit(f"\n{r['name']}\n", "bold")
            for p in r["parts"]:
                o.emit(f"   {p['share']:>5.1f}%  ")
                o.emit_link(p["name"], wowhead_url(p["id"], game))
                o.emit(f"  @ {wp.fmt_gold(p['each'])}\n" if p["listed"] else "  (not listed - counted as 0)\n",
                       "muted")
            if r.get("normalized"):
                o.emit("   Shares didn't add up to 100%, so they were scaled to fit.\n", "muted")
            for e in r["errors"]:
                o.emit(f"   {e}\n", "down")
        o.end()


# ---------------------------------------------------------------- professions hub

def signed_gold(v):
    if v is None:
        return "--"
    return ("+" if v >= 0 else "-") + wp.fmt_gold(abs(v))


class DataTable(ttk.Frame):
    """Themed, sortable table: click a heading to sort by it."""

    def __init__(self, master, columns, height=12):
        super().__init__(master)
        self.cols = columns                       # [(key, heading, width, anchor)]
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings",
                                 style="Data.Treeview", height=height, selectmode="browse")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        for key, head, width, anchor in columns:
            self.tree.heading(key, text=head, anchor=anchor, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=key == columns[0][0])
        self.tree.tag_configure("pos", foreground=UP)
        self.tree.tag_configure("neg", foreground=DOWN)
        self.tree.tag_configure("na", foreground=MUTED)
        self.sort_keys = {}
        self.on_sort = None

    def sort_by(self, key):
        if self.on_sort:
            self.on_sort(key)


class ProfessionsWindow(ToolWindow):
    SORTS = ["Profit", "Margin %", "Craft vs sell raw", "Most listed", "Name (A-Z)"]

    def __init__(self, app):
        super().__init__(app, "Professions", "1280x780")
        self.minsize(1040, 620)
        self.profs = []
        self.page = None
        self.rows = []
        self.recipe_cache = {}

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x")
        tk.Label(head, image=IMG["coin_big"], bg=BG).pack(side="left", padx=(12, 8), pady=6)
        tk.Label(head, text="PROFESSIONS", bg=BG, fg=GOLD, font=F(17, "bold")).pack(side="left")
        tk.Label(head, text="   recipes, profits and gathering at today's prices", bg=BG, fg=MUTED,
                 font=F(9)).pack(side="left", pady=(8, 0))
        Banner.trim(self).pack(fill="x", pady=(0, 6))

        body = ttk.Frame(self, padding=(10, 0, 10, 10))
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=210)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.ptree = ttk.Treeview(left, show="tree", selectmode="browse", style="Side.Treeview")
        self.ptree.pack(fill="both", expand=True)
        self.ptree.tag_configure("cat", foreground=GOLD_EDGE, font=F(9, "bold"))
        self.ptree.bind("<<TreeviewSelect>>", self.on_pick)
        ttk.Button(left, text="My own recipes", command=lambda: CraftingWindow(self.app)).pack(fill="x", pady=(6, 0))

        self.right = ttk.Frame(body)
        self.right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.welcome()
        self.load_professions()

    # ---------------------------------------------------------------- list
    def welcome(self, text=None):
        self.clear_page()
        self.out = OutputText(self.right)
        self.out.pack(fill="both", expand=True)
        self.out.show(text or "Pick a profession on the left.\n\n"
                      "Crafting professions list every recipe Blizzard publishes, priced at today's\n"
                      "auction-house prices: what the materials cost, what the item sells for, and\n"
                      "your profit after the 5% AH cut. Click a recipe for its shopping list.\n\n"
                      "Gathering professions show what their materials sell for right now, and\n"
                      "let you log a session to work out your gold per hour.")

    def clear_page(self):
        for w in self.right.winfo_children():
            w.destroy()

    def load_professions(self):
        game = self.app.game_key()
        self.ptree.insert("", "end", iid="loading", text="Loading...")

        def done(res):
            profs, _err = res
            self.ptree.delete(*self.ptree.get_children())
            self.from_api = bool(profs)
            if not profs:
                profs = [{"id": None, "name": n, "gathering": n in wp.GATHERING} for n in wp.DEFAULT_PROFESSIONS]
            self.profs = {p["name"]: p for p in profs}
            for group, gathering in (("CRAFTING", False), ("GATHERING", True)):
                gid = f"grp:{group}"
                self.ptree.insert("", "end", iid=gid, text=group, open=True, tags=("cat",))
                for p in profs:
                    if p["gathering"] == gathering:
                        self.ptree.insert(gid, "end", iid=f"p:{p['name']}", text=p["name"])

        self.app.in_background(lambda: capture(lambda: wp.get_professions(wp.connect(game))), done)

    def on_pick(self, _e=None):
        sel = self.ptree.selection()
        if not sel or not sel[0].startswith("p:"):
            return
        prof = self.profs[sel[0][2:]]
        if prof["gathering"]:
            self.gathering_page(prof)
        else:
            self.crafting_page(prof)

    def header(self, prof, subtitle):
        h = ttk.Frame(self.right)
        h.pack(fill="x", pady=(0, 6))
        ttk.Label(h, text=prof["name"].upper(), font=F(16, "bold"), foreground=GOLD).pack(side="left")
        ttk.Label(h, text="   " + subtitle, foreground=MUTED).pack(side="left", pady=(6, 0))
        has_guide = prof["name"] in wp.GUIDES or os.path.exists(os.path.join(wp.GUIDES_DIR, prof["name"] + ".json"))
        ttk.Button(h, text="Leveling guide" if has_guide else "Write a leveling guide",
                   command=lambda: GuideWindow(self.app, prof["name"])).pack(side="right", padx=(6, 0))
        return h

    def materials_button(self, parent, prof):
        def go():
            game = self.app.game_key()
            self.app.in_background(
                lambda: capture(lambda: wp.find_material_category(wp.connect(game), prof["name"])),
                lambda res: self.app.browse_materials(res[0]) if res[0] else
                self.app.set_status(f"no material category found for {prof['name']}"))
        ttk.Button(parent, text="Browse materials on AH", command=go).pack(side="right")

    # ---------------------------------------------------------------- crafting
    def crafting_page(self, prof):
        self.clear_page()
        self.prof = prof
        h = self.header(prof, "every recipe, priced at today's auction-house prices")
        self.materials_button(h, prof)

        ctl = ttk.Frame(self.right)
        ctl.pack(fill="x", pady=(0, 6))
        self.tier_box = ttk.Combobox(ctl, state="readonly", width=26)
        self.tier_box.bind("<<ComboboxSelected>>", lambda e: self.load_tier())
        self.name_label = ttk.Label(ctl, text="Name contains:")
        self.name_label.pack(side="left")
        self.name_box = ttk.Entry(ctl, width=16)
        self.name_box.pack(side="left", padx=(4, 12))
        self.name_box.bind("<KeyRelease>", lambda e: self.fill_table())
        self.only_profit = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl, text="Profitable only", variable=self.only_profit,
                        command=self.fill_table).pack(side="left", padx=(0, 12))
        self.only_listed = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctl, text="Sells on AH", variable=self.only_listed,
                        command=self.fill_table).pack(side="left", padx=(0, 12))
        ttk.Label(ctl, text="Sort:").pack(side="left")
        self.sort_box = ttk.Combobox(ctl, state="readonly", width=17, values=self.SORTS)
        self.sort_box.current(0)
        self.sort_box.pack(side="left", padx=4)
        self.sort_box.bind("<<ComboboxSelected>>", lambda e: self.fill_table())
        self.refresh_btn = ttk.Button(ctl, text="Refresh prices", command=self.load_tier)
        self.refresh_btn.pack(side="right")

        self.status = ttk.Label(self.right, foreground=MUTED, font=M(10))
        self.status.pack(fill="x")
        self.table = DataTable(self.right, [
            ("recipe", "RECIPE", 300, "w"), ("cat", "CATEGORY", 150, "w"),
            ("cost", "MATS COST", 120, "e"), ("sell", "SELLS FOR", 120, "e"),
            ("profit", "PROFIT", 120, "e"), ("margin", "MARGIN", 80, "e"), ("raw", "VS SELL RAW", 120, "e")],
            height=9)
        self.table.pack(fill="both", expand=True, pady=(4, 6))
        self.table.on_sort = self.sort_from_heading
        self.table.tree.bind("<<TreeviewSelect>>", lambda e: self.show_recipe())

        bottom = ttk.Frame(self.right)
        bottom.pack(fill="x")
        ttk.Label(bottom, text="Craft how many?").pack(side="left")
        self.count = ttk.Spinbox(bottom, from_=1, to=999, width=5, command=self.show_recipe)
        self.count.set(1)
        self.count.pack(side="left", padx=6)
        self.count.bind("<KeyRelease>", lambda e: self.show_recipe())
        ttk.Button(bottom, text="Watch this item", command=lambda: self.watch("item")).pack(side="right")
        ttk.Button(bottom, text="Watch its materials", command=lambda: self.watch("mats")).pack(side="right", padx=6)
        self.detail = OutputText(self.right, height=12)
        self.detail.pack(fill="x", pady=(6, 0))
        self.detail.show("Click a recipe to see its materials and a shopping list.")
        self.rows = []

        if prof["id"] is None:
            self.status.config(text="")
            self.detail.show("Blizzard doesn't publish profession recipes for this game version, so\n"
                             "they can't be loaded automatically.\n\n"
                             "Use 'My own recipes' (bottom left) to add the recipes you craft - they're\n"
                             "priced the same way.")
            return
        game = self.app.game_key()
        self.status.config(text="Loading skill tiers...")

        def done(res):
            tiers, err = res
            if not tiers:
                self.status.config(text="")
                self.detail.show(err or f"Blizzard didn't return any recipes for {prof['name']}.\n"
                                 "Use 'My own recipes' (bottom left) to add yours.")
                return
            self.tiers = tiers
            if len(tiers) > 1:
                ttk.Label(ctl, text="Tier:").pack(side="left", before=self.name_label)
                self.tier_box.pack(side="left", padx=(4, 12), before=self.name_label)
            self.tier_box.config(values=[t["name"] for t in tiers])
            self.tier_box.current(0)
            self.load_tier()

        self.app.in_background(lambda: capture(lambda: wp.profession_tiers(wp.connect(game), prof["id"])), done)

    def load_tier(self):
        tier = self.tiers[self.tier_box.current()]
        prof = self.prof
        game = self.app.game_key()
        self.refresh_btn.config(state="disabled")
        self.status.config(text=f"Loading {tier['name']} recipes... (the first time takes a minute; "
                                "after that they're remembered for a week)")

        def progress(i, n):
            if i % 5 == 0:
                self.app.results.put((lambda _r, i=i, n=n: self.status.config(
                    text=f"Downloading recipes from Blizzard: {i} of {n}..."), None))

        def work():
            api = wp.connect(game)
            recipes = wp.tier_recipes(api, prof["id"], tier["id"], progress)
            return wp.price_recipes(api, recipes or [])

        def done(res):
            result, err = res
            self.refresh_btn.config(state="normal")
            if result is None:
                self.status.config(text="")
                self.detail.show(err or "Couldn't load recipes.")
                return
            self.rows = result["rows"]
            self.ts = result["ts"]
            self.fill_table()

        self.app.in_background(lambda: capture(work), done)

    def sort_from_heading(self, key):
        mapping = {"profit": "Profit", "margin": "Margin %", "raw": "Craft vs sell raw", "recipe": "Name (A-Z)"}
        if key in mapping:
            self.sort_box.set(mapping[key])
            self.fill_table()

    def fill_table(self):
        if not hasattr(self, "table"):
            return
        t = self.table.tree
        t.delete(*t.get_children())
        text = self.name_box.get().strip().lower()
        rows = [r for r in self.rows
                if (not text or text in r["name"].lower() or text in (r["item_name"] or "").lower())
                and (not self.only_listed.get() or r["each"] is not None)
                and (not self.only_profit.get() or (r["profit"] or 0) > 0)]
        sort = self.sort_box.get()
        none_last = lambda v: (v is None, -(v or 0))
        if sort == "Profit":
            rows.sort(key=lambda r: none_last(r["profit"]))
        elif sort == "Margin %":
            rows.sort(key=lambda r: none_last(r["margin"]))
        elif sort == "Craft vs sell raw":
            rows.sort(key=lambda r: none_last(r["vs_raw"]))
        elif sort == "Most listed":
            rows.sort(key=lambda r: -r["listed"])
        else:
            rows.sort(key=lambda r: r["name"].lower())
        self.shown = {}
        for r in rows:
            tag = "na" if r["profit"] is None else "pos" if r["profit"] > 0 else "neg"
            iid = str(r["id"])
            self.shown[iid] = r
            t.insert("", "end", iid=iid, tags=(tag,), values=(
                r["name"], r["category"] or "", wp.fmt_gold(r["cost"]) if r["cost"] else "--",
                wp.fmt_gold(r["sell"]) if r["sell"] is not None else "--",
                signed_gold(r["profit"]), f"{r['margin']:+.0f}%" if r["margin"] is not None else "--",
                signed_gold(r["vs_raw"])))
        profitable = sum(1 for r in rows if (r["profit"] or 0) > 0)
        self.status.config(text=f"{len(rows)} of {len(self.rows)} recipes shown  ·  {profitable} profitable "
                                f"right now  ·  prices as of {clock(self.ts)}  ·  click a heading to sort")

    def current(self):
        sel = self.table.tree.selection() if hasattr(self, "table") else ()
        return self.shown.get(sel[0]) if sel else None

    def show_recipe(self):
        r = self.current()
        if not r:
            return
        try:
            n = max(1, int(self.count.get()))
        except ValueError:
            n = 1
        game = self.app.game_key()
        o = self.detail
        o.begin()
        o.emit(r["name"], "bold")
        o.emit("  makes ")
        o.emit_link(r["item_name"], wowhead_url(r["item_id"], game))
        makes = f"{r['makes']:g}"
        if r["each"] is not None:
            o.emit(f" x{makes}  @ {wp.fmt_gold(r['each'])} each  ({r['listed']:,} listed)\n")
        else:
            o.emit(f" x{makes}  (not listed on the AH right now)\n", "muted")
        o.emit(f"\nMaterials for {n} craft{'s' if n != 1 else ''}:\n", "bold")
        for p in r["parts"]:
            q = p["qty"] * n
            o.emit(f"  {q:>4} x ")
            o.emit_link(p["name"], wowhead_url(p["id"], game))
            if p["how"]:
                o.emit(f"  @ {wp.fmt_gold(p['each'])}" + ("  (vendor)" if p["how"] == "vendor" else "")
                       + f"  = {wp.fmt_gold(p['each'] * q)}\n", "muted")
            else:
                o.emit("  no price - not on the AH or at a vendor\n", "down")
        o.emit("\n")
        o.emit(f"Shopping list total: {wp.fmt_gold(r['cost'] * n)}", "bold")
        if r["sell"] is not None:
            o.emit(f"     Sells for: {wp.fmt_gold(r['sell'] * n)} after AH cut     Profit: ")
            o.emit(signed_gold(r["profit"] * n), "up" if r["profit"] > 0 else "down")
        o.end()

    def watch(self, what):
        r = self.current()
        if not r:
            self.app.set_status("pick a recipe first")
            return
        game = self.app.game_key()
        items = [(r["item_id"], r["item_name"])] if what == "item" else [(p["id"], p["name"]) for p in r["parts"]]
        for iid, name in items:
            info = wp.cached_info(game, iid)
            self.app.add_entry({"id": iid, "name": name, "cls": info.get("cls"), "sub": info.get("sub")})
        self.app.set_status(f"added {len(items)} item{'s' if len(items) != 1 else ''} to your watchlist")

    # ---------------------------------------------------------------- gathering
    def gathering_page(self, prof):
        self.clear_page()
        self.prof = prof
        name = prof["name"]
        h = self.header(prof, "what your materials are worth right now")
        self.materials_button(h, prof)

        btns = ttk.Frame(self.right)
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text=f"Log a {name.lower()} session", style="Big.TButton",
                   command=lambda: FishingWindow(self.app, name)).pack(side="left")
        ttk.Button(btns, text="Spot / route planner", style="Big.TButton",
                   command=lambda: SpotWindow(self.app)).pack(side="left", padx=8)
        ttk.Button(btns, text="Watch selected", command=self.watch_material).pack(side="right")

        self.status = ttk.Label(self.right, foreground=MUTED, font=M(10))
        self.status.pack(fill="x")
        self.mats = DataTable(self.right, [
            ("item", "MATERIAL", 320, "w"), ("lowest", "LOWEST", 130, "e"),
            ("market", "MARKET", 130, "e"), ("qty", "LISTED", 110, "e")], height=18)
        self.mats.pack(fill="both", expand=True, pady=(4, 0))
        self.mats.tree.bind("<Double-Button-1>", lambda e: self.watch_material())
        self.mat_rows = {}
        game = self.app.game_key()
        self.status.config(text="Loading material prices...")

        def done(res):
            result, err = res
            if not result:
                self.status.config(text=(err or f"Couldn't find {name} materials on the auction house.").splitlines()[-1])
                return
            cat = result["category"]
            self.status.config(text=f"{wp.category_label(cat[2], cat[3])}: {len(result['items'])} items for sale  "
                                    f"·  most listed first  ·  double-click to watch")
            t = self.mats.tree
            for e in result["items"][:200]:
                iid = str(e["id"])
                self.mat_rows[iid] = e
                t.insert("", "end", iid=iid, values=(e["name"], wp.fmt_gold(e["lowest"]),
                                                     wp.fmt_gold(e["cheap10"]), f"{e['quantity']:,}"))

        self.app.in_background(lambda: capture(lambda: wp.material_prices(wp.connect(game), name)), done)

    def watch_material(self):
        sel = self.mats.tree.selection() if hasattr(self, "mats") else ()
        if not sel:
            self.app.set_status("pick a material first")
            return
        self.app.add_entry(self.mat_rows[sel[0]])


# ---------------------------------------------------------------- character and gear upgrades

class CharacterTab(ttk.Frame):
    """Look up a character, then browse every piece of gear for sale for each slot - scored
    against what they wear, with upgrades highlighted."""

    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.char = None
        self.index = None
        self.rows = {}
        self.view_slot = None          # None = best upgrades across all slots
        self.current = {}
        self.drop_mode = False         # True = score what drops in dungeons instead of what's for sale
        self.drop_busy = False

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Name").pack(side="left")
        self.name = ttk.Entry(top, width=16, font=M(11))
        self.name.pack(side="left", padx=(4, 10))
        self.second_label = ttk.Label(top, text="Surname")
        self.second_label.pack(side="left")
        self.second = ttk.Entry(top, width=16, font=M(11))
        self.second.pack(side="left", padx=(4, 10))
        self.btn_look = ttk.Button(top, text="Look up", command=self.lookup)
        self.btn_look.pack(side="left")
        for e in (self.name, self.second):
            e.bind("<Return>", lambda ev: self.lookup())
        ttk.Label(top, text="Recent:").pack(side="left", padx=(16, 4))
        self.recent = ttk.Combobox(top, state="readonly", width=26)
        self.recent.pack(side="left")
        self.recent.bind("<<ComboboxSelected>>", self.pick_recent)
        ttk.Label(self, foreground=MUTED, font=M(10),
                  text="WoW: Forever characters are found by first name + surname. They show up once they're "
                       "level 10 and you've logged out.").pack(fill="x", pady=(4, 6))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=380)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.card = tk.Frame(left, bg=PANEL_2, highlightthickness=2, highlightbackground=BORDER, padx=12, pady=8)
        self.card.pack(fill="x")
        self.title = tk.Label(self.card, text="No character yet", bg=PANEL_2, fg=GOLD, font=F(14, "bold"), anchor="w")
        self.title.pack(fill="x")
        self.subtitle = tk.Label(self.card, text="Look one up above.", bg=PANEL_2, fg=MUTED, font=M(11),
                                 anchor="w", justify="left")
        self.subtitle.pack(fill="x")
        self.btn_rescan = ttk.Button(left, text="Rescan the auction house", command=lambda: self.build_index(True),
                                     state="disabled")
        self.btn_rescan.pack(side="bottom", fill="x", pady=(6, 0))
        self.gear = DataTable(left, [("slot", "SLOT", 90, "w"), ("item", "EQUIPPED", 210, "w"), ("ilvl", "ILVL", 50, "e")],
                              height=15)
        self.gear.pack(fill="both", expand=True, pady=(8, 0))
        for q, col in QUALITY_COLORS.items():
            self.gear.tree.tag_configure("q_" + q, foreground=col)
        self.gear.tree.tag_configure("empty", foreground=MUTED)
        self.gear.tree.bind("<<TreeviewSelect>>", lambda e: self.on_gear_select())

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        ctl = ttk.Frame(right)
        ctl.pack(fill="x")
        ttk.Label(ctl, text="Stat focus:").pack(side="left")
        self.focus = ttk.Combobox(ctl, state="readonly", width=20)
        self.focus.pack(side="left", padx=(4, 12))
        self.focus.bind("<<ComboboxSelected>>", lambda e: self.refresh_view())
        ttk.Label(ctl, text="Compare by:").pack(side="left")
        self.mode = ttk.Combobox(ctl, state="readonly", width=27, values=wp.COMPARE_MODES)
        self.mode.current(0)
        self.mode.pack(side="left", padx=(4, 12))
        self.mode.bind("<<ComboboxSelected>>", lambda e: self.refresh_view())
        ctl2 = ttk.Frame(right)
        ctl2.pack(fill="x", pady=(6, 0))
        ttk.Label(ctl2, text="Max price:").pack(side="left")
        self.max_price = ttk.Entry(ctl2, width=9)
        self.max_price.pack(side="left", padx=(4, 12))
        self.max_price.bind("<KeyRelease>", lambda e: self.after_idle(self.refresh_view))
        self.show_all_gear = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl2, text="Show gear I can't use", variable=self.show_all_gear,
                        command=self.refresh_view).pack(side="left", padx=(0, 12))
        self.only_upgrades = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl2, text="Upgrades only", variable=self.only_upgrades,
                        command=self.refresh_view).pack(side="left")
        self.btn_all = ttk.Button(ctl2, text="Best upgrades (all slots)", command=self.show_all, state="disabled")
        self.btn_all.pack(side="right")
        self.btn_drops = ttk.Button(ctl2, text="Upgrades from dungeons", command=self.show_drops, state="disabled")
        self.btn_drops.pack(side="right", padx=(0, 6))

        srow = ttk.Frame(right)
        srow.pack(fill="x", pady=(6, 4))
        self.sort = ttk.Combobox(srow, state="readonly", width=19,
                                 values=["Biggest upgrade", "Best value per gold", "Efficiency", "Cheapest", "Item level"])
        self.sort.current(0)
        self.sort.pack(side="right")
        self.sort.bind("<<ComboboxSelected>>", lambda e: self.refresh_view())
        ttk.Label(srow, text="Sort:").pack(side="right", padx=(0, 4))
        self.status = ttk.Label(srow, foreground=MUTED, font=M(10))
        self.status.pack(side="left", fill="x")

        self.table = DataTable(right, [("slot", "SLOT", 70, "w"), ("item", "ITEM FOR SALE", 190, "w"),
                                       ("ilvl", "ILVL", 40, "e"), ("power", "POWER", 54, "e"),
                                       ("fit", "FIT", 44, "e"), ("eff", "EFFICIENCY", 84, "e"),
                                       ("up", "VS YOURS", 74, "e"), ("price", "PRICE", 112, "e"),
                                       ("note", "NOTE", 150, "w")], height=9)
        self.table.pack(fill="both", expand=True)
        tv = self.table.tree
        for q, col in QUALITY_COLORS.items():
            tv.tag_configure("q_" + q, foreground=col)
        tv.tag_configure("better", background="#163a1c")
        tv.tag_configure("best", background="#3d3410")
        tv.tag_configure("nouse", foreground="#6f6250")
        tv.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        self.table.on_sort = self.sort_heading
        bb = ttk.Frame(right)
        bb.pack(fill="x", pady=(6, 0))
        ttk.Button(bb, text="What did the scan find?", command=self.show_scan_info).pack(side="left")
        ttk.Button(bb, text="Watch this item", command=self.watch).pack(side="right")
        ttk.Button(bb, text="Show on Search tab", command=self.show_on_search).pack(side="right", padx=6)
        self.detail = OutputText(right, height=9)
        self.detail.config(wrap="word")
        self.detail.pack(fill="x", pady=(6, 0))
        self.detail.show("Look up a character. The app then reads every piece of gear for sale on the auction "
                         "house (the first time takes a minute or two) - after that, click any slot on the left to "
                         "see everything for sale for it. Green rows are upgrades, gold rows are the best value.")
        self.on_game_change()
        self.refresh_recent()

    # ------------------------------------------------------------ helpers
    def forever(self):
        return self.app.game_key() == "forever"

    def on_game_change(self):
        self.second_label.config(text="Surname" if self.forever() else "Realm")
        self.index = None
        if self.drop_mode:
            self.drop_mode = False
            self.set_headings()

    def refresh_recent(self):
        game = self.app.game_key()
        self.recent_list = [c for c in wp.load_characters() if c.get("game") == game]
        self.recent.config(values=[f"{c['name']} {c.get('surname') or c.get('realm', '')}".strip()
                                   for c in self.recent_list])

    def pick_recent(self, _e=None):
        c = self.recent_list[self.recent.current()]
        set_entry(self.name, c["name"])
        set_entry(self.second, c.get("surname") or c.get("realm", ""))
        self.lookup()

    def weights(self):
        c = self.char or {}
        presets = wp.STAT_PRESETS.get(c.get("cls"), {})
        return presets.get(self.focus.get()) or next(iter(presets.values()), wp.DEFAULT_WEIGHTS)

    # ------------------------------------------------------------ lookup
    def lookup(self):
        name, second = self.name.get().strip(), self.second.get().strip()
        if not name or not second:
            self.status.config(text="Enter the character's first name and surname." if self.forever()
                               else "Enter the character's name and realm.")
            return
        game = self.app.game_key()
        self.btn_look.config(state="disabled")
        self.status.config(text=f"Looking up {name} {second}...")

        def work():
            api = wp.connect(game)
            try:
                return wp.get_character(api, name, second if game == "forever" else None,
                                        second if game != "forever" else None)
            except wp.ApiError as e:
                if e.code == 404:
                    raise SystemExit(f"Couldn't find {name} {second}. Check the spelling - "
                                     + ("Forever characters need first name AND surname, " if game == "forever" else "")
                                     + "must be level 10+, and appear after you log out.")
                raise

        def done(res):
            char, err = res
            self.btn_look.config(state="normal")
            if not char:
                self.status.config(text=(err or "Lookup failed.").splitlines()[-1])
                return
            self.char = char
            self.btn_drops.config(state="normal" if game == "forever" else "disabled")
            wp.remember_character({"name": char["name"], "surname": char.get("surname", ""),
                                   "realm": char.get("realm", "") if game != "forever" else "", "game": game})
            self.refresh_recent()
            self.show_character()
            self.build_index()

        self.app.in_background(lambda: capture(work), done)

    def show_character(self):
        c = self.char
        full = f"{c['name']} {c['surname']}".strip()
        self.title.config(text=full)
        bits = [f"Level {c['level']} {c['race']} {c['cls']}".replace("  ", " ")]
        if c.get("ruleset"):
            bits.append(f"{c['ruleset']} ruleset")
        if c.get("realm"):
            bits.append(c["realm"])
        if c.get("ilvl"):
            bits.append(f"item level {c['ilvl']}")
        self.subtitle.config(text="\n".join(bits))
        t = self.gear.tree
        t.delete(*t.get_children())
        equipped = {g["slot"]: g for g in c["gear"]}
        for slot, label in wp.SLOT_NAMES.items():
            g = equipped.get(slot)
            if g:
                t.insert("", "end", iid=slot, values=(label, g["name"] or "?", g["ilvl"] or ""),
                         tags=("q_" + (g["q"] or ""),))
            else:
                t.insert("", "end", iid=slot, values=(label, "— empty —", ""), tags=("empty",))
        presets = list(wp.STAT_PRESETS.get(c["cls"], {}) or ["Balanced"])
        self.focus.config(values=presets)
        self.focus.current(0)
        self.view_slot = None
        self.table.tree.delete(*self.table.tree.get_children())

    # ------------------------------------------------------------ auction-house gear index
    def build_index(self, force=False):
        if not self.char:
            return
        if force:
            for f in ("forever_all_houses_v5", "commodities"):
                path = os.path.join(wp.CACHE_DIR, f"{self.app.game_key()}_us_{f}.json")
                if os.path.exists(path):
                    os.remove(path)
        game = self.app.game_key()
        self.btn_rescan.config(state="disabled")
        self.status.config(text="Reading the gear for sale on the auction house...")

        def progress(i, n):
            self.app.results.put((lambda _r, i=i, n=n: self.status.config(
                text=f"Identifying gear for sale: {i:,} of {n:,} (only needed once per item)..."), None))

        def done(res):
            index, err = res
            self.btn_rescan.config(state="normal")
            if index is None:
                self.status.config(text=(err or "Couldn't read the auction house.").splitlines()[-1])
                return
            self.index = index
            self.btn_all.config(state="normal")
            self.refresh_view()

        self.app.in_background(lambda: capture(lambda: wp.gear_index(wp.connect(game), progress)), done)

    # ------------------------------------------------------------ views
    def selected_slot(self):
        sel = self.gear.tree.selection()
        return sel[0] if sel else None

    def on_gear_select(self):
        slot = self.selected_slot()
        if not slot or not self.char:
            return
        self.view_slot = slot if slot in wp.SLOT_SEARCH else None
        self.show_equipped(slot)
        self.refresh_view(keep_detail=True)

    def set_headings(self):
        tv, d = self.table.tree, self.drop_mode
        tv.heading("item", text="ITEM THAT DROPS" if d else "ITEM FOR SALE")
        tv.heading("price", text="ON THE AH" if d else "PRICE")
        tv.heading("note", text="DROPPED BY" if d else "NOTE")
        tv.column("note", width=280 if d else 150)

    def show_drops(self):
        """Switch the table to gear that drops in dungeons and raids, scored like the AH gear."""
        if not self.char:
            return
        mt = self.app.monster_tab
        if mt.db is None:
            if not mt.loading and not mt.declined:
                mt.load()
            if mt.db is None:
                self.status.config(text="Dungeon drops need the monster data. " +
                                   ("It's loading - click again in a moment." if mt.loading else
                                    "Open the Monster Compendium tab and click Update data first."))
                return
        self.drop_mode, self.view_slot = True, None
        self.gear.tree.selection_remove(*self.gear.tree.selection())
        self.set_headings()
        todo = wl.not_asked(wl.dungeon_gear(mt.db))
        if todo and not self.drop_busy and wp.has_credentials():
            self.drop_busy = True

            def progress(i, n):
                self.app.results.put((lambda _r, i=i, n=n: self.status.config(
                    text=f"Identifying dungeon gear: {i:,} of {n:,} (only needed once per item)..."), None))

            def done(_res):
                self.drop_busy = False
                if self.drop_mode:
                    self.refresh_view()
            self.app.in_background(
                lambda: capture(lambda: wp.fetch_items(wp.connect("forever"), todo, progress)), done)
        self.refresh_view()

    def refresh_drops(self, keep_detail=False):
        mt = self.app.monster_tab
        if not self.char or mt.db is None:
            return
        sources = self.index["sources"] if self.index else mt.sources
        rows, counts = wl.drop_rows(self.char, mt.db, self.weights(), self.mode.get(), self.view_slot, sources)
        self.current = {}
        if self.view_slot:
            if not self.show_all_gear.get():
                rows = [r for r in rows if r["usable"]]
            if self.only_upgrades.get():
                rows = [r for r in rows if r["better"]]
        else:
            rows = wl.best_per_slot(rows)
        keyf = {"Efficiency": lambda r: (not r["usable"], -r["eff"]),
                "Item level": lambda r: (not r["usable"], -(r["ilvl"] or 0))}.get(
                    self.sort.get(), lambda r: (not r["usable"], -r["gain"]))
        rows.sort(key=keyf)
        rows = rows[:400]
        t = self.table.tree
        t.delete(*t.get_children())
        self.rows = {}
        for n, r in enumerate(rows):
            iid = f"{r['slot']}:{r['id']}:{n}"
            self.rows[iid] = r
            tags = ("nouse",) if not r["usable"] else ("q_" + (r["q"] or ""),) + (("better",) if r["better"] else ())
            note = (r["why"] + "  ·  " if not r["usable"] else "") + wl.source_text(r)
            up = ("new" if r["up_pct"] is None else f"{r['up_pct']:+.0f}%") if r["better"] else \
                (f"{r['up_pct']:+.0f}%" if r["up_pct"] is not None else "--")
            t.insert("", "end", iid=iid, tags=tags, values=(
                r["slot_name"], r["name"], r["ilvl"] or "", f"{r['power']:.1f}",
                f"{r['fit'] * 100:.0f}%" if r["fit"] is not None else "--",
                ("~" if r["est"] else "") + f"{r['eff']:.1f}", up,
                wp.fmt_gold(r["price"]) if r["price"] else "not sold", note))
        n_up = sum(1 for r in rows if r["better"])
        where = wp.SLOT_NAMES[self.view_slot] if self.view_slot else "All slots (best 4 each)"
        gaps = f"  ·  {counts['missing']:,} of {counts['total']:,} dungeon items can't be scored (Blizzard has no data)"
        if counts["unknown"]:
            gaps = f"  ·  {counts['unknown']:,} items still being identified"
        self.status.config(text=f"{where}: {len(rows)} dungeon drop{'s' if len(rows) != 1 else ''}  ·  "
                                f"{n_up} upgrade{'s' if n_up != 1 else ''}{gaps}")
        if not keep_detail:
            self.detail.show(
                "Upgrades from dungeons\n\nGear that only drops inside dungeons and raids, scored against what "
                "you wear the same way as auction-house gear. Click a slot on the left for everything that "
                "drops for it, or a row for the stat comparison and who drops it. \"Best upgrades (all slots)\" "
                "goes back to gear for sale.\n\nOnly gear you can equip at your level is counted as an upgrade. "
                "Drop chances aren't known, and Blizzard has no stats for many Classic-era items, so some drops "
                "are missing from this list.")

    def show_all(self):
        self.view_slot = None
        if self.drop_mode:
            self.drop_mode = False
            self.set_headings()
        self.gear.tree.selection_remove(*self.gear.tree.selection())
        self.refresh_view()

    def sort_heading(self, key):
        mapping = {"up": "Biggest upgrade", "eff": "Efficiency", "price": "Cheapest", "ilvl": "Item level"}
        if key in mapping:
            self.sort.set(mapping[key])
            self.refresh_view(keep_detail=True)

    def refresh_view(self, keep_detail=False):
        if self.drop_mode:
            return self.refresh_drops(keep_detail)
        if not self.char or not self.index:
            return
        mode, weights = self.mode.get(), self.weights()
        try:
            max_price = wp.parse_gold(self.max_price.get())
        except ValueError:
            max_price = None
        if self.view_slot:
            rows, cur = wp.slot_view(self.char, self.view_slot, self.index, weights, mode)
            self.current = {self.view_slot: cur}
            if not self.show_all_gear.get():
                rows = [r for r in rows if r["usable"]]
        else:
            rows, self.current = wp.best_upgrades(self.char, self.index, weights, mode)
        if max_price:
            rows = [r for r in rows if r["price"] <= max_price]
        if self.only_upgrades.get():
            rows = [r for r in rows if r["better"]]
        how = self.sort.get()
        keyf = {"Best value per gold": lambda r: (not r["usable"], -r["per_gold"]),
                "Efficiency": lambda r: (not r["usable"], -r["eff"]),
                "Cheapest": lambda r: (not r["usable"], r["price"]),
                "Item level": lambda r: (not r["usable"], -(r["ilvl"] or 0))}.get(how, lambda r: (not r["usable"], -r["gain"]))
        rows.sort(key=keyf)
        t = self.table.tree
        t.delete(*t.get_children())
        self.rows = {}
        for n, r in enumerate(rows):
            iid = f"{r['slot']}:{r['id']}:{n}"
            self.rows[iid] = r
            if not r["usable"]:
                note, tags = r["why"], ("nouse",)
            else:
                note = "★ best value" if r.get("best_value") else "▲ biggest" if r.get("biggest") \
                    else "upgrade" if r["better"] else ""
                tags = ("q_" + (r["q"] or ""),) + (("best",) if r.get("best_value") else ("better",) if r["better"] else ())
            if r.get("est"):
                note = (note + "  ~est" if note else "~ estimated stats")
            up = ("new" if r["up_pct"] is None else f"{r['up_pct']:+.0f}%") if r["better"] else \
                (f"{r['up_pct']:+.0f}%" if r["up_pct"] is not None else "--")
            t.insert("", "end", iid=iid, tags=tags, values=(
                r["slot_name"], r["name"], r["ilvl"] or "", f"{r['power']:.1f}",
                f"{r['fit'] * 100:.0f}%" if r["fit"] is not None else "--",
                ("~" if r["est"] else "") + f"{r['eff']:.1f}", up, wp.fmt_gold(r["price"]), note))
        n_up = sum(1 for r in rows if r["better"])
        where = wp.SLOT_NAMES[self.view_slot] if self.view_slot else "All slots (best 3 each)"
        self.status.config(text=f"{where}: {len(rows)} for sale  ·  {n_up} upgrade{'s' if n_up != 1 else ''}"
                                f"  ·  prices {clock(self.index['ts'])}")
        if not rows and not keep_detail:
            self.show_scan_info()

    def show_equipped(self, slot):
        g = next((x for x in self.char["gear"] if x["slot"] == slot), None)
        o = self.detail
        o.begin()
        o.emit(f"{wp.SLOT_NAMES.get(slot, slot)}: ", "bold")
        if not g:
            o.emit("empty - anything usable here is an upgrade.\n", "muted")
        else:
            o.emit_link(g["name"] or "?", wowhead_url(g["id"], self.app.game_key()))
            e = wp.efficiency(g, self.weights(), slot, self.mode.get())
            o.emit(f"   item level {g['ilvl']}   Efficiency {e['eff']:.1f}\n")
            bits = [f"{v:g} {k.title()}" for k, v in g["stats"].items()]
            if g.get("armor"):
                bits.append(f"{g['armor']:g} Armor")
            if g.get("dps"):
                bits.append(f"{g['dps']:.1f} DPS")
            o.emit(("  " + "   ".join(bits) if bits else "  (no stats reported)") + "\n", "muted")
        if not self.index:
            o.emit("\nStill reading the auction house - the list will fill in when it's done.", "muted")
        o.end()

    def show_scan_info(self):
        o = self.detail
        o.begin()
        ix = self.index
        if not ix:
            o.emit("The auction house hasn't been read yet.", "muted")
            o.end()
            return
        o.emit("What the scan found\n", "bold")
        o.emit(f"  Gear listings on the auction house:   {ix['listed']:,}\n")
        o.emit(f"  Identified (slot, level, stats):      {len(ix['items']):,}\n")
        o.emit(f"  Blizzard has no data for:             {ix['missing']:,}\n", "muted")
        o.emit(f"  Not wearable gear:                    {ix['other']:,}\n", "muted")
        if self.view_slot:
            rows, _c = wp.slot_view(self.char, self.view_slot, ix, self.weights(), self.mode.get())
            usable = sum(1 for r in rows if r["usable"])
            o.emit(f"\n  {wp.SLOT_NAMES[self.view_slot]}: {len(rows):,} for sale, {usable:,} you can use, "
                   f"{sum(1 for r in rows if r['better']):,} upgrades\n")
            if rows and not usable:
                reasons = {}
                for r in rows:
                    reasons[r["why"]] = reasons.get(r["why"], 0) + 1
                o.emit("  Why the rest don't fit: " + ", ".join(f"{k} ({v})" for k, v in
                                                              sorted(reasons.items(), key=lambda kv: -kv[1])[:4]), "muted")
        if not ix["listed"]:
            o.emit("\nNo gear listings came back from Blizzard - send me a screenshot of this.", "down")
        o.end()

    def current_row(self):
        sel = self.table.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def show_detail(self):
        r = self.current_row()
        if not r:
            return
        cur_item = next((x for x in self.char["gear"] if x["slot"] == r["slot"]), None)
        c = self.current.get(r["slot"]) or wp.efficiency(cur_item, self.weights(), r["slot"], self.mode.get())
        game = self.app.game_key()
        o = self.detail
        o.begin()
        o.emit(f"{r['slot_name']}: ", "bold")
        o.emit_link(r["name"], wowhead_url(r["id"], game))
        o.emit(f"   item level {r['ilvl']}" + (f", requires {r['req']}" if r.get("req") else "")
               + (f"   for {wp.fmt_gold(r['price'])} ({r['listed']:,} listed)\n" if r["price"] else
                  "   not on the auction house\n"))
        for zone, names in (r.get("from") or {}).items():
            o.emit("Drops from: ", "gold")
            o.emit(", ".join(names[:6]) + (" ..." if len(names) > 6 else "") + (f"  ·  {zone}" if zone else "") + "   ")
        if r.get("npcs"):
            dt = self.app.dungeon_tab
            o.emit_action("Open in Dungeons tab", lambda: (self.app.tabs.select(dt), dt.goto(r["npcs"][0])))
            o.emit("\n")
        if not r["usable"]:
            o.emit(f"You can't use this: {r['why']}.\n", "down")
        cf = f"{c['fit'] * 100:.0f}%" if c.get("fit") is not None else "--"
        nf = f"{r['fit'] * 100:.0f}%" if r.get("fit") is not None else "--"
        o.emit(f"Power {c.get('power', 0):.1f} -> {r['power']:.1f}   Fit {cf} -> {nf}   ", "bold")
        o.emit(f"Efficiency {c.get('eff', 0):.1f} -> {r['eff']:.1f}", "gold", "bold")
        if r["better"]:
            o.emit(f"  ({r['up_pct']:+.0f}%)\n" if r["up_pct"] is not None else "  (fills an empty slot)\n", "up")
        else:
            o.emit("  (not an upgrade)\n", "muted")
        new, old = r["gear"], cur_item or {"stats": {}, "armor": 0, "dps": 0}
        rows = [(k.title(), old["stats"].get(k, 0), new["stats"].get(k, 0))
                for k in sorted(set(new["stats"]) | set(old["stats"]))]
        if new.get("armor") or old.get("armor"):
            rows.append(("Armor", old.get("armor") or 0, new.get("armor") or 0))
        if new.get("dps") or old.get("dps"):
            rows.append(("Weapon DPS", round(old.get("dps") or 0, 1), round(new.get("dps") or 0, 1)))
        if rows:
            o.emit(f"  {'':<12}{'NOW':>8}{'NEW':>8}{'CHANGE':>9}\n", "muted")
            for label, a, b in rows:
                d = b - a
                o.emit(f"  {label:<12}{a:>8g}{b:>8g}")
                o.emit(f"{d:>+9g}\n", "up" if d > 0 else "down" if d < 0 else "muted")
        if r.get("est"):
            o.emit("~ Blizzard didn't send this item's stats, so its Fit is estimated at 50%.\n", "muted")
        o.emit("Power = stat points from item level, quality and slot.  Fit = share of those stats your focus "
               "uses.  Efficiency = Power x Fit, plus weapon DPS and armor.", "muted")
        o.end()

    def watch(self):
        r = self.current_row()
        if r:
            info = wp.cached_info(self.app.game_key(), r["id"])
            self.app.add_entry({"id": r["id"], "name": r["name"], "cls": info.get("cls"), "sub": info.get("sub")})

    def show_on_search(self):
        r = self.current_row()
        if r:
            self.app.tabs.select(0)
            set_entry(self.app.item, r["name"])
            self.app.lookup(str(r["id"]), by_id=True)

# ---------------------------------------------------------------- monster compendium

RANK_COLORS = {"Elite": GOLD, "Rare Elite": "#e6cc80", "Rare": "#d9d9e3", "Boss": "#ff8000"}
PRICE_TTL = 55 * 60


def prices_status(ts):
    """'AH prices from 3:05 PM', plus a warning when some auction houses didn't answer."""
    note = wp.snapshot_note()
    return f"AH prices from {clock(ts)}" + (f"  ·  {note}" if note else "")


def wiki_url(name):
    return wm.WIKI_PAGE.format(urllib.parse.quote(name.replace(" ", "_")))


class MonsterTab(ttk.Frame):
    """Monster Compendium: every monster in each region, what it drops (priced on the AH),
    the quests that need it or its drops, and a tracking list with kill counters."""

    TITLE = "Monster Compendium"
    SIDE_LABEL = "Regions"
    WIKI_CHOICES = ["Wowhead (Forever)", "Warcraft Wiki"]
    FACTIONS = ["Both factions", "Alliance", "Horde"]

    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.db = None
        self.loading = False
        self.view = None                     # ("zone", id) / ("tracked",) / ("search", text, mode)
        self.monsters = []                   # ids in the table, in display order
        self.sort_key, self.sort_rev = None, False
        self.sources, self.sources_ts, self.pricing = None, 0, False
        self.cur = None                      # selected monster id
        self.cur_drops = []
        self.tracked = wm.load_tracking()
        self.declined = False
        self.listeners = []                  # called with an error text (or None) after each load

        # --- top bar: search, link choice, data status
        self.top = top = ttk.Frame(self)
        top.pack(fill="x")
        self.q = ttk.Entry(top, width=26, font=M(11))
        self.q.pack(side="left")
        self.q.bind("<Return>", lambda e: self.search())
        self.qmode = ttk.Combobox(top, state="readonly", width=15, values=["Monster name", "Drops this item"])
        self.qmode.current(0)
        self.qmode.pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Find", command=self.search).pack(side="left", padx=6)
        ttk.Label(top, text="Name links open:").pack(side="left", padx=(12, 4))
        self.wiki = ttk.Combobox(top, state="readonly", width=18, values=self.WIKI_CHOICES)
        self.wiki.current(0)
        self.wiki.pack(side="left")
        self.btn_update = ttk.Button(top, text="Update data", command=lambda: self.load(update=True))
        self.btn_update.pack(side="right")
        self.data_label = ttk.Label(top, foreground=MUTED, font=M(10))
        self.data_label.pack(side="right", padx=8)

        flt = ttk.Frame(self)
        flt.pack(fill="x", pady=(6, 6))
        ttk.Label(flt, text="Level").pack(side="left")
        self.lmin = ttk.Entry(flt, width=4)
        self.lmin.pack(side="left", padx=(4, 0))
        ttk.Label(flt, text="-").pack(side="left", padx=2)
        self.lmax = ttk.Entry(flt, width=4)
        self.lmax.pack(side="left")
        for e in (self.lmin, self.lmax):
            e.bind("<KeyRelease>", lambda ev: self.after_idle(self.fill_monsters))
        self.special = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="Rares, elites and bosses only", variable=self.special,
                        command=self.fill_monsters).pack(side="left", padx=(12, 0))
        self.with_drops = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="Has drops", variable=self.with_drops,
                        command=self.fill_monsters).pack(side="left", padx=(12, 0))
        ttk.Label(flt, text="Quests for:").pack(side="left", padx=(16, 4))
        self.faction = ttk.Combobox(flt, state="readonly", width=13, values=self.FACTIONS)
        self.faction.current(0)
        self.faction.pack(side="left")
        self.faction.bind("<<ComboboxSelected>>", lambda e: (self.fill_monsters(), self.show_detail()))
        self.status = ttk.Label(flt, foreground=MUTED, font=M(10))
        self.status.pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # --- left: regions and the tracking list
        left = ttk.Frame(body, width=250)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        ttk.Label(left, text=self.SIDE_LABEL, font=F(10, "bold"), foreground=GOLD).pack(anchor="w")
        rbox = ttk.Frame(left)
        rbox.pack(fill="both", expand=True)
        self.rtree = ttk.Treeview(rbox, show="tree", selectmode="browse", style="Side.Treeview")
        rsb = ttk.Scrollbar(rbox, orient="vertical", command=self.rtree.yview)
        self.rtree.configure(yscrollcommand=rsb.set)
        rsb.pack(side="right", fill="y")
        self.rtree.pack(side="left", fill="both", expand=True)
        self.rtree.tag_configure("group", foreground=GOLD_EDGE, font=F(9, "bold"))
        self.rtree.tag_configure("tracked", foreground=GOLD, font=F(10, "bold"))
        self.rtree.bind("<<TreeviewSelect>>", self.on_region)

        # --- right: monsters on top, drops + quests underneath
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        panes = tk.PanedWindow(right, orient="vertical", bg=BG, sashwidth=6, bd=0, sashrelief="flat")
        panes.pack(fill="both", expand=True)

        upper = ttk.Frame(panes)
        self.bar = bar = ttk.Frame(upper)
        bar.pack(side="bottom", fill="x", pady=(6, 4))
        self.table = DataTable(upper, [("name", "MONSTER", 200, "w"), ("trk", "TRACKED", 70, "center"),
                                       ("lvl", "LEVEL", 58, "e"), ("rank", "TYPE", 84, "w"),
                                       ("zone", "ZONE", 150, "w"), ("drops", "DROPS", 58, "e"),
                                       ("quests", "QUESTS", 64, "e"), ("kills", "KILLS", 56, "e"),
                                       ("best", "BEST DROP ON THE AH", 200, "w")], height=10)
        self.table.pack(fill="both", expand=True)
        tv = self.table.tree
        tv.tag_configure("plain", foreground=LINK)
        for rank, col in RANK_COLORS.items():
            tv.tag_configure("r_" + rank, foreground=col)
        tv.tag_configure("tracked", background="#2b2410")
        tv.bind("<<TreeviewSelect>>", lambda e: self.on_monster())
        tv.bind("<Double-Button-1>", self.on_double)
        tv.bind("<Motion>", self.on_motion)
        tv.bind("<Button-3>", self.on_right_click)
        self.table.on_sort = self.sort_by
        self.btn_track = ttk.Button(bar, text="Track", width=10, command=self.toggle_track)
        self.btn_track.pack(side="left")
        ttk.Button(bar, text="+1 kill", command=lambda: self.add_kill(1)).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="-1", width=4, command=lambda: self.add_kill(-1)).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Note...", command=self.edit_note).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Copy waypoint", command=self.copy_waypoint).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Warcraft Wiki", command=lambda: self.open_link("wiki")).pack(side="right")
        ttk.Button(bar, text="Wowhead", command=lambda: self.open_link("wowhead")).pack(side="right", padx=6)
        panes.add(upper, minsize=170, stretch="always")

        lower = ttk.Frame(panes)
        dleft = ttk.Frame(lower, width=590)
        dleft.pack(side="left", fill="both")
        dleft.pack_propagate(False)
        dbar = ttk.Frame(dleft)
        dbar.pack(side="bottom", fill="x", pady=(6, 0))
        self.drops = DataTable(dleft, [("item", "DROPS", 180, "w"), ("type", "TYPE", 90, "w"),
                                       ("chance", "CHANCE", 60, "e"), ("price", "AH LOWEST", 98, "e"),
                                       ("qty", "ON AH", 56, "e"), ("you", "FOR YOU", 72, "e")], height=8)
        self.drops.pack(fill="both", expand=True)
        dtv = self.drops.tree
        for q, col in QUALITY_COLORS.items():
            dtv.tag_configure("q_" + q, foreground=col)
        dtv.tag_configure("questitem", foreground="#ffd100")
        dtv.tag_configure("better", background="#163a1c")
        self.stats_tried, self.stats_busy = set(), False
        dtv.bind("<Double-Button-1>", lambda e: self.open_drop())
        self.drops.on_sort = self.sort_drops
        self.drop_sort = None
        ttk.Button(dbar, text="Watch this drop", command=self.watch_drop).pack(side="left")
        ttk.Button(dbar, text="Show on Search tab", command=self.drop_on_search).pack(side="left", padx=6)
        self.btn_prices = ttk.Button(dbar, text="Refresh AH prices", command=lambda: self.load_prices(True))
        self.btn_prices.pack(side="right")
        self.info = OutputText(lower)
        self.info.config(wrap="word")
        self.info.pack(side="left", fill="both", expand=True, padx=(10, 0))
        panes.add(lower, minsize=200, stretch="always")

        self.info.show("Monster Compendium\n\nPick a region on the left to list its monsters, or search above "
                       "by monster name or by an item they drop.")
        self.bind("<Map>", lambda e: self.on_show())

    # ------------------------------------------------------------ loading
    def on_show(self):
        if self.db is None and not self.loading and not self.declined:
            self.load()
        elif self.db is not None and time.time() - self.sources_ts > PRICE_TTL:
            self.load_prices()

    def post(self, fn, value=None):
        self.app.results.put((fn, value))

    def set_status(self, text):
        self.status.config(text=text)

    def load(self, update=False):
        if self.loading:
            return
        first = not os.path.exists(wm.INDEX_PATH)
        if (first or update) and not messagebox.askokcancel(
                "Monster Compendium",
                ("Check GitHub for newer monster data and download it if there is any?\n\n" if update else
                 "The Monster Compendium uses the community QuestieDB database for WoW: Forever "
                 "(the data behind the Questie addon).\n\n"
                 "It isn't included with this app, so it will now be downloaded from GitHub "
                 "(about 14 MB, one time) and saved on this computer.\n\n") +
                "QuestieDB's Forever data is still filling in, so some new Forever monsters, drops "
                "and quests may be missing.", parent=self):
            if self.db is None:
                self.declined = True
                self.info.show("Monster Compendium\n\nThe monster data hasn't been downloaded yet.\n"
                               "Click Update data (top right) when you're ready.")
            return
        self.loading = True
        self.btn_update.config(state="disabled")
        self.info.show("Loading monster data..." if not (first or update) else
                       "Downloading the QuestieDB data for WoW: Forever...\nThis takes a minute the first time.")

        def progress(msg):
            self.post(lambda _v: self.set_status(msg))

        def work():
            try:
                return wm.load(progress, update=update), None
            except Exception as e:          # network trouble, a changed release format...
                return None, str(e)

        def done(res):
            db, err = res
            self.loading = False
            self.btn_update.config(state="normal")
            if db is None:
                self.set_status("")
                self.info.show("Couldn't load the monster data.\n\n" + (err or "") +
                               "\n\nClick Update data to try again.")
                for fn in self.listeners:
                    fn(err or "")
                return
            self.db = db
            self.set_status("")
            self.fill_regions()
            self.update_data_label()
            if update:
                Toast(self.app.root, f"Monster data updated (QuestieDB {db.version})")
            self.load_prices()
            self.check_for_update()
            for fn in self.listeners:
                fn(None)

        threading.Thread(target=lambda: self.post(done, work()), daemon=True).start()

    def update_data_label(self, newer=None):
        db = self.db
        text = f"QuestieDB {db.version} · {len(db.npcs):,} monsters · {len(db.quests):,} quests"
        if newer:
            text += f"  ·  v{newer} available"
        self.data_label.config(text=text, foreground=GOLD if newer else MUTED)

    def check_for_update(self):
        _, built = wm.index_info()
        if built and time.time() - built < wm.CHECK_EVERY:
            return

        def done(newer):
            if newer and self.db:
                self.update_data_label(newer)
        threading.Thread(target=lambda: self.post(done, wm.newer_release()), daemon=True).start()

    def load_prices(self, force=False):
        if self.pricing or not wp.has_credentials():
            return
        if not force and self.sources is not None and time.time() - self.sources_ts < PRICE_TTL:
            return
        self.pricing = True
        self.btn_prices.config(state="disabled")
        self.set_status("Loading auction house prices...")

        def done(res):
            sources, err = res
            self.pricing = False
            self.btn_prices.config(state="normal")
            if sources is None:
                self.set_status("Couldn't load AH prices" + (f": {err.splitlines()[-1]}" if err else ""))
                return
            self.sources, self.sources_ts = sources, time.time()
            self.set_status(prices_status(self.sources_ts))
            self.fill_monsters(keep=True)
            self.show_detail()

        self.app.in_background(lambda: capture(lambda: wp.get_sources(wp.connect("forever"))), done)

    # ------------------------------------------------------------ regions
    def fill_regions(self):
        t = self.rtree
        t.delete(*t.get_children())
        t.insert("", "end", iid="tracked", text=self.tracked_label(), tags=("tracked",))
        for group, zones in self.db.regions():
            g = t.insert("", "end", iid="g:" + group, text=group, open=group in ("Forever: new areas",),
                         tags=("group",))
            for zid, name, count in zones:
                t.insert(g, "end", iid=f"z:{zid}", text=f"{name}  ({count})")
        self.info.show("Monster Compendium\n\nPick a region on the left to list its monsters, or search above "
                       "by monster name or by an item they drop.\n\n"
                       "Double-click a monster's name to open its wiki page (choose Wowhead or Warcraft Wiki "
                       "above). Click a monster to see its drops - priced on the auction house - and every "
                       "quest that needs it or its drops.\n\nTrack monsters you're farming: they're listed "
                       "under Tracked monsters with a kill counter and notes.\n\n"
                       "Data: QuestieDB (the Questie addon's community database). Drop chances are only "
                       "known for quest items; other drops are what players have recorded.")

    def tracked_label(self):
        return f"Tracked monsters ({len(self.tracked)})"

    def on_region(self, _e=None):
        sel = self.rtree.selection()
        if not sel or self.db is None:
            return
        iid = sel[0]
        if iid == "tracked":
            self.view = ("tracked",)
        elif iid.startswith("z:"):
            self.view = ("zone", int(iid[2:]))
        else:
            return
        self.fill_monsters()

    def search(self):
        if self.db is None:
            return
        text = self.q.get().strip()
        if not text:
            return
        mode = "drop" if self.qmode.current() == 1 else "name"
        self.view = ("search", text, mode)
        self.rtree.selection_remove(self.rtree.selection())
        self.fill_monsters()

    # ------------------------------------------------------------ monster table
    def tracked_entry(self, nid):
        return next((t for t in self.tracked if t.get("id") == nid), None)

    def view_ids(self):
        db, v = self.db, self.view
        if not v:
            return []
        if v[0] == "zone":
            return db.monsters_in(v[1])
        if v[0] == "tracked":
            return [t["id"] for t in self.tracked if t.get("id") in db.npcs]
        if v[2] == "drop":
            return db.find_by_drop(v[1])
        return db.search(v[1])

    def faction_ok(self, q):
        f = self.faction.current()
        return f == 0 or not q.get("fa") or q["fa"] == ("A" if f == 1 else "H")

    def quest_list(self, nid):
        return [t for t in self.db.quests_for(nid) if self.faction_ok(t[1])]

    def best_drop(self, nid):
        if self.sources is None:
            return None
        best = None
        for iid in self.db.drops.get(nid, []):
            s = wp.item_summary(self.sources, iid)
            if s and (best is None or s["lowest"] > best[1]["lowest"]):
                best = (iid, s)
        return best

    def row_values(self, nid):
        db = self.db
        n = db.npcs[nid]
        tr = self.tracked_entry(nid)
        zones = sorted(n["z"], key=lambda z: -n["z"][z])
        zone = db.zone_name(zones[0]) if zones else ""
        if len(zones) > 1:
            zone += f" +{len(zones) - 1}"
        best = self.best_drop(nid)
        best_txt = ""
        if best:
            best_txt = f"{db.items[best[0]]['n']}  {wp.fmt_gold(best[1]['lowest'])}"
        elif self.sources is not None and db.drops.get(nid):
            best_txt = "none listed"
        lvl = db.level_text(nid)
        return {"name": n["n"], "trk": "yes" if tr else "", "lvl": "?" if lvl == "0" else lvl,
                "rank": db.rank_text(nid), "zone": zone, "drops": len(db.drops.get(nid, [])),
                "quests": len(self.quest_list(nid)), "kills": tr.get("kills", 0) if tr else "",
                "best": best_txt, "_best": best[1]["lowest"] if best else -1, "_lvl": min(n["l"][0], 99)}

    def fill_monsters(self, keep=False):
        if self.db is None or not self.view:
            return
        try:
            lo = int(self.lmin.get()) if self.lmin.get().strip() else None
            hi = int(self.lmax.get()) if self.lmax.get().strip() else None
        except ValueError:
            lo = hi = None
        rows = []
        for nid in self.view_ids():
            n = self.db.npcs[nid]
            if lo is not None and (n["l"][1] or n["l"][0]) < lo:
                continue
            if hi is not None and n["l"][0] > hi:
                continue
            if self.special.get() and not n.get("r"):
                continue
            if self.with_drops.get() and not self.db.drops.get(nid):
                continue
            rows.append((nid, self.row_values(nid)))
        if self.sort_key:
            key = {"lvl": "_lvl", "best": "_best"}.get(self.sort_key, self.sort_key)

            def sort_val(r):
                v = r[1][key]
                if key in ("kills", "drops", "quests"):
                    return v if isinstance(v, int) else -1
                return v.lower() if isinstance(v, str) else v
            rows.sort(key=sort_val, reverse=self.sort_rev)
        tv = self.table.tree
        sel = self.cur if keep else None
        tv.delete(*tv.get_children())
        self.monsters = [nid for nid, _ in rows]
        for nid, v in rows:
            rank = v["rank"]
            tags = ["r_" + rank if rank else "plain"]
            if v["trk"]:
                tags.append("tracked")
            tv.insert("", "end", iid=str(nid), tags=tags,
                      values=[v[c[0]] for c in self.table.cols])
        v = self.view
        where = (self.db.zone_name(v[1]) if v[0] == "zone" else "Tracked monsters" if v[0] == "tracked"
                 else f'"{v[1]}"' + (" (drops)" if v[2] == "drop" else ""))
        if not keep:
            self.set_status(f"{len(rows)} monster{'s' if len(rows) != 1 else ''} · {where}")
        if sel and str(sel) in tv.get_children():
            tv.selection_set(str(sel))
            tv.see(str(sel))
        elif rows and not keep:
            tv.selection_set(str(rows[0][0]))
        elif not rows:
            self.cur = None
            self.drops.tree.delete(*self.drops.tree.get_children())
            self.info.show("No monsters here match your filters." if v[0] != "tracked" else
                           "No tracked monsters yet.\n\nSelect a monster and click Track to follow it "
                           "here, with a kill counter and notes.")

    def sort_by(self, key):
        if key == self.sort_key:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_key, self.sort_rev = key, key in ("drops", "quests", "kills", "best", "trk")
        self.fill_monsters(keep=True)

    def on_monster(self):
        sel = self.table.tree.selection()
        if not sel:
            return
        self.cur = int(sel[0])
        self.btn_track.config(text="Untrack" if self.tracked_entry(self.cur) else "Track")
        self.show_detail()

    def name_cell(self, event):
        tv = self.table.tree
        return tv.identify_region(event.x, event.y) == "cell" and tv.identify_column(event.x) == "#1"

    def on_motion(self, event):
        self.table.tree.config(cursor="hand2" if self.name_cell(event) else "")

    def on_double(self, event):
        row = self.table.tree.identify_row(event.y)
        if row:
            self.cur = int(row)
            self.open_link("wiki" if self.wiki.current() == 1 else "wowhead")
        return "break"

    def on_right_click(self, event):
        row = self.table.tree.identify_row(event.y)
        if not row:
            return
        self.table.tree.selection_set(row)
        self.cur = int(row)
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Open on Wowhead (Forever)", command=lambda: self.open_link("wowhead"))
        m.add_command(label="Open on Warcraft Wiki", command=lambda: self.open_link("wiki"))
        m.add_separator()
        m.add_command(label="Untrack" if self.tracked_entry(self.cur) else "Track",
                      command=self.toggle_track)
        self.extra_menu(m)
        m.tk_popup(event.x_root, event.y_root)

    def extra_menu(self, m):
        dt = getattr(self.app, "dungeon_tab", None)
        zid = dt.dungeon_of(self.cur) if dt else None
        if zid:
            nid = self.cur
            m.add_separator()
            m.add_command(label="Open in Dungeons tab",
                          command=lambda: (self.app.tabs.select(dt), dt.goto(nid, zid)))

    def goto(self, nid, zid=None):
        """Show a monster: open its zone in the side list and select its row."""
        if self.db is None or nid not in self.db.npcs:
            return
        zid = zid or self.db.main_zone(nid)
        iid = f"z:{zid}"
        if self.rtree.exists(iid):
            if self.rtree.parent(iid):
                self.rtree.item(self.rtree.parent(iid), open=True)
            self.rtree.selection_set(iid)
            self.rtree.see(iid)

        def pick():
            if self.view != ("zone", zid):
                self.view = ("zone", zid)
                self.fill_monsters()
            tv = self.table.tree
            if str(nid) in tv.get_children():
                tv.selection_set(str(nid))
                tv.see(str(nid))
        self.after(120, pick)                # after the side list's own selection event has run

    def spots(self, nid):
        """[(label, zone, x, y, note)]: where a monster is, or its dungeon's entrance."""
        out = [("Where: ", zone, x, y, f"  (busiest of {n} spawn points)" if n > 1 else "")
               for zone, x, y, n in self.db.where(nid)]
        dt = getattr(self.app, "dungeon_tab", None)
        zid = dt.dungeon_of(nid) if dt is not None and not out else None
        if zid:
            out = [(f"Entrance to {self.db.zone_name(zid)}: ", zone, x, y, f"  ({label})" if label else "")
                   for zone, x, y, label in wd.entrances(self.db, zid)[:3]]
        return out

    def copy_waypoint(self):
        if self.cur is None or self.db is None:
            messagebox.showinfo(self.TITLE, "Select a monster in the table first.", parent=self)
            return
        spots = self.spots(self.cur)
        if not spots:
            messagebox.showinfo(self.TITLE, "There's no map position for this monster in the data.", parent=self)
            return
        _l, zone, x, y, _n = spots[0]
        self.app.copy_way(wm.way(zone, x, y, self.db.npcs[self.cur]["n"]))

    def emit_quest_spot(self, o, qid):
        """One line under a quest: where its giver stands, with a waypoint link."""
        spot = self.db.quest_spot(qid)
        q = self.db.allq.get(qid)
        if spot and q:
            o.emit(f"    Starts at {spot[0]} {spot[1]:g}, {spot[2]:g}   ", "muted")
            o.emit_action("Copy waypoint", lambda: self.app.copy_way(wm.way(*spot, q[wpg.GIVER] or q[wpg.N])))
            o.emit("\n")

    def open_link(self, which):
        if self.cur is None or self.db is None:
            return
        name = self.db.npcs[self.cur]["n"]
        webbrowser.open_new_tab(wiki_url(name) if which == "wiki" else wm.WOWHEAD_NPC.format(self.cur))

    # ------------------------------------------------------------ detail: drops + quests
    def show_detail(self):
        if self.cur is None or self.db is None or self.cur not in self.db.npcs:
            return
        db, nid = self.db, self.cur
        n = db.npcs[nid]
        self.cur_drops = db.drops_of(nid)
        for d in self.cur_drops:
            s = wp.item_summary(self.sources, d["id"]) if self.sources is not None else None
            d["ah"], d["qty"] = (s["lowest"], s["quantity"]) if s else (None, 0)
        self.fill_drops()

        o = self.info
        o.begin()
        o.emit_link(n["n"], wm.WOWHEAD_NPC.format(nid), "gold", "bold")
        o.emit("\n")
        rank = db.rank_text(nid)
        lvl = db.level_text(nid)
        o.emit(f"Level {'?' if lvl == '0' else lvl}" + (f"  ·  {rank}" if rank else "") +
               (f"  ·  <{n['s']}>" if n.get("s") else "") + f"  ·  NPC {nid}\n", "muted")
        o.emit_link("Wowhead (Forever)", wm.WOWHEAD_NPC.format(nid))
        o.emit("   ")
        o.emit_link("Warcraft Wiki", wiki_url(n["n"]))
        o.emit("\n\n")
        zones = sorted(n["z"], key=lambda z: -n["z"][z])
        o.emit("Found in: ", "gold")
        o.emit(", ".join(db.zone_name(z) for z in zones[:8]) + (" ..." if len(zones) > 8 else "") + "\n")
        for label, zone, x, y, note in self.spots(nid):
            o.emit(label, "gold")
            o.emit(f"{zone}  {x:g}, {y:g}{note}   ")
            o.emit_action("Copy waypoint", lambda z=zone, x=x, y=y: self.app.copy_way(wm.way(z, x, y, n["n"])))
            o.emit("\n")
        tr = self.tracked_entry(nid)
        if tr:
            o.emit("Tracking: ", "gold")
            o.emit(f"{tr.get('kills', 0)} kills")
            if tr.get("note"):
                o.emit(f"  ·  {tr['note']}", "muted")
            o.emit("\n")
        if self.sources is not None and self.cur_drops:
            listed = [d for d in self.cur_drops if d["ah"]]
            if listed:
                best = max(listed, key=lambda d: d["ah"])
                o.emit("Most valuable drop on the AH: ", "gold")
                o.emit(f"{best['name']} at {wp.fmt_gold(best['ah'])}\n")

        quests = self.quest_list(nid)
        o.emit(f"\nQuests that need this monster or its drops ({len(quests)})\n", "gold", "bold")
        if not quests:
            o.emit("None known" + (" for this faction" if self.faction.current() else "") + ".\n", "muted")
        for qid, q, why in quests:
            lv = q.get("lv")
            o.emit(f"[{lv if lv and lv > 0 else '?'}] ", "muted")
            o.emit_link(q["n"], wm.WOWHEAD_QUEST.format(qid))
            fac = {"A": "  Alliance", "H": "  Horde"}.get(q.get("fa"), "")
            o.emit(fac + "\n", "muted")
            o.emit(f"    {why}", "up" if why == "Kill" else "")
            if q.get("z") and q["z"] in db.zones:
                o.emit(f"  ·  {db.zone_name(q['z'])}", "muted")
            elif q.get("z"):
                pass
            o.emit("\n")
            if q.get("sn"):
                o.emit(f"    From {', '.join(q['sn'][:2])}", "muted")
                if q.get("en") and q["en"] != q["sn"]:
                    o.emit(f"  ·  turn in to {', '.join(q['en'][:2])}", "muted")
                o.emit("\n")
            elif q.get("si"):
                o.emit("    Started by an item\n", "muted")
            elif q.get("en"):
                o.emit(f"    Turn in to {', '.join(q['en'][:2])}\n", "muted")
            self.emit_quest_spot(o, qid)
            if q.get("t"):
                o.emit(f"    {q['t'][:220]}\n", "muted")
        o.emit("\nMonster, drop and quest data: QuestieDB (Forever). Drop chances are only known for "
               "quest items; prices are the lowest listing across all Forever auction houses.\n", "muted")
        o.end()

    def my_char(self):
        """The Forever character loaded on the Character tab, if any."""
        c = getattr(self.app.char_tab, "char", None)
        return c if isinstance(c, dict) and c.get("game") == "forever" else None

    def for_me(self, d, char):
        """("+12%", gain, is an upgrade) for a drop against the loaded character's gear."""
        if not char or d["cls"] not in ("Weapon", "Armor"):
            return "", -1e9, False
        g = wl.gear_of(d["id"])
        if not g:
            return ("no data" if g is None else "..."), -1e9, False
        r = wl.rate(char, g, self.app.char_tab.weights(), self.app.char_tab.mode.get())
        if not r:
            return "", -1e9, False
        if not r["usable"]:
            return "can't use", -1e8, False
        if r["same"]:
            return "wearing", 0, False
        if r["better"]:
            return ("new" if r["up_pct"] is None else f"{r['up_pct']:+.0f}%"), r["gain"], True
        return (f"{r['up_pct']:+.0f}%" if r["up_pct"] is not None else "--"), r["gain"], False

    def fill_drops(self):
        tv = self.drops.tree
        tv.delete(*tv.get_children())
        rows = list(self.cur_drops)
        char = self.my_char()
        for d in rows:
            d["_you"] = self.for_me(d, char)
        if self.drop_sort:
            k, rev = self.drop_sort
            keyf = {"item": lambda d: d["name"].lower(), "type": lambda d: d["cls"],
                    "chance": lambda d: d["rate"] or -1, "price": lambda d: d["ah"] or -1,
                    "qty": lambda d: d["qty"], "you": lambda d: d["_you"][1]}[k]
            rows.sort(key=keyf, reverse=rev)
        for d in rows:
            info = wp.cached_info("forever", d["id"])
            q = info.get("q")
            tag = "questitem" if d["cls"] == "Quest" else ("q_" + q if q in QUALITY_COLORS else "")
            cls = info.get("cls") or d["cls"]
            price = wp.fmt_gold(d["ah"]) if d["ah"] else ("--" if self.sources is not None else "...")
            tags = ((tag,) if tag else ()) + (("better",) if d["_you"][2] else ())
            tv.insert("", "end", iid=str(d["id"]), tags=tags,
                      values=[d["name"], cls, f"{d['rate']:.0f}%" if d["rate"] else "",
                              price, d["qty"] or "", d["_you"][0]])
        if char:
            self.want_stats([d["id"] for d in rows if d["cls"] in ("Weapon", "Armor")])

    def want_stats(self, ids):
        """Ask Blizzard (once, in the background) for the stats of drops it hasn't been asked about."""
        todo = [i for i in wl.not_asked(ids) if i not in self.stats_tried]
        if not todo or self.stats_busy or not wp.has_credentials():
            return
        self.stats_busy = True
        self.stats_tried.update(todo)

        def done(_res):
            self.stats_busy = False
            self.fill_drops()
        self.app.in_background(lambda: capture(lambda: wp.fetch_items(wp.connect("forever"), todo)), done)

    def sort_drops(self, key):
        rev = not (self.drop_sort and self.drop_sort[0] == key and self.drop_sort[1])
        if key in ("item", "type") and not self.drop_sort:
            rev = False
        self.drop_sort = (key, rev)
        self.fill_drops()

    def selected_drop(self):
        sel = self.drops.tree.selection()
        if not sel:
            messagebox.showinfo(self.TITLE, "Select a drop in the list first.", parent=self)
            return None
        iid = int(sel[0])
        return next((d for d in self.cur_drops if d["id"] == iid), None)

    def open_drop(self):
        d = self.selected_drop()
        if d:
            webbrowser.open_new_tab(wm.WOWHEAD_ITEM.format(d["id"]))

    def watch_drop(self):
        d = self.selected_drop()
        if d:
            info = wp.cached_info("forever", d["id"])
            self.app.add_entry({"id": d["id"], "name": d["name"], "cls": info.get("cls"), "sub": info.get("sub")})
            Toast(self.app.root, f"Added {d['name']} to your watchlist")

    def drop_on_search(self):
        d = self.selected_drop()
        if d:
            if self.app.game_key() != "forever":
                self.app.game.set("WoW: Forever")
                self.app.on_game_change()
            self.app.tabs.select(self.app.search_tab)
            set_entry(self.app.item, d["name"])
            self.app.lookup(str(d["id"]), by_id=True)

    # ------------------------------------------------------------ tracking list
    def save_tracking(self):
        wm.save_tracking(self.tracked)
        if self.rtree.exists("tracked"):
            self.rtree.item("tracked", text=self.tracked_label())

    def toggle_track(self):
        if self.cur is None:
            return
        tr = self.tracked_entry(self.cur)
        name = self.db.npcs[self.cur]["n"]
        if tr:
            self.tracked.remove(tr)
            msg = f"Stopped tracking {name}"
        else:
            z = self.db.main_zone(self.cur)
            self.tracked.append({"id": self.cur, "name": name, "zone": self.db.zone_name(z) if z else "",
                                 "kills": 0, "note": "", "added": int(time.time())})
            msg = f"Tracking {name}"
        self.save_tracking()
        self.btn_track.config(text="Untrack" if not tr else "Track")
        self.fill_monsters(keep=True)
        self.show_detail()
        self.set_status(msg)

    def add_kill(self, n):
        if self.cur is None:
            return
        tr = self.tracked_entry(self.cur)
        if not tr:
            self.toggle_track()
            tr = self.tracked_entry(self.cur)
        tr["kills"] = max(0, int(tr.get("kills", 0)) + n)
        self.save_tracking()
        self.fill_monsters(keep=True)
        self.show_detail()

    def edit_note(self):
        if self.cur is None:
            return
        tr = self.tracked_entry(self.cur)
        if not tr:
            self.toggle_track()
            tr = self.tracked_entry(self.cur)
        dlg = tk.Toplevel(self)
        dlg.title("Note")
        dlg.transient(self.winfo_toplevel())
        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"Note for {tr['name']} (where it spawns, what you're farming for...)").pack(anchor="w")
        e = ttk.Entry(frm, width=60, font=M(11))
        e.pack(fill="x", pady=8)
        e.insert(0, tr.get("note", ""))
        e.focus_set()

        def save(_ev=None):
            tr["note"] = e.get().strip()
            self.save_tracking()
            self.show_detail()
            dlg.destroy()
        btns = ttk.Frame(frm)
        btns.pack(anchor="e")
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=save).pack(side="right", padx=6)
        e.bind("<Return>", save)


class DungeonTab(MonsterTab):
    """Dungeons: every Forever dungeon and raid in the monster data, how to get there,
    the monsters inside, what they drop (priced on the AH) and the quests that send you in.
    Shares the Monster Compendium's data, prices and tracking list."""

    TITLE = "Dungeons"
    SIDE_LABEL = "Dungeons and raids"
    INTRO = ("Dungeons\n\nPick a dungeon or raid on the left to see where its entrance is, the quickest way "
             "there for each faction, every monster inside, what they drop (priced on the auction house) "
             "and the quests that send you in.\n\n"
             "Click a monster for its own drops and quests; Dungeon overview brings the dungeon page back. "
             "Search above looks through dungeon monsters only.\n\n"
             "Monsters, drops, quests and entrance coordinates: QuestieDB (the Questie addon's community "
             "database). Travel routes are this app's own notes, written from Classic-era geography and not "
             "yet checked in Forever. Edit routes (top right) opens the notes file so you can correct them.")

    def __init__(self, master, app):
        super().__init__(master, app)
        self.mt = app.monster_tab
        self.tracked = self.mt.tracked           # one tracking list for both tabs
        self.zone = None                         # selected dungeon's area id
        self.dmap = {}                           # area id -> dungeon dict
        self.dnpcs = set()                       # every monster that lives in a dungeon
        self.mt.listeners.append(self.adopt)
        ttk.Button(self.top, text="Edit routes...", command=self.edit_routes).pack(side="right", padx=(0, 6))
        ttk.Button(self.bar, text="Dungeon overview", command=self.show_overview).pack(side="left", padx=(12, 0))
        ttk.Button(self.bar, text="Open in Monster Compendium",
                   command=self.to_compendium).pack(side="left", padx=(6, 0))
        self.info.show(self.INTRO)

    # ------------------------------------------------------------ loading (the Compendium owns the data)
    def load(self, update=False):
        mt = self.mt
        if mt.db is not None and not update:
            self.adopt()
            return
        if mt.loading:
            return
        if self.db is None:
            self.info.show("Loading dungeon data...")
        mt.load(update=update)
        if mt.loading:
            return
        if mt.db is None:                        # the download was declined
            self.declined = True
            self.info.show("Dungeons\n\nThe dungeon data hasn't been downloaded yet. It is the same QuestieDB "
                           "download the Monster Compendium uses (about 14 MB, one time).\n\n"
                           "Click Update data (top right) when you're ready.")
        elif self.db is None:
            self.adopt()

    def adopt(self, err=None):
        mt = self.mt
        if mt.db is None:
            if not self.declined:
                self.info.show("Couldn't load the dungeon data.\n\n" + (err or "") +
                               "\n\nClick Update data to try again.")
            return
        self.declined = False
        self.db = mt.db
        self.fill_regions()
        self.update_data_label()
        if wp.has_credentials():
            self.load_prices()
        else:
            self.set_status("No Blizzard API key saved yet, so drops have no auction house prices.")

    def update_data_label(self, newer=None):
        self.data_label.config(text=f"QuestieDB {self.db.version} · {len(self.dmap)} dungeons and raids",
                               foreground=MUTED)

    def load_prices(self, force=False):
        mt = self.mt
        if not force and mt.sources is not None and time.time() - mt.sources_ts < PRICE_TTL:
            if self.sources is not mt.sources:
                self.sources, self.sources_ts = mt.sources, mt.sources_ts
                self.set_status(prices_status(self.sources_ts))
                self.fill_monsters(keep=True)
                self.show_detail()
            return
        super().load_prices(force)

    # ------------------------------------------------------------ dungeon list
    def fill_regions(self):
        t = self.rtree
        t.delete(*t.get_children())
        self.dmap, self.dnpcs = {}, set()
        for group, lst in wd.dungeon_list(self.db):
            g = t.insert("", "end", iid="g:" + group, text=group, open=True, tags=("group",))
            for d in lst:
                self.dmap[d["id"]] = d
                self.dnpcs.update(self.db.by_zone.get(d["id"], []))
                lv = d["levels"]
                t.insert(g, "end", iid=f"z:{d['id']}", text=d["name"] + (f"  ({lv[0]}-{lv[1]})" if lv else ""))
        self.zone = self.view = self.cur = None
        self.cur_drops = []
        for tv in (self.table.tree, self.drops.tree):
            tv.delete(*tv.get_children())
        self.info.show(self.INTRO)

    def on_region(self, _e=None):
        sel = self.rtree.selection()
        if not sel or self.db is None or not sel[0].startswith("z:"):
            return
        self.zone = int(sel[0][2:])
        self.view = ("zone", self.zone)
        self.fill_monsters()

    def view_ids(self):
        ids = super().view_ids()
        if self.view and self.view[0] == "search":
            ids = [n for n in ids if n in self.dnpcs]
        return ids

    def fill_monsters(self, keep=False):
        super().fill_monsters(keep)
        if not keep and self.view and self.view[0] == "zone":
            self.show_overview()                 # a dungeon opens on its own page, not its first monster

    def dungeon_of(self, nid):
        """The dungeon a monster lives in (area id), or None."""
        if self.db is None and self.mt.db is not None:
            self.adopt()
        if self.db is None or nid not in self.db.npcs:
            return None
        z = self.db.npcs[nid]["z"]
        return next((k for k in sorted(z, key=lambda k: -z[k]) if k in self.dmap), None)

    def open_dungeon(self, zid):
        """Show a dungeon's page (used by the Progress tab)."""
        if self.db is None and self.mt.db is not None:
            self.adopt()
        iid = f"z:{zid}"
        if self.db is not None and self.rtree.exists(iid):
            self.rtree.selection_set(iid)
            self.rtree.see(iid)
            self.zone, self.view = zid, ("zone", zid)
            self.fill_monsters()

    def goto(self, nid, zid=None):
        zid = zid or self.dungeon_of(nid)
        if zid:
            self.zone = zid
            super().goto(nid, zid)

    # ------------------------------------------------------------ dungeon page
    def show_detail(self):
        if self.cur is None and self.view and self.view[0] == "zone":
            self.show_overview()
        else:
            super().show_detail()

    def show_overview(self):
        if self.db is None or self.zone not in self.dmap:
            return
        tv = self.table.tree
        if tv.selection():
            tv.selection_remove(tv.selection())
        self.cur = None
        self.btn_track.config(text="Track")
        db, zid, d = self.db, self.zone, self.dmap[self.zone]
        t = wd.load_travel().get(zid) or {}

        self.cur_drops = wd.dungeon_drops(db, zid)
        for x in self.cur_drops:
            s = wp.item_summary(self.sources, x["id"]) if self.sources is not None else None
            x["ah"], x["qty"] = (s["lowest"], s["quantity"]) if s else (None, 0)
        self.cur_drops.sort(key=lambda x: (-(x["ah"] or 0), x["cls"] != "Quest", x["name"]))
        self.fill_drops()

        o = self.info
        o.begin()
        o.emit_link(d["name"], wiki_url(d["name"]), "gold", "bold")
        o.emit("\n")
        kind = (t.get("kind") or "").lower()
        bits = ["Raid" if kind == "raid" else "Dungeon" if kind == "dungeon" else "Type not recorded"]
        if t.get("players"):
            bits.append(f"{t['players']} players")
        if d["levels"]:
            bits.append(f"monsters level {d['levels'][0]}-{d['levels'][1]}")
        bits.append(f"{d['count']} monsters · {len(self.cur_drops)} drops")
        o.emit("  ·  ".join(bits) + "\n", "muted")

        o.emit("\nHow to get there\n", "gold", "bold")
        ents = wd.entrances(db, zid)
        for zone, x, y, label in ents:
            o.emit("Entrance: ", "gold")
            o.emit(f"{zone}  {x:g}, {y:g}" + (f"  ({label})" if label else "") + "   ")
            o.emit_action("Copy waypoint", lambda z=zone, x=x, y=y: self.app.copy_way(wm.way(z, x, y, d["name"])))
            o.emit("\n")
        if not ents:
            o.emit("Entrance location isn't in the data yet.\n", "muted")
        f = self.faction.current()
        sides = [("alliance", "Alliance"), ("horde", "Horde")]
        sides = sides[:1] if f == 1 else sides[1:] if f == 2 else sides
        any_route = False
        for key, label in sides:
            flight, steps = wd.route(t, key)
            o.emit(f"\n{label}\n", "gold")
            if not steps:
                o.emit("Route not recorded yet.\n", "muted")
                continue
            any_route = True
            if flight:
                o.emit(f"Nearest flight point: {flight}\n")
            for i, s in enumerate(steps, 1):
                o.emit(f"{i}. {s}\n")
        if t.get("notes"):
            o.emit(f"\n{t['notes']}\n", "muted")
        if any_route and not t.get("verified"):
            o.emit("\nRoute written from Classic-era geography and not yet checked in Forever. "
                   "Edit routes (top right) to correct it.\n", "muted")
        elif not any_route:
            o.emit("\nKnow the way? Edit routes (top right) opens the notes file.\n", "muted")

        quests = [q for q in wd.dungeon_quests(db, zid) if self.faction_ok(q[1])]
        o.emit(f"\nQuests for this dungeon ({len(quests)})\n", "gold", "bold")
        if not quests:
            o.emit("None known" + (" for this faction" if f else "") + ".\n", "muted")
        for qid, q, why in quests:
            lv = q.get("lv")
            o.emit(f"[{lv if lv and lv > 0 else '?'}] ", "muted")
            o.emit_link(q["n"], wm.WOWHEAD_QUEST.format(qid))
            o.emit({"A": "  Alliance", "H": "  Horde"}.get(q.get("fa"), "") + "\n", "muted")
            if why:
                o.emit("    " + "; ".join(why) + "\n", "up")
            if q.get("sn"):
                o.emit(f"    From {', '.join(q['sn'][:2])}", "muted")
                if q.get("en") and q["en"] != q["sn"]:
                    o.emit(f"  ·  turn in to {', '.join(q['en'][:2])}", "muted")
                o.emit("\n")
            elif q.get("si"):
                o.emit("    Started by an item\n", "muted")
            elif q.get("en"):
                o.emit(f"    Turn in to {', '.join(q['en'][:2])}\n", "muted")
            self.emit_quest_spot(o, qid)
            if q.get("t"):
                o.emit(f"    {q['t'][:220]}\n", "muted")
        o.emit("\nThe list on the left of this text shows everything dropped inside, most valuable first. "
               "Click a monster above for its own drops and quests.\n" +
               ("FOR YOU compares each piece of gear with what " + self.my_char()["name"] + " wears; green rows "
                "are upgrades. Click that heading to sort by it.\n" if self.my_char() else
                "Look up a character on the Character tab and FOR YOU will show which drops are upgrades.\n") +
               "Monsters, drops, quests and entrance coordinates: QuestieDB (Forever). Drop chances are only "
               "known for quest items.\n", "muted")
        o.end()

    # ------------------------------------------------------------ links to the Compendium, routes file
    def extra_menu(self, m):
        m.add_separator()
        m.add_command(label="Open in Monster Compendium", command=self.to_compendium)

    def copy_waypoint(self):
        if self.cur is None and self.db is not None and self.zone in self.dmap:
            ents = wd.entrances(self.db, self.zone)
            if ents:
                self.app.copy_way(wm.way(ents[0][0], ents[0][1], ents[0][2], self.dmap[self.zone]["name"]))
                return
        super().copy_waypoint()

    def to_compendium(self):
        if self.cur is None:
            messagebox.showinfo(self.TITLE, "Select a monster in the table first.", parent=self)
            return
        self.app.tabs.select(self.mt)
        self.mt.goto(self.cur)

    def save_tracking(self):
        super().save_tracking()
        mt = self.mt
        if mt.rtree.exists("tracked"):
            mt.rtree.item("tracked", text=mt.tracked_label())
        if mt.db is not None and mt.view:
            mt.fill_monsters(keep=True)

    def edit_routes(self):
        path = wd.USER_PATH
        try:
            path = wd.editable_path()
            os.startfile(path)
        except (OSError, AttributeError):
            messagebox.showinfo(self.TITLE, f"The travel notes are in this file:\n\n{path}\n\n"
                                "Open it in Notepad to edit the routes.", parent=self)
            return
        self.set_status("Save the file, then pick the dungeon again to see your changes.")


class ProgressTab(ttk.Frame):
    """Progress: one Forever character's quests per zone, current quests, milestones,
    reputations, PvP, dungeons and raids, professions - and what to do next."""

    TITLE = "Progress"
    SECTIONS = [("next", "What to do next"), ("route", "Tonight's route"), ("zones", "Zones"), ("log", "Quest log"),
                ("miles", "Milestones"), ("reps", "Reputations"), ("pvp", "PvP"),
                ("raids", "Dungeons and raids"), ("profs", "Professions"), ("stats", "All statistics"),
                ("chars", "My characters")]
    HEADS = {"next": [("Quest", 230), ("Level", 54), ("Zone", 150), ("From", 150), ("Why", 190)],
             "route": [("Stop", 50), ("Where", 110), ("What to do", 470), ("Quests", 70), ("", 20)],
             "zones": [("Zone", 230), ("Done", 80), ("For you now", 96), ("Progress", 84), ("Quest levels", 100)],
             "log": [("Quest", 250), ("Level", 54), ("Zone", 170), ("Turn in to", 180), ("", 60)],
             "miles": [("Milestone", 280), ("Status", 100), ("Progress", 90), ("Completed", 120), ("", 60)],
             "reps": [("Faction", 240), ("Standing", 110), ("Progress", 130), ("To next", 100), ("", 60)],
             "pvp": [("Statistic", 300), ("Value", 110), ("Detail", 170), ("Group", 150), ("", 20)],
             "raids": [("Dungeon or raid", 230), ("Type", 80), ("Quests done", 100), ("Bosses down", 110),
                       ("Monster levels", 110)],
             "profs": [("Profession", 240), ("Skill", 80), ("Cap", 80), ("Recipes known", 120), ("", 60)],
             "stats": [("Statistic", 300), ("Value", 110), ("Detail", 170), ("Group", 170), ("", 20)],
             "chars": [("Character", 190), ("Level and class", 190), ("Quests done", 96), ("Professions", 280),
                       ("Read from Blizzard", 150)]}
    INTRO = ("Progress\n\nType your WoW: Forever character's first name and surname above and click Load.\n\n"
             "The app reads the character's progress from Blizzard (completed and current quests, milestones, "
             "reputations, PvP, dungeon and raid kills, professions) and compares it with the full quest list "
             "to show how far along each zone is and what to do next.\n\n"
             "Forever characters appear from level 10, after you log out. Blizzard updates a character's data "
             "when it logs out, so load again after a play session.")

    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.mt = app.monster_tab
        self.snap = None
        self.pg = None                       # wpg.Progress once the quest list is loaded too
        self.zone_rows, self.rec, self.route = [], None, None
        self.section = "next"
        self.rows = {}                       # table row id -> what it stands for
        self.cur_quest = None
        self.started = False
        self.mt.listeners.append(lambda err=None: self.rebuild())

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="First name").pack(side="left")
        self.name = ttk.Entry(top, width=14, font=M(11))
        self.name.pack(side="left", padx=(6, 10))
        ttk.Label(top, text="Surname").pack(side="left")
        self.second = ttk.Entry(top, width=14, font=M(11))
        self.second.pack(side="left", padx=(6, 8))
        for e in (self.name, self.second):
            e.bind("<Return>", lambda ev: self.load())
        self.btn_load = ttk.Button(top, text="Load", command=self.load)
        self.btn_load.pack(side="left")
        ttk.Label(top, text="Recent").pack(side="left", padx=(14, 4))
        self.recent = ttk.Combobox(top, state="readonly", width=22)
        self.recent.pack(side="left")
        self.recent.bind("<<ComboboxSelected>>", self.pick_recent)
        ttk.Button(top, text="Guild crafters", command=self.app.open_guild).pack(side="right")
        self.status = ttk.Label(top, foreground=MUTED, font=M(10))
        self.status.pack(side="right", padx=(0, 8))
        self.title = ttk.Label(self, font=F(12, "bold"), foreground=GOLD)
        self.title.pack(anchor="w", pady=(8, 0))
        self.sub = ttk.Label(self, foreground=MUTED, font=M(10))
        self.sub.pack(anchor="w", pady=(0, 6))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=210)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        ttk.Label(left, text="Track", font=F(10, "bold"), foreground=GOLD).pack(anchor="w")
        self.side = ttk.Treeview(left, show="tree", selectmode="browse", style="Side.Treeview")
        self.side.pack(fill="both", expand=True)
        for key, label in self.SECTIONS:
            self.side.insert("", "end", iid=key, text=label)
        self.side.bind("<<TreeviewSelect>>", self.on_section)
        self.side.bind("<ButtonRelease-1>", self.on_side_click)     # click the open section again to get its page back

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        panes = tk.PanedWindow(right, orient="vertical", bg=BG, sashwidth=6, bd=0, sashrelief="flat")
        panes.pack(fill="both", expand=True)
        upper = ttk.Frame(panes)
        self.table = DataTable(upper, [(f"c{i}", "", 120, "w") for i in range(1, 6)], height=10)
        self.table.pack(fill="both", expand=True)
        tv = self.table.tree
        tv.tag_configure("done", foreground=UP)
        tv.tag_configure("now", foreground=GOLD)
        tv.tag_configure("link", foreground=LINK)
        tv.bind("<<TreeviewSelect>>", lambda e: self.on_row())
        tv.bind("<Double-Button-1>", self.on_double)
        panes.add(upper, minsize=150, stretch="always")
        lower = ttk.Frame(panes)
        self.info = OutputText(lower)
        self.info.config(wrap="word")
        self.info.pack(fill="both", expand=True, pady=(6, 0))
        panes.add(lower, minsize=220, stretch="always")
        self.info.show(self.INTRO)
        self.bind("<Map>", lambda e: self.on_show())

    # ------------------------------------------------------------ loading
    def on_show(self):
        self.refresh_recent()
        if self.started:
            return
        self.started = True
        saved = wpg.load_saved()
        snap = saved["chars"].get(saved.get("last") or "")
        if snap:
            set_entry(self.name, snap.get("name", ""))
            set_entry(self.second, snap.get("surname", ""))
            self.adopt(snap)
        elif self.recent_list:
            set_entry(self.name, self.recent_list[0]["name"])
            set_entry(self.second, self.recent_list[0].get("surname", ""))

    def refresh_recent(self):
        seen, lst = set(), []
        saved = wpg.load_saved()["chars"].values()
        for c in list(saved) + [c for c in wp.load_characters() if c.get("game") == "forever"]:
            k = (c.get("name", "").lower(), (c.get("surname") or "").lower())
            if c.get("name") and k not in seen:
                seen.add(k)
                lst.append(c)
        self.recent_list = lst
        self.recent.config(values=[f"{c['name']} {c.get('surname') or ''}".strip() for c in lst])

    def pick_recent(self, _e=None):
        c = self.recent_list[self.recent.current()]
        set_entry(self.name, c["name"])
        set_entry(self.second, c.get("surname") or "")
        saved = wpg.load_saved()["chars"].get(f"{c['name']} {c.get('surname') or ''}".strip().lower())
        if saved:
            self.adopt(saved)
        else:
            self.load()

    def load(self):
        name, second = self.name.get().strip(), self.second.get().strip()
        if not name:
            self.status.config(text="Type the character's first name and surname.")
            return
        if not wp.has_credentials():
            self.status.config(text="Add your Blizzard API key first (restart the app to enter it).")
            return
        self.btn_load.config(state="disabled")
        self.status.config(text=f"Loading {name} {second}...")

        def work():
            try:
                return wpg.fetch(name, second or None)
            except wp.ApiError as e:
                if e.code == 404:
                    raise SystemExit(f"Couldn't find {name} {second}. Forever characters need first name AND "
                                     "surname, must be level 10+, and appear after you log out.")
                raise

        def done(res):
            snap, err = res
            self.btn_load.config(state="normal")
            if not snap:
                self.status.config(text=(err or "Couldn't load the character.").splitlines()[-1])
                return
            wpg.save(snap)
            wp.remember_character({"name": snap["name"], "surname": snap.get("surname", ""), "realm": "",
                                   "game": "forever"})
            self.refresh_recent()
            self.adopt(snap)

        self.app.in_background(lambda: capture(work), done)

    def adopt(self, snap):
        self.snap = snap
        full = f"{snap['name']} {snap.get('surname', '')}".strip()
        self.title.config(text=full)
        bits = [f"Level {snap.get('level', '?')} {snap.get('race', '')} {snap.get('cls', '')}".replace("  ", " "),
                "Horde" if snap.get("faction") == "H" else "Alliance"]
        if snap.get("guild"):
            bits.append(f"<{snap['guild']}>")
        bits.append(f"{len(snap.get('completed') or [])} quests completed")
        bits.append(f"read from Blizzard {clock(snap.get('fetched', 0), '%b %d, %I:%M %p')}")
        self.sub.config(text="  ·  ".join(bits))
        self.status.config(text="")
        if self.mt.db is None and not self.mt.loading and not self.mt.declined:
            self.mt.load()                   # the quest list is the Monster Compendium's data
        self.rebuild()

    def rebuild(self):
        if self.snap is None:
            return
        self.pg = wpg.Progress(self.mt.db, self.snap) if self.mt.db is not None else None
        self.zone_rows = self.pg.zones() if self.pg else []
        self.rec = self.pg.recommend(self.zone_rows) if self.pg else None
        if self.side.selection() != (self.section,):
            self.side.selection_set(self.section)
        self.show_section()

    # ------------------------------------------------------------ sections
    def on_section(self, _e=None):
        sel = self.side.selection()
        if sel and sel[0] != self.section:
            self.section = sel[0]
            self.show_section()

    def on_side_click(self, event):
        if self.side.identify_row(event.y) == self.section and self.table.tree.selection():
            self.show_section()

    def set_rows(self, rows):
        """rows: [(row id, [5 values], tag, payload)]"""
        tv = self.table.tree
        heads = self.HEADS[self.section]
        for i, (text, width) in enumerate(heads, 1):
            tv.heading(f"c{i}", text=text.upper())
            tv.column(f"c{i}", width=width)
        tv.delete(*tv.get_children())
        self.rows = {}
        self.cur_quest = None
        for iid, vals, tag, payload in rows:
            tv.insert("", "end", iid=str(iid), values=list(vals) + [""] * (5 - len(vals)),
                      tags=(tag,) if tag else ())
            self.rows[str(iid)] = payload

    def need_quests(self):
        """False (with a message) when the quest list isn't loaded."""
        if self.pg is not None:
            return True
        self.set_rows([])
        self.info.show("This part needs the quest list, which is the Monster Compendium's QuestieDB download "
                       "(about 14 MB, one time).\n\nOpen the Monster Compendium tab and click Update data, "
                       "then come back." if not self.mt.loading else "Loading the quest list...")
        return False

    def show_section(self):
        if self.snap is None:
            return
        getattr(self, "sec_" + self.section)()

    def qrow(self, qid, why="", zone=None):
        q = self.pg.db.allq.get(qid)
        if not q:
            return None
        return (f"q{qid}", [q[wpg.N], q[wpg.LV] if q[wpg.LV] > 0 else "?", zone or self.pg.zone_name(q),
                            q[wpg.GIVER], why], "link", ("quest", qid))

    def sec_next(self):
        if not self.need_quests():
            return
        r, pg, s = self.rec, self.pg, self.snap
        rows = []
        for qid, name in r["finish"]:
            rows.append(self.qrow(qid, "In your quest log") or
                        (f"q{qid}", [name, "?", "", "", "In your quest log"], "link", ("quest", qid)))
        for qid, zone in r["quests"]:
            lv = pg.db.allq[qid][wpg.LV]
            rows.append(self.qrow(qid, "At your level" if abs(lv - pg.level) <= 2 else
                                  "A little below you" if lv < pg.level else "A little above you", zone))
        self.set_rows([x for x in rows if x])
        o = self.info
        o.begin()
        o.emit("What to do next\n", "gold", "bold")
        n = 0
        if r["finish"]:
            n += 1
            o.emit(f"\n{n}. Finish what's in your quest log\n", "gold")
            for qid, name in r["finish"]:
                o.emit("    ")
                o.emit_link(name or f"Quest {qid}", wm.WOWHEAD_QUEST.format(qid))
                q = pg.db.quests.get(qid)
                o.emit((f"  ·  turn in to {', '.join(q['en'][:2])}" if q and q.get("en") else "") + "\n", "muted")
        z = r["zone"]
        if z:
            n += 1
            o.emit(f"\n{n}. Quest in {z['name']}\n", "gold")
            o.emit(f"    {z['now']} quests there are open to you right now and still worth experience "
                   f"(quest levels {z['lo']}-{z['hi']}). You've done {z['done']} of {z['total']}.\n")
            o.emit("    The table above lists them, closest to your level first.\n", "muted")
        elif pg.level:
            n += 1
            o.emit(f"\n{n}. No open quests found at your level\n", "gold")
            o.emit("    The quest list has nothing new you can pick up right now. Dungeons, professions or "
                   "the next level may open more.\n", "muted")
        for z2 in r["nearly"]:
            n += 1
            o.emit(f"\n{n}. Finish off {z2['name']}\n", "gold")
            o.emit(f"    {z2['done']} of {z2['total']} done, {z2['now']} still open to you.\n")
        fits = r["dungeons"]
        if fits:
            n += 1
            o.emit(f"\n{n}. Dungeons around your level\n", "gold")
            for d in fits:
                lv = d["levels"]
                o.emit(f"    {d['name']}", "bold")
                o.emit(f"  ·  monsters level {lv[0]}-{lv[1]}  ·  quests {d['done']}/{d['total']} done"
                       + (f", {len(d['now'])} you can pick up before a run" if d["now"] else "") + "\n")
            o.emit("    Double-click a dungeon under Dungeons and raids for its entrance and route.\n", "muted")
        profs = [p for p in r["profs"] if p["skill"] < p["max"]]
        capped = [p for p in r["profs"] if p["skill"] >= p["max"]]
        if profs or capped:
            n += 1
            o.emit(f"\n{n}. Professions\n", "gold")
            for p in profs:
                o.emit(f"    {p['name']} {p['skill']}/{p['max']}\n")
            for p in capped:
                o.emit(f"    {p['name']} {p['skill']}/{p['max']}  ·  at the cap for this rank; see a trainer "
                       "for the next one\n")
            o.emit("    The Professions button has a priced leveling guide for each.\n", "muted")
        if r["reps"]:
            n += 1
            o.emit(f"\n{n}. Reputations close to the next standing\n", "gold")
            for rp in r["reps"]:
                o.emit(f"    {rp['name']}: {rp['standing']} {rp['value']}/{rp['max']} "
                       f"({rp['max'] - rp['value']} to go)\n")
        if r["milestones"]:
            n += 1
            o.emit(f"\n{n}. Milestones in progress\n", "gold")
            for a in r["milestones"]:
                o.emit(f"    {a['name']}  ·  progress {a['amount']}\n")
        o.emit("\nHow this is worked out: quests you haven't done, that your faction and class can take, "
               "whose required level and earlier quests you've met, and that aren't so far below you that "
               "they give no experience. The quest list is QuestieDB's, which is still filling in for "
               "Forever, so some quests may be missing or listed too early.\n", "muted")
        if pg.unknown_done:
            o.emit(f"{pg.unknown_done} of your completed quests aren't in the quest list (hidden or brand-new "
                   "quests) and aren't counted in zone progress.\n", "muted")
        if s.get("missing"):
            o.emit("Blizzard didn't return: " + ", ".join(s["missing"]) + ".\n", "muted")
        o.end()

    # ------------------------------------------------------------ tonight's route
    @staticmethod
    def stop_summary(stop):
        gets = [t for k, t, _q in stop["acts"] if k == "get"]
        dos = [t for k, t, _q in stop["acts"] if k == "do"]
        ends = [t for k, t, _q in stop["acts"] if k == "end"]
        parts = []
        if ends:
            parts.append(f"Turn in {len(ends)}" if len(ends) > 1 else ends[0])
        if gets:
            parts.append(f"Pick up {len(gets)}" if len(gets) > 1 else gets[0])
        if dos:
            parts.append(dos[0].split(" for ")[0] + (f" +{len(dos) - 1} more" if len(dos) > 1 else ""))
        return "  ·  ".join(parts)

    def stop_way(self, i):
        r = self.route
        s = r["stops"][i]
        return wm.way(r["zone"], s["x"], s["y"], f"Stop {i + 1}: {self.stop_summary(s)}"[:70])

    def copy_route(self):
        lines = [self.stop_way(i) for i in range(len(self.route["stops"]))]
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append("\n".join(lines))
        Toast(self.app.root, f"Copied {len(lines)} waypoints. In game, TomTom's /ttpaste window takes them all "
                             "at once (if your TomTom has it); otherwise use Copy waypoint on each stop.")

    def emit_stop(self, o, i, links=False):
        r, s = self.route, self.route["stops"][i]
        o.emit(f"\n{i + 1}. ", "gold", "bold")
        o.emit(f"{r['zone']}  {s['x']:g}, {s['y']:g}   ", "gold")
        o.emit_action("Copy waypoint", lambda: self.app.copy_way(self.stop_way(i)))
        o.emit("\n")
        for kind, text, _q in s["acts"]:
            o.emit(f"    {text}\n", *({"get": ("gold",), "end": ("up",)}.get(kind, ())))
        if links:
            o.emit("\nQuests at this stop: ", "muted")
            for n, qid in enumerate(dict.fromkeys(q for _k, _t, q in s["acts"])):
                o.emit(", " if n else "")
                o.emit_link(self.pg.db.allq[qid][wpg.N], wm.WOWHEAD_QUEST.format(qid))
            o.emit("\n")

    def sec_route(self):
        if not self.need_quests():
            return
        r = self.route = self.pg.route(self.zone_rows)
        rows = [(f"s{i}", [i + 1, f"{s['x']:g}, {s['y']:g}", self.stop_summary(s),
                           len({q for _k, _t, q in s["acts"]})],
                 "now" if any(k == "get" for k, _t, _q in s["acts"]) else "", ("stop", i))
                for i, s in enumerate(r["stops"])]
        self.set_rows(rows)
        o = self.info
        o.begin()
        o.emit("Tonight's route" + (f": {r['zone']}" if r["zone"] else "") + "\n", "gold", "bold")
        if not r["stops"]:
            o.emit("\nNo route could be built: the quests open to you have no map positions in the data.\n", "muted")
        else:
            o.emit(f"{r['quests']} quests in {len(r['stops'])} stops, nearest first. Gold lines are pick-ups, "
                   "green lines are turn-ins.   ", "muted")
            o.emit_action("Copy all waypoints", self.copy_route)
            o.emit("\n")
        for i in range(len(r["stops"])):
            self.emit_stop(o, i)
        if r["elsewhere"]:
            o.emit("\nOn another map\n", "gold", "bold")
            for text, zone, x, y, _q in r["elsewhere"]:
                o.emit(f"    {text}  ·  {zone} {x:g}, {y:g}   ")
                o.emit_action("Copy waypoint", lambda z=zone, x=x, y=y, t=text: self.app.copy_way(wm.way(z, x, y, t[:60])))
                o.emit("\n")
        if r["unknown"]:
            o.emit("\nNo location in the data (use your quest log or Questie for these)\n", "gold", "bold")
            for text, _q in r["unknown"]:
                o.emit(f"    {text}\n", "muted")
        fits = [d for d in self.rec["dungeons"]] if self.rec else []
        if fits:
            o.emit("\nAfter that\n", "gold", "bold")
            for d in fits[:3]:
                o.emit(f"    {d['name']}  ·  quests {d['done']}/{d['total']} done"
                       + (f", {len(d['now'])} to pick up first" if d["now"] else "") + "   ")
                ents = wd.entrances(self.pg.db, d["id"])
                if ents:
                    o.emit_action("Copy waypoint to the entrance", lambda e=ents[0], n=d["name"]:
                                  self.app.copy_way(wm.way(e[0], e[1], e[2], n)))
                o.emit("\n")
        o.emit("\nHow this is built: the quests in your log plus the ten open quests closest to your level in "
               "the suggested zone. Each stop is a quest giver, a monster's busiest spawn point or a turn-in, "
               "taken nearest-first, never an objective before its pick-up. It doesn't know about roads, cliffs "
               "or flight paths, or which objectives you've already finished. Click a stop for its quests; "
               "double-click to copy its waypoint.\n", "muted")
        o.end()

    def sec_zones(self):
        if not self.need_quests():
            return
        rows = []
        for i, z in enumerate(self.zone_rows):
            pct = round(100 * z["done"] / z["total"]) if z["total"] else 0
            tag = "done" if z["total"] and z["done"] == z["total"] else "now" if z["now"] else ""
            rows.append((f"z{i}", [z["name"], f"{z['done']} / {z['total']}", z["now"] or "",
                                   f"{bar(pct, 100, 8)} {pct}%", f"{z['lo']}-{z['hi']}" if z["hi"] else ""],
                         tag, ("zone", z)))
        self.set_rows(rows)
        done = sum(z["done"] for z in self.zone_rows)
        total = sum(z["total"] for z in self.zone_rows)
        self.info.show(f"Zones\n\n{done} of {total} quests done across {len(self.zone_rows)} zones, counting "
                       "only quests your faction and class can take. Repeatable quests aren't counted.\n\n"
                       "\"For you now\" is how many you can pick up today that still give experience. Zones "
                       "with the most of those are listed first.\n\nClick a zone to see what's left in it.")

    def zone_detail(self, z):
        pg, o = self.pg, self.info
        o.begin()
        o.emit(z["name"] + "\n", "gold", "bold")
        o.emit(f"{z['done']} of {z['total']} quests done  ·  quest levels {z['lo']}-{z['hi']}\n", "muted")
        groups = [("now", "Open to you now"), ("active", "In your quest log"),
                  ("later", "Later (higher level or an earlier quest first)"),
                  ("gray", "Below your level (no experience)"), ("done", "Done")]
        by = {}
        for qid in z["ids"]:
            by.setdefault(pg.state(qid), []).append(qid)
        for key, label in groups:
            ids = sorted(by.get(key, []), key=lambda q: (pg.db.allq[q][wpg.LV], pg.db.allq[q][wpg.N]))
            if not ids:
                continue
            o.emit(f"\n{label} ({len(ids)})\n", "gold")
            for qid in ids[:60]:
                q = pg.db.allq[qid]
                o.emit(f"[{q[wpg.LV] if q[wpg.LV] > 0 else '?'}] ", "muted")
                o.emit_link(q[wpg.N], wm.WOWHEAD_QUEST.format(qid))
                extra = []
                if key in ("now", "later") and q[wpg.GIVER]:
                    extra.append(f"from {q[wpg.GIVER]}")
                if key == "later":
                    extra += pg.blockers(qid)
                o.emit(("  ·  " + "  ·  ".join(extra) if extra else "") + "\n", "muted")
            if len(ids) > 60:
                o.emit(f"... and {len(ids) - 60} more\n", "muted")
        o.end()

    def sec_log(self):
        s, pg = self.snap, self.pg
        rows = []
        for qid, name in s.get("in_progress") or []:
            q = pg.db.allq.get(qid) if pg else None
            rows.append((f"q{qid}", [name, (q[wpg.LV] if q and q[wpg.LV] > 0 else "?"),
                                     pg.zone_name(q) if q else "", q[wpg.ENDER] if q else ""],
                         "link", ("quest", qid)))
        self.set_rows(rows)
        self.info.show(f"Quest log\n\n{len(rows)} quest{'s' if len(rows) != 1 else ''} in progress and "
                       f"{len(s.get('completed') or [])} completed, as of the last time the character logged "
                       "out.\n\nClick a quest for details; double-click to open it on Wowhead.")

    def quest_detail(self, qid, extra=None):
        """Quest page; extra is Blizzard's own text for it, fetched the first time a quest is opened."""
        pg, o = self.pg, self.info
        self.cur_quest = qid
        q = pg.db.allq.get(qid) if pg else None
        o.begin()
        name = q[wpg.N] if q else next((n for i, n in self.snap.get("in_progress") or [] if i == qid), f"Quest {qid}")
        o.emit_link(name, wm.WOWHEAD_QUEST.format(qid), "gold", "bold")
        o.emit("\n")
        if q:
            st = {"done": "Done", "active": "In your quest log", "now": "Open to you now",
                  "gray": "Below your level", "later": "Not yet available",
                  "closed": "No longer available"}[pg.state(qid)]
            o.emit(f"Level {q[wpg.LV] if q[wpg.LV] > 0 else '?'}  ·  requires level {q[wpg.RL] or 1}  ·  "
                   f"{pg.zone_name(q)}  ·  {st}\n", "muted")
            for label, who, end in (("From: ", q[wpg.GIVER], False), ("Turn in to: ", q[wpg.ENDER], True)):
                if not who:
                    continue
                o.emit(label, "gold")
                o.emit(who)
                spot = pg.db.quest_spot(qid, end)
                if spot:
                    o.emit(f"  ·  {spot[0]} {spot[1]:g}, {spot[2]:g}   ", "muted")
                    o.emit_action("Copy waypoint", lambda sp=spot, w=who: self.app.copy_way(wm.way(*sp, w)))
                o.emit("\n")
            if q[wpg.TEXT]:
                o.emit("\nObjective\n", "gold")
                o.emit(q[wpg.TEXT] + "\n")
            block = pg.blockers(qid)
            if block and pg.state(qid) == "later":
                o.emit("\nBefore you can take it: ", "gold")
                o.emit(", ".join(block) + "\n")
        else:
            o.emit("This quest isn't in the quest list yet.\n", "muted")
        if extra:
            if extra.get("desc"):
                o.emit("\nDescription\n", "gold")
                o.emit(extra["desc"] + "\n")
            rewards = []
            if extra.get("xp"):
                rewards.append(f"{extra['xp']:,} experience")
            if extra.get("money"):
                rewards.append(wp.fmt_gold(int(extra["money"])))
            rewards += extra.get("items") or []
            if rewards:
                o.emit("\nRewards: ", "gold")
                o.emit(", ".join(rewards) + "\n")
        elif extra is None and wp.has_credentials():
            o.emit("\nAsking Blizzard for the description...\n", "muted")
        o.emit("\nDouble-click the quest in the table to open it on Wowhead.\n", "muted")
        o.end()
        if extra is None and wp.has_credentials():
            def done(res):
                if self.cur_quest == qid:
                    self.quest_detail(qid, res[0] or {})
            self.app.in_background(lambda: capture(lambda: wpg.quest_info(qid)), done)

    def sec_miles(self):
        s = self.snap
        rows = []
        if self.pg:
            full = [z for z in self.zone_rows if z["total"] >= 5 and z["done"] == z["total"]]
            rows.append(("m_lvl", [f"Level {s.get('level', 0)}", "", "", ""], "", None))
            rows.append(("m_q", ["Quests completed", "", len(s.get("completed") or []), ""], "", None))
            rows.append(("m_z", ["Zones fully completed", "", f"{len(full)} / {len(self.zone_rows)}", ""], "", None))
        for i, a in enumerate(sorted(s.get("achievements") or [], key=lambda a: (not a["done"], -a["amount"], a["name"]))):
            rows.append((f"a{i}", [a["name"], "Done" if a["done"] else "In progress" if a["amount"] else "Not started",
                                   a["amount"] or "", clock(a["ts"] / 1000, "%b %d %Y") if a["ts"] else ""],
                         "done" if a["done"] else "now" if a["amount"] else "", None))
        self.set_rows(rows)
        n = len(s.get("achievements") or [])
        self.info.show("Milestones\n\n" + (f"Blizzard lists {n} milestones for this character" +
                       (f" ({s['points']} points)" if s.get("points") else "") + ". " if n else
                       "Blizzard didn't return any milestones for this character. ") +
                       "Progress is the number Blizzard reports for the milestone (for a profession milestone, "
                       "your skill).\n\nThe first rows are the app's own count: your level, quests completed "
                       "and zones where every quest for your faction and class is done.")

    def sec_reps(self):
        rows = []
        for i, r in enumerate(sorted(self.snap.get("reputations") or [], key=lambda r: (-r["tier"], -r["value"]))):
            pct = round(100 * r["value"] / r["max"]) if r["max"] else 100
            rows.append((f"r{i}", [r["name"], r["standing"], f"{bar(pct, 100, 8)} {r['value']}/{r['max']}" if r["max"]
                                   else "", r["max"] - r["value"] if r["max"] else ""], "", None))
        self.set_rows(rows)
        self.info.show("Reputations\n\n" + (f"{len(rows)} factions this character has met, highest standing first. "
                       "\"To next\" is the reputation still needed for the next standing." if rows else
                       "Blizzard didn't return any reputations for this character."))

    def stat_rows(self, stats, first=()):
        rows = list(first)
        for i, s in enumerate(stats):
            q = s["qty"]
            val = "" if q is None else f"{int(q):,}" if float(q).is_integer() else f"{q:,.1f}"
            rows.append((f"s{i}", [s["name"], val, s["desc"], s["sub"] or s["cat"]], "", None))
        return rows

    def sec_pvp(self):
        p = self.snap.get("pvp") or {}
        first = []
        if p:
            first = [("p_hk", ["Honorable kills", f"{p.get('hk') or 0:,}", "", "Summary"], "now", None),
                     ("p_rank", ["PvP rank", p.get("rank") or 0, "", "Summary"], "now", None)]
        stats = wpg.pick_stats(self.snap, r"player vs|pvp|battleground|arena|honor|duel|killing blow")
        self.set_rows(self.stat_rows(stats, first))
        self.info.show("PvP\n\nHonorable kills and rank come from Blizzard's PvP summary; the rest are the PvP "
                       "statistics Blizzard keeps for the character." +
                       ("" if stats else "\n\nNo PvP statistics came back for this character yet."))

    def sec_raids(self):
        s, rows = self.snap, []
        kills = {}
        for name, mode, done, total, _ts in (s.get("dungeons") or []) + (s.get("raids") or []):
            cur = kills.get(name.lower())
            if not cur or done > cur[0]:
                kills[name.lower()] = (done, total)
        for d in (self.pg.dungeons() if self.pg else []):
            k = kills.pop(d["name"].lower(), None)
            lv = d["levels"]
            tag = "done" if d["total"] and d["done"] == d["total"] else "now" if d["fits"] else ""
            rows.append((f"d{d['id']}", [d["name"], {"raid": "Raid", "dungeon": "Dungeon"}.get(d["kind"], ""),
                                         f"{d['done']} / {d['total']}", f"{k[0]} / {k[1]}" if k else "",
                                         f"{lv[0]}-{lv[1]}" if lv else ""], tag, ("dungeon", d["id"])))
        for name, (done, total) in kills.items():
            rows.append((f"k{len(rows)}", [name.title(), "", "", f"{done} / {total}", ""], "", None))
        self.set_rows(rows)
        stats = wpg.pick_stats(s, r"dungeon|raid|boss")
        o = self.info
        o.begin()
        o.emit("Dungeons and raids\n", "gold", "bold")
        o.emit("\nQuests done counts each dungeon's quests your faction and class can take. Gold rows are around "
               "your level. Double-click one to open it in the Dungeons tab.\n")
        if not (s.get("dungeons") or s.get("raids")):
            o.emit("\nBlizzard returned no boss kills for this character yet, so Bosses down is empty.\n", "muted")
        if stats:
            o.emit("\nDungeon and raid statistics\n", "gold")
            for st in stats[:40]:
                q = st["qty"]
                o.emit(f"    {st['name']}: {'' if q is None else int(q) if float(q).is_integer() else q}"
                       + (f"  ({st['desc']})" if st["desc"] else "") + "\n")
        if not self.pg:
            o.emit("\nThe dungeon list needs the Monster Compendium's data; open that tab to download it.\n", "muted")
        o.end()

    def sec_profs(self):
        rows = [(f"p{i}", [p["name"], p["skill"], p["max"], p["recipes"] or ""],
                 "now" if p["max"] and p["skill"] >= p["max"] else "", None)
                for i, p in enumerate(self.snap.get("professions") or [])]
        self.set_rows(rows)
        self.info.show("Professions\n\nSkill and cap for the rank you've trained. A gold row is at its cap: see "
                       "a trainer for the next rank.\n\nThe Professions button at the top of the window has "
                       "priced leveling guides.")

    def sec_stats(self):
        self.set_rows(self.stat_rows(self.snap.get("stats") or []))
        self.info.show("All statistics\n\nEverything Blizzard counts for this character, grouped the way "
                       "Blizzard groups it.")

    # ------------------------------------------------------------ all your characters
    def sec_chars(self):
        chars = sorted(wpg.load_saved()["chars"].items(), key=lambda kv: (-kv[1].get("level", 0), kv[0]))
        rows = []
        for key, c in chars:
            profs = ", ".join(f"{p['name']} {p['skill']}" for p in c.get("professions") or [] if p.get("primary")) \
                or ", ".join(f"{p['name']} {p['skill']}" for p in (c.get("professions") or [])[:2])
            rows.append(("c_" + key, [f"{c['name']} {c.get('surname', '')}".strip(),
                                      f"{c.get('level', '?')} {c.get('cls', '')}", len(c.get("completed") or []),
                                      profs, clock(c.get("fetched", 0), "%b %d, %I:%M %p")],
                         "now" if self.snap and wpg.key_of(c) == wpg.key_of(self.snap) else "", ("char", key)))
        self.set_rows(rows)
        o = self.info
        o.begin()
        o.emit("My characters\n", "gold", "bold")
        o.emit(f"\n{len(rows)} character{'s' if len(rows) != 1 else ''} saved. To add one, type its name above and "
               "click Load. Click a row for its summary; double-click to switch the whole tab to it.\n")
        if rows:
            o.emit("\n")
            o.emit_action("Refresh all characters from Blizzard", self.refresh_all)
            o.emit("\n")
        for key, c in chars:
            self.char_block(o, key, c)
        o.emit("\nBlizzard doesn't share bags, bank or gold, so those aren't shown.\n", "muted")
        o.end()

    def char_block(self, o, key, c, full=False):
        o.emit(f"\n{c['name']} {c.get('surname', '')}".rstrip() + "\n", "gold", "bold")
        o.emit(f"Level {c.get('level', '?')} {c.get('race', '')} {c.get('cls', '')}  ·  "
               f"{'Horde' if c.get('faction') == 'H' else 'Alliance'}"
               + (f"  ·  <{c['guild']}>" if c.get("guild") else "") + "\n", "muted")
        pg = wpg.Progress(self.mt.db, c) if self.mt.db is not None else None
        if pg:
            zones = pg.zones()
            done, total = sum(z["done"] for z in zones), sum(z["total"] for z in zones)
            rec = pg.recommend(zones)
            o.emit("Quests: ", "gold")
            o.emit(f"{done} of {total} done  ·  {sum(z['now'] for z in zones)} open now"
                   + (f"  ·  in the log: {', '.join(n for _i, n in c['in_progress'][:3])}"
                      if c.get("in_progress") else "") + "\n")
            o.emit("Next: ", "gold")
            o.emit((f"quest in {rec['zone']['name']} ({rec['zone']['now']} open)" if rec["zone"]
                    else "no open quests found at this level")
                   + (f"  ·  dungeon: {', '.join(d['name'] for d in rec['dungeons'][:2])}"
                      if rec["dungeons"] else "") + "\n")
        profs = c.get("professions") or []
        if profs:
            o.emit("Professions: ", "gold")
            o.emit(", ".join(f"{p['name']} {p['skill']}/{p['max']}" for p in profs) + "\n")
        reps = sorted(c.get("reputations") or [], key=lambda r: (-r["tier"], -r["value"]))
        if reps:
            o.emit("Reputations: ", "gold")
            o.emit(", ".join(f"{r['name']} ({r['standing']})" for r in reps[:None if full else 4])
                   + (f" +{len(reps) - 4} more" if len(reps) > 4 and not full else "") + "\n")
        pvp = c.get("pvp") or {}
        if pvp.get("hk") or pvp.get("rank"):
            o.emit("PvP: ", "gold")
            o.emit(f"{pvp.get('hk') or 0:,} honorable kills, rank {pvp.get('rank') or 0}\n")
        if full:
            done_m = sum(1 for a in c.get("achievements") or [] if a["done"])
            o.emit("Milestones: ", "gold")
            o.emit(f"{done_m} of {len(c.get('achievements') or [])} done\n")
            o.emit(f"Read from Blizzard {clock(c.get('fetched', 0), '%b %d, %I:%M %p')}\n\n", "muted")
            o.emit_action("Switch to this character", lambda: self.switch_to(key))
            o.emit("     ")
            o.emit_action("Remove from this list", lambda: self.remove_char(key))
            o.emit("\n")

    def switch_to(self, key):
        c = wpg.load_saved()["chars"].get(key)
        if c:
            set_entry(self.name, c["name"])
            set_entry(self.second, c.get("surname", ""))
            wpg.save(c)                      # remembers it as the one to open next time
            self.section = "next"
            self.adopt(c)

    def remove_char(self, key):
        wpg.forget(key)
        self.refresh_recent()
        self.show_section()

    def refresh_all(self):
        if not wp.has_credentials():
            self.status.config(text="Add your Blizzard API key first (restart the app to enter it).")
            return
        self.status.config(text="Reading all your characters from Blizzard...")

        def done(res):
            got, err = res
            ok, failed = got or (0, [])
            self.status.config(text=f"Updated {ok} character{'s' if ok != 1 else ''}"
                               + (f"; couldn't read {', '.join(failed)}" if failed else "")
                               + (f"  ({err.splitlines()[-1]})" if err and not got else ""))
            cur = wpg.load_saved()["chars"].get(wpg.key_of(self.snap)) if self.snap else None
            if cur:
                self.adopt(cur)
            else:
                self.show_section()
        self.app.in_background(lambda: capture(wpg.refresh_all), done)

    # ------------------------------------------------------------ rows
    def on_row(self):
        sel = self.table.tree.selection()
        payload = self.rows.get(sel[0]) if sel else None
        if not payload:
            return
        if payload[0] == "stop":
            self.info.begin()
            self.emit_stop(self.info, payload[1], links=True)
            self.info.end()
        elif payload[0] == "char":
            c = wpg.load_saved()["chars"].get(payload[1])
            if c:
                self.info.begin()
                self.char_block(self.info, payload[1], c, full=True)
                self.info.end()
        elif payload[0] == "quest":
            self.quest_detail(payload[1])
        elif payload[0] == "zone":
            self.zone_detail(payload[1])

    def on_double(self, event):
        row = self.table.tree.identify_row(event.y)
        payload = self.rows.get(row)
        if not payload:
            return
        if payload[0] == "stop":
            self.app.copy_way(self.stop_way(payload[1]))
        elif payload[0] == "char":
            self.switch_to(payload[1])
        elif payload[0] == "quest":
            webbrowser.open_new_tab(wm.WOWHEAD_QUEST.format(payload[1]))
        elif payload[0] == "dungeon":
            self.app.tabs.select(self.app.dungeon_tab)
            self.app.dungeon_tab.open_dungeon(payload[1])
        return "break"


# ---------------------------------------------------------------- profession leveling guides

RANK_CAPS = (75, 150, 225)


def gather_kind(guide):
    return (guide or {}).get("kind") == "gather"


class GuideWindow(tk.Toplevel):
    """A profession's 1-300 leveling guide. Every branch is priced from the auction house,
    the cheapest one is marked, and your chosen path and progress are remembered."""

    def __init__(self, app, profession):
        super().__init__(app.root)
        self.app, self.prof = app, profession
        self.title(f"{profession} leveling guide")
        self.geometry("1120x820")
        self.minsize(900, 600)
        self.prices = {}
        self.guide = wp.load_guide(profession)
        self.progress = wp.load_progress()
        self.state = self.progress.setdefault(profession, {"done": [], "choice": {}})

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x")
        tk.Label(head, image=IMG["coin_big"], bg=BG).pack(side="left", padx=(12, 8), pady=6)
        tk.Label(head, text=f"{profession.upper()} LEVELING GUIDE", bg=BG, fg=GOLD,
                 font=F(17, "bold")).pack(side="left")
        self.sub = tk.Label(head, bg=BG, fg=MUTED, font=F(9))
        self.sub.pack(side="left", padx=(10, 0), pady=(8, 0))
        Banner.trim(self).pack(fill="x", pady=(0, 6))

        info = ttk.Frame(self, padding=(14, 0, 14, 4))
        info.pack(fill="x")
        self.intro = ttk.Label(info, wraplength=1060, justify="left")
        self.intro.pack(anchor="w")
        self.trainers = ttk.Label(info, wraplength=1060, justify="left", foreground=MUTED, font=M(11))
        self.trainers.pack(anchor="w", pady=(4, 0))

        bar = ttk.Frame(self, padding=(14, 6, 14, 2))
        bar.pack(fill="x")
        ttk.Button(bar, text="Refresh prices", command=self.reload).pack(side="left")
        ttk.Button(bar, text="Open on Wowhead", command=self.open_wowhead).pack(side="left", padx=6)
        ttk.Button(bar, text="Customize guide", command=self.customize).pack(side="left")
        ttk.Button(bar, text="Reset progress", command=self.reset).pack(side="right")
        self.summary = ttk.Label(self, padding=(14, 4, 14, 4), font=M(12), foreground=TEXT,
                                 wraplength=1080, justify="left")
        self.summary.pack(fill="x")

        body = ttk.Frame(self, padding=(10, 0, 10, 10))
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=INSET, highlightthickness=2, highlightbackground=BORDER)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=INSET)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.win, width=e.width))
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all(
            "<MouseWheel>", lambda ev: self.canvas.yview_scroll(int(-ev.delta / 120), "units")))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        self.reload()

    # ------------------------------------------------------------ data
    def reload(self):
        self.guide = wp.load_guide(self.prof)
        if not self.guide:
            self.summary.config(text=f"No guide for {self.prof} yet. Click Customize guide to write one.")
            return
        g = self.guide
        self.sub.config(text="1 - 300  ·  Classic-based" + ("  ·  your customised copy" if g.get("custom") else "")
                        + "  ·  every branch priced live")
        self.intro.config(text=g.get("intro", ""))
        self.trainers.config(text=g.get("trainers", ""))
        self.render()
        game = self.app.game_key()
        n = len(wp.guide_item_names(g))
        self.summary.config(text=f"Pricing {n} materials at today's auction-house prices... "
                                 "(the first time can take up to a minute)")

        def done(res):
            result, err = res
            if result is None:
                self.summary.config(text=(err or "Couldn't load prices.").splitlines()[-1])
                return
            self.prices = result["prices"]
            self.render()

        self.app.in_background(lambda: capture(lambda: wp.guide_prices(wp.connect(game), g)), done)

    def key(self, step):
        a, b = step["range"]
        return f"{a}-{b}"

    def scores(self, step):
        """Per option: (sort score, cost, value, missing). Lower score is better for crafting;
        for gathering the score is minus the average material value."""
        out = []
        for opt in step["options"]:
            if self.guide.get("kind") == "gather":
                v = wp.option_value(opt, self.prices)
                out.append((-(v or 0), None, v, []))
            else:
                cost, value, missing = wp.option_cost(opt, self.prices)
                out.append(((cost - value) if not missing else float("inf"), cost, value, missing))
        return out

    def best(self, step):
        sc = self.scores(step)
        if not self.prices or len(sc) < 2:
            return None
        order = sorted(range(len(sc)), key=lambda k: sc[k][0])
        i, runner_up = order[0], order[1]
        if sc[i][0] == float("inf"):
            return None
        if abs(sc[i][0] - sc[runner_up][0]) <= abs(sc[i][0]) * 0.005:
            return None                     # a tie (e.g. Alliance vs Horde zones) - no winner to mark
        return i

    def chosen(self, step):
        c = self.state["choice"].get(self.key(step))
        if c is not None and c < len(step["options"]):
            return c
        b = self.best(step)
        return b if b is not None else 0

    # ------------------------------------------------------------ actions
    def choose(self, step, i):
        self.state["choice"][self.key(step)] = i
        wp.save_progress(self.progress)
        self.render(keep_scroll=True)

    def toggle_done(self, step):
        k = self.key(step)
        done = self.state["done"]
        if k in done:
            done.remove(k)
        else:
            done.append(k)
        wp.save_progress(self.progress)
        self.render(keep_scroll=True)

    def reset(self):
        self.state["done"], self.state["choice"] = [], {}
        wp.save_progress(self.progress)
        self.render()

    def open_wowhead(self):
        q = urllib.parse.quote_plus(f"{self.prof} leveling guide")
        webbrowser.open_new_tab(f"https://www.wowhead.com/classic/search?q={q}")

    def customize(self):
        path = wp.export_guide(self.prof)
        try:
            if sys.platform == "win32":
                os.startfile(path)
            messagebox.showinfo(
                "Customize guide",
                f"Your own copy of this guide is in:\n{path}\n\nEdit it in any text editor, save, then click "
                "Refresh prices to load your changes. Delete the file to go back to the built-in guide.",
                parent=self)
        except OSError:
            messagebox.showinfo("Customize guide", f"Edit this file, then click Refresh prices:\n{path}", parent=self)
        self.reload()

    # ------------------------------------------------------------ drawing
    def render(self, keep_scroll=False):
        top = self.canvas.yview()[0] if keep_scroll else 0
        for w in self.inner.winfo_children():
            w.destroy()
        steps = self.guide.get("steps", []) if self.guide else []
        for step in steps:
            self.step_card(step)
        self.update_summary(steps)
        self.update_idletasks()
        self.canvas.yview_moveto(top)

    def update_summary(self, steps):
        if not self.prices:
            return
        done = set(self.state["done"])
        if self.guide.get("kind") == "gather":
            left = sum(1 for st in steps if self.key(st) not in done)
            self.summary.config(text=f"{len(steps) - left} of {len(steps)} brackets done.   Each bracket's highest-"
                                     "value route is marked BEST VALUE - click a route to make it yours.")
            return
        path_cost = path_back = todo = best_net = 0
        unknown = 0
        for st in steps:
            sc = self.scores(st)
            c = self.chosen(st)
            _s, cost, value, missing = sc[c]
            unknown += bool(missing)
            path_cost += cost
            path_back += value
            if self.key(st) not in done:
                todo += cost
            b = self.best(st)
            _s2, bcost, bvalue, _m2 = sc[b if b is not None else c]
            best_net += bcost - bvalue

        def net(v):
            return f"net profit {wp.fmt_gold(-v)}" if v < 0 else f"net cost {wp.fmt_gold(v)}"
        text = (f"Your path: {wp.fmt_gold(path_cost)} in materials, about {wp.fmt_gold(path_back)} back by selling "
                f"your crafts ({net(path_cost - path_back)}).   Still to buy: {wp.fmt_gold(todo)}.   "
                f"Best-value path: {net(best_net)}.")
        if unknown:
            text += f"   ({unknown} bracket{'s have' if unknown != 1 else ' has'} unpriced materials - not counted.)"
        self.summary.config(text=text)

    def skill_bar(self, parent, a, b, done):
        c = tk.Canvas(parent, width=304, height=14, bg=CARD_BG, highlightthickness=0)
        c.create_rectangle(1, 3, 303, 12, fill=INSET, outline=BORDER)
        c.create_rectangle(2 + a, 4, 2 + b, 11, fill=UP if done else GOLD, outline="")
        for cap in RANK_CAPS:
            c.create_rectangle(1 + cap, 1, 3 + cap, 13, fill=GOLD_EDGE, outline="")
        return c

    def step_card(self, step):
        a, b = step["range"]
        done = self.key(step) in self.state["done"]
        card = tk.Frame(self.inner, bg=CARD_BG, highlightthickness=2,
                        highlightbackground=UP if done else BORDER, padx=12, pady=8)
        card.pack(fill="x", padx=8, pady=5)
        head = tk.Frame(card, bg=CARD_BG)
        head.pack(fill="x")
        var = tk.BooleanVar(value=done)
        ttk.Checkbutton(head, variable=var, command=lambda: self.toggle_done(step),
                        style="Card.TCheckbutton").pack(side="left")
        tk.Label(head, text=f"{a} - {b}", bg=CARD_BG, fg=UP if done else GOLD, font=M(16)).pack(side="left", padx=(2, 12))
        self.skill_bar(head, a, b, done).pack(side="left")
        if done:
            tk.Label(head, text="DONE", bg=CARD_BG, fg=UP, font=F(9, "bold")).pack(side="left", padx=10)
        if len(step["options"]) > 1:
            tk.Label(head, text=f"{len(step['options'])} options - click one to choose" +
                     ("" if gather_kind(self.guide) else "  (best value = lowest cost after selling crafts back)"),
                     bg=CARD_BG, fg=MUTED, font=F(9)).pack(side="right")
        if step.get("note"):
            tk.Label(card, text=step["note"], bg=CARD_BG, fg=MUTED, font=F(9), anchor="w",
                     justify="left", wraplength=1000).pack(fill="x", pady=(4, 0))

        scores = self.scores(step)
        best, pick = self.best(step), self.chosen(step)
        gather = self.guide.get("kind") == "gather"
        for i, opt in enumerate(step["options"]):
            on = i == pick
            bg = SELECT_BG if on else CARD_BG
            row = tk.Frame(card, bg=bg, highlightthickness=1,
                           highlightbackground=GOLD_EDGE if on else PANEL_2, padx=8, pady=5)
            row.pack(fill="x", pady=(6, 0))
            line = tk.Frame(row, bg=bg)
            line.pack(fill="x")
            tk.Label(line, image=IMG["radio_on" if on else "radio_off"], bg=bg).pack(side="left", padx=(0, 6))
            tk.Label(line, text=opt["name"], bg=bg, fg=GOLD if on else TEXT, font=F(11, "bold")).pack(side="left")
            if best == i:
                tk.Label(line, text="BEST VALUE", bg=bg, fg=UP,
                         font=F(8, "bold")).pack(side="left", padx=10)
            _s, cost, value, missing = scores[i]
            if self.prices and not gather:
                if value:
                    money(line, value, bg).pack(side="right")
                    tk.Label(line, text="back", bg=bg, fg=MUTED, font=F(9)).pack(side="right", padx=(10, 4))
                money(line, cost, bg).pack(side="right")
                tk.Label(line, text="mats", bg=bg, fg=MUTED, font=F(9)).pack(side="right", padx=(0, 4))
            elif self.prices and gather and value:
                money(line, value, bg).pack(side="right")
                tk.Label(line, text="avg per item", bg=bg, fg=MUTED, font=F(9)).pack(side="right", padx=(0, 4))

            for text in self.option_lines(opt, gather):
                tk.Label(row, text=text, bg=bg, fg=TEXT, font=M(11), anchor="w",
                         justify="left").pack(fill="x", padx=(22, 0))
            if missing:
                tk.Label(row, text="No price found for: " + ", ".join(missing), bg=bg, fg=DOWN, font=M(10),
                         anchor="w").pack(fill="x", padx=(22, 0))
            if opt.get("note"):
                tk.Label(row, text=opt["note"], bg=bg, fg=MUTED, font=F(9), anchor="w", justify="left",
                         wraplength=980).pack(fill="x", padx=(22, 0), pady=(2, 0))
            self._clickable(row, lambda e, st=step, k=i: self.choose(st, k))

    def option_lines(self, opt, gather):
        def price(name):
            p = self.prices.get(name) or {}
            if p.get("each") is None:
                return ""
            return f" ({wp.fmt_gold(p['each'])}{', vendor' if p['how'] == 'vendor' else ''})"
        if gather:
            return ["Gathers: " + "   ".join(f"{g}{price(g)}" for g in opt.get("gathers", []))]
        lines = []
        for recipe, times, mats, _product in opt.get("crafts", []):
            need = ",  ".join(f"{q * times} {m}{price(m)}" for m, q in mats)
            lines.append(f"{recipe} x{times}:  {need}")
        return lines

    def _clickable(self, widget, fn):
        if isinstance(widget, ttk.Widget):
            return
        widget.bind("<Button-1>", fn)
        widget.configure(cursor="hand2")
        for child in widget.winfo_children():
            self._clickable(child, fn)


# ---------------------------------------------------------------- bundled pixel fonts (OFL 1.1)

FONT_DATA = {
    "PixelifySans-Regular-v3.ttf": (   # C, G and c opened up so they no longer read as O / o
        "AAEAAAAPAIAAAwBwR0RFRghoDOoAAEJgAAAAjEdQT1MaLPR3AABC7AAAF0RHU1VCr/Ww4QAAWjAAAAK6T1MvMmFXHVIAAAF4AAAA"
        "YFNUQVR5kGzdAABc7AAAAC5jbWFwBGkDWwAABYgAAAJqZ2FzcAAAABAAAEJYAAAACGdseWa/MosWAAAJ1AAAMw5oZWFkK24mmwAA"
        "APwAAAA2aGhlYQe6AwsAAAE0AAAAJGhtdHjjXTV7AAAB2AAAA65sb2Nhtn+plAAAB/QAAAHebWF4cAD7AHYAAAFYAAAAIG5hbWUx"
        "MFP5AAA85AAAAkZwb3N0LroCFAAAPywAAAMsAAEAAAABAADXA0TgXw889QADA+gAAAAA4R9yMAAAAADnGHD+//D/OAQvA1IAAAAG"
        "AAIAAAAAAAAAAQAAA5j+6AAABGz/8P7NBC8AAQAAAAAAAAAAAAAAAAAAAOkAAQAAAO4AUAAGACQABAABAAAAAAAAAAAAAAAAAAIA"
        "AQAEAjgBkAAFAAACvAKKAAAAjAK8AooAAAHdADIA+gAAAAAAAAAAAAAAAIAAAGcAAABKAAAAAAAAAABOT05FAMAAICIVA5j+6AAA"
        "A5oBISAAAJ8AAAAAAcICvAAAACAAAwK9AGQCSgA8AkoAPAJKADwCSgA8AkoAPAJKADwCSgA8AkoAPAO1ADwCSgA8AkoAPAJKADwC"
        "SgA8AkoAFgJKADwCSgA8AkoAPAJKADwCSgA8AkoAPAJKADwCSgA8AZQAPAGUADwBlAA8AZQAMQGUADwCSgA8AkoAPAJKADwC/wA8"
        "AkoAPAJKADwCSgA8AkoAPAJKADwCSgA8AkoAPAJvADwCSgA8A7UAPAJKADwCSgA8AkoAPAJKADwCSgA8AkoAPAJKADwCSgA8AkoA"
        "PAJKADwCSgA8AkoAPAL/ADwCSgA8AkoAPAJKADwCSgA8AqUAPAKlADwCpQA8AqUAPAKlADwCpQA8AqUAPARsADwCSgA8AkoAPAJK"
        "ADwCSgA8Al0APAJKADwCSgA8AkoAPAJKADwCSgA8AkoAPAJKADwCSgA8AN4APADeADwA3gAXAN4AJgDe//AA3gA8AN7/+QHvADwB"
        "7wA8AkoAPADeADwC/wA8AkoAPAJKADwCSgA8AkoAPAJKADwCSgA8AkoAPAJKABUCSgA8A7UAPAJKADwCSgA8AkoAPAJKADwCSgA8"
        "AkoAPAKlADwCSgA8AkoAPAJKADwCSgA8AkoAPAJAADIC/wA8AkoAPAJKADwCSgA8AkoAPAJKADwDtQA8A7UAPAO1ADwCSgA8AkoA"
        "PAGOADwBYQA8AkoAPAGUADwCSgA8AkoAPAJKADwCSgA8AkoAPAJKADwCSgA8AkoAPAMwADwDcQA8A44APANtADwDvAA8A2gAPAOt"
        "ADwDywA8A98APAEPADwBbAA8AWwAPADIAAAAyAAAAN4APAELADwA3gA8AQsAPAKDADwA3gA8AN4APAJKADwCSgA8AN4APAECADwB"
        "CwA8AqUAPAIRADwCEQA8AN0APADdADwBTQAXAZMAPAH2ADwBugA8AXYAPAF2AB4B0AAeAdAAHgF2ADwBdgAeAQsAPAHRADwB0QA8"
        "AdEAPAELADwBCwA8A2kAHgNVAAoCLAA8AiwAHgHRADwBCwA8AkoAPAKlADwC/gA8AkoAPAGZAEYBmQBGAxUAPAE5ADwA3gA8AkoA"
        "PAHGADwCSgA8AkoAPAKkADwCSgA8AhEAPAJYAEMCWABtAlgAYAJYAG0CWABtAlgAQwJYAEMCWABlAlgAsAJYAG0BCwA8AkoAPANj"
        "ADwAAP/5AAAAYwAAADwAAABNAAAATQAAAB0AAABkAAAAGwAAAAkAAAATASz/9wEKADwBLAA8AE0AXgAbAA0ALAAAAAAAAgAAAAMA"
        "AAAUAAMAAQAAABQABAJWAAAANAAgAAQAFAAvADkAfgClAKwA/wECATEBUwLGAtoC3AMBAwQDCCAUIBogHiAiICYgOiCsISIiEiIV"
        "//8AAAAgADAAOgCgAKcArgECATEBUgLGAtoC3AMAAwMDCCATIBggHCAiICYgOSCsISIiEiIV//8AAABQAAAAAAAAAAD/Af8gAAD+"
        "I/4Q/g/93v3g/dTglwAAAADggOB24ILgH9+j3r7euQABADQAAABQANgA4gDsAAAAAAGKAAAAAAAAAAAAAAAAAAABfgGCAAAAAAAA"
        "AAAAAAAAAAAAAACWAJ0AvQCkAMoA2wDAAL4ArQCuAKMAzwCZAKkAmAClAJoAmwDVANMA1ACfAL8AAQAKAAsADQAPABQAFQAWABcA"
        "HAAdAB4AHwAgACIAKgAsAC0ALgAvADAANQA2ADcAOAA6ALEApgCyANkArADnADsAQwBEAEYASABNAE4ATwBQAFcAWQBaAFsAXABe"
        "AGYAaABpAGoAbABtAHIAcwB0AHUAeACvAMcAsADXAJcAngDIAMwAyQDNAMIA5gDDAH4AuQDYAMQA7ADGANYAlACVAOgA2gDBAKEA"
        "7QCTAH8AugCNAIoAjgCgAAYAAgAEAAgABQAHAAkADAATABAAEQASABsAGAAZABoADgAhACYAIwAkACgAJQDRACcANAAxADIAMwA5"
        "ACsAawA/ADwAPQBBAD4AQABCAEUATABJAEoASwBWAFIAUwBUAEcAXQBiAF8AYABkAGEA0gBjAHEAbgBvAHAAdgBnAHcAKQBlALcA"
        "uACzALUAtgC0AAAAAAAVADgARABQAFwAaAB0AIAAjADBAOUBAwE1AVQBewGdAakBtQHBAc0B5QIJAiQCOQJFAlECXQJpAoMCsALF"
        "AuwDCwMXAzQDQANMA1gDZAOLA5cDyQPmBAIEKARMBHIEiwShBK0EuQTFBNEE7wUWBUIFXwVrBY0FrgW6BcYF0gXdBekF9QYwBk0G"
        "awadBroG5QcHBxMHHwcrBzYHUAd1B48HogevB7oHxQfQB9sH5gf7CBAIMQg+CFsIcAh8CJkIpQixCL0IyAjuCPoJLAlJCWUJgwmZ"
        "CbcJ1wn1CgsKFwojCi8KOgpWCnMKnwq+CsoK1grzCxsLRwtwC44LqQvNC+wMCQweDEQMagyLDLQM2QzvDRgNPQ2GDc8OKA5rDr4P"
        "Cg9mD8YQEhAnEEsQbxBvEG8QehCOEJ8QuRDQEOIQ9REVETURQRFNEWkRkhGhEbARuxHGEdIR3hHqEfYSEhIuElQSehKPEqQSuBLZ"
        "EvsTHRMxE0UTlxPpFBUUQRRjFHcUuBT1FREVNRVkFYsVxBXeFesWEBZAFm4WlBa2FuIW/hcSFx4XNxdPF2IXjhe6F9QX6Bf3GAsY"
        "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"
        "AQb++gxaAc5bW2Raq1nAWmSsAAABADz/9AINAncACwAABREhFSM1MzUhFTMRAaf++mVbARpcDAIeWmRbW/3YAAMAPP/0Ag0CdwAT"
        "ABcAGwAAFzUjNTM1IzUzNSEVMxUjFTMVIxUlITUhNSE1IZdbW1tbARpcXFxc/vABBv76AQb++gxawFC+W1u+UMBaZKxjqwACADz/"
        "9AINAncAEwAXAAAXNSM1MxUhNSE1IzUzNSEVMxEjFQEhNSGXW2UBBv7wW1sBGlxc/vABBv76DFplW6xavltb/jJaAXOrAAMAPP/z"
        "AvQCdwATAB8AOwAAFzUzNTM1MzUzNTMVIxUjFSMVIxUDESMVIzUzNTMVMxEBNSM1MzUzNSMVIzUzNTMVMxUjFSMVMzUzFSMVp09Q"
        "T1FZT1FPUGclOC45LwFeLy+Mgjkvli4ujII4Lgyonk+fT6hQnk+eATQBFy84Ly/+4P7LLpkvUy84Ly9mL4Vhay4AAwA8//MDNAJ3"
        "ABMAHwA7AAAXNTM1MzUzNTM1MxUjFSMVIxUjFQMRIxUjNTM1MxUzEQE1IzUzFTM1IzUzNSMVIzUzNTMVMxUjFTMVIxXZT1BPUVlP"
        "UU9QmSU4LjkvAZ4wOoCKioA6MJQwMDAwDKieT59PqFCeT54BNAEXLzgvL/7g/ssvOC5TOFIuOC8vZiRnLwADADz/8wNSAncAEwAv"
        "AEsAAAU1MzUzNTM1MzUzFSMVIxUjFSMVAzUjNTM1MzUjFSM1MzUzFTMVIxUjFTM1MxUjFQE1IzUzFTM1IzUzNSMVIzUzNTMVMxUj"
        "FTMVIxUBClBPUFBaUFBQT/ouLoyCOC6WLy+MgjkvAY4wOoCKioA6MJQwMDAwDKieT59PqFCeT54BMi5nL1MvOS4uZy9TLzku/s0v"
        "OC5TOFIuOC8vZiRnLwAABAA8//MDMAJ3ABMAHwArADMAABc1MzUzNTM1MzUzFSMVIxUjFSMVAxEjFSM1MzUzFTMRATUjNTM1MzUz"
        "NTMRJzM1IxUjFSPZT1BPUVlPUU9QmSU4LjkvAiW7Ly8uaLuCJS4vDKieT59PqFCeT54BNAEXLzgvL/7g/stdZy4uL/6xlYIvLgAE"
        "ADz/8wN/AncAEwAvADsAQwAABTUzNTM1MzUzNTMVIxUjFSMVIxUBNSM1MxUzNSM1MzUjFSM1MzUzFTMVIxUzFSMVATUjNTM1MzUz"
        "NTMRJzM1IxUjFSMBKFBPUFBaUFBQT/7pLzmAioqAOS+UMDAwMAJIuy8uL2e7gyUvLwyonk+fT6hQnk+eATQvOC5TOFIuOC8vZiRn"
        "L/7LXWcuLi/+sZWCLy4ABQA8//MDKwJ3ABMAHwAzADcAOwAAFzUzNTM1MzUzNTMVIxUjFSMVIxUDESMVIzUzNTMVMxEBNSM1MzUj"
        "NTM1MxUzFSMVMxUjFSczNSM1MzUj2U9QT1FZT1FPUJklOC45LwGTLy8vL5YwMDAwjIKCgoIMqJ5Pn0+oUJ5PngE0ARcvOC8v/uD+"
        "yy9nJGcvL2ckZy85UzhUAAAFADz/8wNwAncAEwAvADMARwBLAAAFNTM1MzUzNTM1MxUjFSMVIxUjFQE1IzUzFTM1IzUzNSMVIzUz"
        "NTMVMxUjFTMVIxUFMzUjBzUjNTM1IzUzNTMVMxUjFTMVIxUnMzUjAR5QT1BQWlBQUE/+8y85gIqKgDkvlDAwMDABtoKCCi8vLy+W"
        "Ly8vL4yCggyonk+fT6hQnk+eATQvOC5TOFIuOC8vZiRnL/xTjC9nJGcvL2ckZy/EVAAABQA8//MDjgJ3ABMAMwA3AEsATwAABTUz"
        "NTM1MzUzNTMVIxUjFSMVIxUBNSM1MxUzNSM1IzUjNTM1MxUzFSM1IxUzFTMVMxUjFQUzNSMHNSM1MzUjNTM1MxUzFSMVMxUjFScz"
        "NSMBPE9QT1FZT1FPUP7VLjiCXS8uLpYwOoIvXTAwAdKDgwouLi4uljAwMDCMg4MMqJ5Pn0+oUJ5PngEzLzguJC8uZy8vZ15ULi84"
        "L/tTjC9nJGcvL2ckZy/EVAAABQA8//MDogJ3ABMAHwAzADcAOwAABTUzNTM1MzUzNTMVIxUjFSMVIxUDESMVIzUzNTMVMxEBNSM1"
        "MzUjNTM1MxUzFSMVMxUjFSczNSM1MzUjAVBPUE9RWU9RT1CzgjguljABrC4uLi6WMDAwMIyCgoKCDKieT59PqFCeT54BMwEYLzgv"
        "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"
        "uDgiZVs2LgACAB7/lQMtAs4AIwBHAAAFNSM1IzUjNSM1MzUzNTM1MzUzFSMVIxUjFSMVMxUzFTMVMxUhNSM1IzUjNSM1MzUzNTM1"
        "MzUzFSMVIxUjFSMVMxUzFTMVMxUCx1pbW1tbW1taZlxaW1tbW1pc/l1bW1tbW1tbW2VcWltbW1taXGtbW1pbY1tbWltlWltaUFta"
        "W2VbW1pbY1tbWltlWltaUFtaW2UAAAIACv+VAxkCzgAjAEcAAAU1MzUzNTM1MzUjNSM1IzUjNTMVMxUzFTMVMxUjFSMVIxUjFSE1"
        "MzUzNTM1MzUjNSM1IzUjNTMVMxUzFTMVMxUjFSMVIxUjFQFIW1tbW1tbW1tlW1tbW1tbW1v+XVtbW1tbW1tbZVtbW1tbW1tba2Vb"
        "WltQWltaZVtaW1tjW1pbW2VbWltQWltaZVtaW1tjW1pbWwAAAQA8/5UCDQLOACMAAAU1IzUjNSM1IzUzNTM1MzUzNTMVIxUjFSMV"
        "IxUzFTMVMxUzFQGnWlxaW1taXFpmXFpcWlpcWlxrW1taW2NbW1pbZVpbWlBbWltlAAEAHv+VAe8CzgAjAAAXNTM1MzUzNTM1IzUj"
        "NSM1IzUzFTMVMxUzFTMVIxUjFSMVIxUeW1tbW1tbW1tlW1taXFxaW1trZVtaW1BaW1plW1pbW2NbWltbAAACADwBuAGUAncACwAX"
        "AAABNTM1IzUzFTMVIxUjNTM1IzUzFTMVIxUBMC5cZiws/y5bZS0tAbg4ImVbNi44ImVbNi4AAAEAPAG4AM4CdwALAAATNTM1IzUz"
        "FTMVIxVpLltlLS0BuDgiZVs2LgACADwAPgINAd8AMwA3AAA3NSM1IzUzNTM1MxUzFTMVMxUjFSMVIzUjFSM1IzUzNTMVMxUzNTM1"
        "IzUjNSMVIxUzFTMVJzM1I5cuLS0u7S0uLi4uNB+KKiqKKSAuLi3ZLi62eXZ2Pi4t7CwuLiwtZS0tJiYmeicncTVRLS0t2C04imcA"
        "AwA8//QCaAJ3AB8AJwAvAAAXNSM1MzUzNSM1IzUzNSEVMxUjFSMVMxUzFTMVIzUjFSUhNSM1IxUjNzM1MzUhFTOXW1taWltbARpc"
        "XFpaXFtlUv7wAQZaUlpaUlr++loMWmVbUFpkW1tkWlBbW2RaWmRRW1u+W1BQAAABADz/PwLBAncADwAABREhNSMRMzUhFSMRIxEj"
        "EQGn/vBbWwIqMjSAwQFsWgEXW2X9LQLT/S0AAAEAPP/0Ag0CdwAZAAAXNSM1MzUjNTM1IRUzFSM1IRUhFTMVIRUhFZdbW1tbARpc"
        "Zv76ARBc/pQBbAxawFC+W1tkWqtZZVFkAAMARgFiAVICbQALAA8AIwAAEzUjNTM1MxUzFSMVJzM1Ixc1IzUzNTMVMxUjNSMVMzUz"
        "FSMVcy0tsS4up52dMhISPhEbKiobEQFiLrAtLbAuOJyAET4TExoQKhMdEQADAEYBYgFSAm0ACwAPABsAABM1IzUzNTMVMxUjFScz"
        "NSMXNTM1MxUzFSM1IxVzLS2xLi6nnZ0uDCYMDSMBYi6wLS2wLjicczEMDA0MMAACADwBKQLYAncAGwArAAABETM1MxUzFTM1MzUz"
        "FTMRIxEjFSMVIzUjNSMRIREjFSM1MzUzFTMVIzUjEQGJLzguJS46LTcmLjkuJP7XJTguli44JQEpAR8vL1tbLy/+4QEWXIuLXP7q"
        "ARYvOC8vOC/+6gACADwBiAD8AkgACwAPAAATNSM1MzUzFTMVIxUnMzUjYCQkeCQkbmRkAYgldiUldiUuYwAAAQA8//QAoQJ3AAMA"
        "ABcRMxE8ZQwCg/19AAABADwAAAINApMAGwAAMzUjNSMRMzUzNTMVMxUzFSM1IREhNTMVIxUjFe5XW1tXbVZcZv76AQZmXFZiWgEZ"
        "W2NjW2Ra/vtaZFpiAAYAPACMAYoB2AALAA8AEwAXABsAHwAANzUjNTM1MxUzFSMVBzUzFQM1MxUXMzUjFzUzFQM1MxWYLi6VLi7x"
        "ODg4LoGBrzk5OboulC4ulC4uODgBFDg4roDmODgBFDg4AAEAPP+ZAg0C0gAjAAAXNSM1IzUzFSE1ITUjNTM1MzUzFTMVMxUjNSEV"
        "IRUzFSMVIxX6Y1tlAQb+8FtbY2ZRXGb++gEQXFxRZ1taZVusWr5bW1tbZFqrWcBaWwAAAQA8//QCDQJ3ABsAABc1IxEzNSEVMxUj"
        "NSEVMxUjFTMVIxUhNTMVIxWXW1sBGlxm/vq3t7e3AQZmXAxaAc5bW760ZmUxZFq2wFoAAAEAPP/0AmcCdwAXAAAXNTMRMzUhFTMV"
        "IzUhFTMVIxUhNTMVIxU8W1oBHFpk/vi2tgEIZFoMZAHEW1tkWqtjrFtlWgAAAQA8//QCDQJ3ACMAABc1IzUzNSM1MzUjNSM1MxUz"
        "FTM1MzUzFSMVIxUzFSMVMxUjFfFaWlpaWltlWlJaZlxaWlpaWgxSZCNlLFq/tVtbtb9aLGUjZFIAAAEAPP/0AdQCdwATAAAXNTM1"
        "MzUzNTM1MxUjFSMVIxUjFTxPUE9RWU9RT1AMqJ5Pn0+oUJ5PngAAAQBDAFcCFAIlAAsAADc1IzUzNTMVMxUjFfi1tWa2tleqZMDA"
        "ZKoAAAEAbQDxAeoBVgADAAA3NSEVbQF98WVlAAEAYABwAfcCBAALAAA3JzcnNxc3FwcXByeuR4GIR4iBR4B4R3lwR3+HR4eAR4B3"
        "R3cAAwBtAFEB6gH7AAMABwALAAA3NSEVBzUzFQM1MxVtAX3xZWVl8WVloGVlAUZkZAAAAgBtAIcB6wGHAAMABwAAEzUhFQU1IRVt"
        "AX7+ggF+ASJlZZtkZAABAEP/lQIUAs4AIwAAFzUzNTM1MzUzNSM1IzUjNSM1MxUzFTMVMxUzFSMVIxUjFSMVQ1tbW1tbW1tbZVtb"
        "WlxcWltba2VbWltQWltaZVtaW1tjW1pbWwAAAQBD/5UCFALOACMAAAU1IzUjNSM1IzUzNTM1MzUzNTMVIxUjFSMVIxUzFTMVMxUz"
        "FQGuWlxaW1taXFpmXFpcWlpcWlxrW1taW2NbW1pbZVpbWlBbWltlAAIAZf/5AfQB6wALAA8AADc1IzUzNTMVMxUjFQc1IRX2kZFs"
        "kpL9AY+beGB4eGB4omRkAAABALAAxQGnASwACwAANzUzFTM1MxUjNSMVsJglOpklxWcuLmcvLwAAAQBtAMcB6gGHAAUAACU1ITUh"
        "FQGF/ugBfcdbZcAAAQA8AhIAzgJ3AAsAABM1MzUzFTMVIzUjFTwtOC03JAISNy4uNy4uAAEAPP9EAg0BwgALAAAXETMRIREzESMV"
        "IRU8ZQEGZlz+8LwCfv6WAWr+jFqwAAADADz/9AMmAncAGwAnADMAABc1MzUzNTM1MzUzNTM1MxUjFSMVIxUjFSMVIxUDNSM1MzUz"
        "FTMVIxUBNSM1MzUzFTMVIxVtXFpcWltcZFpcW1pcWjxbW2RcXAFrW1tlW1sMZFtbWVtaW2VaWlpbW1oBalpkW1tkWv6WWmVbW2Va"
        "AAL/+QIMATMCcQADAAcAAAM1MxUzNTMVB2ZvZQIMZWVlZQABAGMCDADJAnEAAwAAEzUzFWNmAgxlZQABADwCDADOAp0ACwAAEzUj"
        "NSM1MxUzFTMVly4tNy4tAgwsLjcuLTYAAQBNAgwA3wKdAAsAABM1MzUzNTMVIxUjFU0tLjctLgIMNi0uNy4sAAEATQIMAN8CcQAL"
        "AAATNTM1MxUzFSM1IxVNLTgtNyQCDDcuLjcuLgABAB0CDAEQAnEABwAAEzUzFTM1MxUdN4Y2AgxlLi5lAAIAZAIMAMkCcQADAAcA"
        "ABM1MxUnMzUjZGVEIyMCDGVlISMAAAEAGwIMARICcwALAAATNTMVMzUzFSM1IxUbmCU6mSUCDGcuLmcvLwABAAkCDAEjAlwAAwAA"
        "EzUhFQkBGgIMUFAAAAIAEwIMARECcQADAAcAABM1MxUzNTMVE2YzZQIMZWVlZQAC//cB4wExAkgAAwAHAAADNTMVMzUzFQlmb2UB"
        "42VlZWX//wA8AgwAzgKdAAYA3gAAAAEAPAIcAM4CrQALAAATNTM1MzUzFSMVIxU8LS43LS4CHDYtLjcuLP//AE0CDADfAnEABgDg"
        "AAAAAgBeAh0AwwKCAAMABwAAEzUzFSczNSNeZUQjIwIdZWUhIwD//wAbAgwBEgJzAAYA4wAAAAEADQIdAScCggADAAATNSEVDQEa"
        "Ah1lZQAAAQAs/zgBGQAlABMAABc1IzUzFTM1IzUjNTMVMxUzFSMVWi44fi4tNy4tLcgtNy0jLWZcLTctAAAAAAAACgB+AAMAAQQJ"
        "AAAAtAEUAAMAAQQJAAEAGgD6AAMAAQQJAAIADgDsAAMAAQQJAAMAPgCuAAMAAQQJAAQAKgCEAAMAAQQJAAUAGgBqAAMAAQQJAAYA"
        "KABCAAMAAQQJAA4ANgAMAAMAAQQJAQAADAAAAAMAAQQJAQEADgDsAFcAZQBpAGcAaAB0AGgAdAB0AHAAcwA6AC8ALwBzAGMAcgBp"
        "AHAAdABzAC4AcwBpAGwALgBvAHIAZwAvAE8ARgBMAFAAaQB4AGUAbABpAGYAeQBTAGEAbgBzAC0AUgBlAGcAdQBsAGEAcgBWAGUA"
        "cgBzAGkAbwBuACAAMQAuADAAMAAwAFAAaQB4AGUAbABpAGYAeQAgAFMAYQBuAHMAIABSAGUAZwB1AGwAYQByADEALgAwADAAMAA7"
        "AE4ATwBOAEUAOwBQAGkAeABlAGwAaQBmAHkAUwBhAG4AcwAtAFIAZQBnAHUAbABhAHIAUgBlAGcAdQBsAGEAcgBQAGkAeABlAGwA"
        "aQBmAHkAIABTAGEAbgBzAEMAbwBwAHkAcgBpAGcAaAB0ACAAMgAwADIAMQAgAFQAaABlACAAUABpAHgAZQBsAGkAZgB5ACAAUwBh"
        "AG4AcwAgAFAAcgBvAGoAZQBjAHQAIABBAHUAdABoAG8AcgBzACAAKABoAHQAdABwAHMAOgAvAC8AZwBpAHQAaAB1AGIALgBjAG8A"
        "bQAvAGUAaQBmAGUAdAB4AC8AUABpAHgAZQBsAGkAZgB5AC0AUwBhAG4AcwApAAAAAgAAAAAAAP+1ADIAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAADuAAAAJADJAQIAxwBiAK0AYwCuAJAAJQAmAGQAJwDpACgAZQDIAMoAywApACoAKwAsAMwAzQDOAM8ALQAuAC8AMAAxAGYA"
        "MgDQANEAZwDTAJEArwCwADMA7QA0ADUANgA3ADgA1ADVAGgA1gA5ADoAOwA8AOsAPQBEAGkAawBsAGoAbgBtAKAARQBGAG8ARwDq"
        "AEgAcAByAHMAcQBJAEoASwBMANcAdAB2AHcBAwB1AE0BBABOAE8AUABRAHgAUgB5AHsAfAB6AKEAfQCxAFMA7gBUAFUAVgCJAFcA"
        "WAB+AIAAgQB/AFkAWgBbAFwA7AC6AF0BBQEGAQcAwADBAJ0AngATABQAFQAWABcAGAAZABoAGwAcAPQBCAEJAPUA9gEKAQsBDAEN"
        "AQ4BDwEQAAMBEQARAA8AHQAeAKsABACjACIAogDDAIcADQAGABIAPwESARMAEACyALMAQgALAAwAXgBgAD4AQADEAMUAtAC1ALYA"
        "twCpAKoAvgC/AAUACgAjAAkAiACGAIsAigCMAIMAXwCEAL0ABwEUAIUAlgEVAA4A7wDwALgAIAAhAB8AkwBhAKQAQQEWAAgBFwEY"
        "ARkBGgEbARwBHQEeAR8BIACOAEMAjQDYAN0A2QDaAN4GQWJyZXZlCWkubG9jbFRSSwd1bmkwMjM3A2ZfZgVmX2ZfaQVmX2ZfbAd1"
        "bmkyMTUzB3VuaTIxNTQJb25lZWlnaHRoDHRocmVlZWlnaHRocwtmaXZlZWlnaHRocwxzZXZlbmVpZ2h0aHMHdW5pMDBCOQd1bmkw"
        "MEIyB3VuaTAwQjMHdW5pMDBBMBZwZXJpb2RjZW50ZXJlZC5sb2NsQ0FUG3BlcmlvZGNlbnRlcmVkLmxvY2xDQVQuY2FzZQRFdXJv"
        "B3VuaTIyMTUHdW5pMDBCNQd1bmkwMzA4B3VuaTAzMDcJZ3JhdmVjb21iCWFjdXRlY29tYgd1bmkwMzAyB3VuaTAzMDYHdW5pMDMw"
        "QQl0aWxkZWNvbWIHdW5pMDMwNA51bmkwMzA4Lm5hcnJvdwABAAH//wAPAAEAAgBEAAAADgAAAHIADgAFAC4AIAAgABgAGAACAAEA"
        "eQB9AAAAAQAEAAEBJQACAAoABgABAnkAAQE8AAEABAABAdoAAgAHAAEADQABAA8AVgABAFgAeAABAHkAfQACANwA3AADAN4A3wAD"
        "AOMA5AADAAEAAgAAAAwAAAAMAAEABQDcAN4A3wDjAOQAAQAAAAoAKABOAAJERkxUAA5sYXRuAA4ABAAAAAD//wADAAAAAQACAANr"
        "ZXJuACBtYXJrABpta21rABQAAAABAAIAAAABAAEAAAABAAAAAwI0AC4ACAAGABAAAQAKAAEAAQIUABYAAQHgAAwAAQAEAAEAhQKt"
        "AAEAAQDeAAQAAAABAAgAAQHwAaAAAQG8AAwAdQGOAY4BjgGOAY4BiAGOAY4BggF8AXwBfAF2AXwBfAF8AXwBcAFqAXwBfAFkAWQB"
        "ZAFkAV4BfAF8AXwBWAF8AXwBfAF8AXwBfAGIAVIBfAFMAWoBagFqAXwBfAF8AXwBfAF8AXwBRgFqAVgBagF8AXwBfAFAAUABQAFA"
        "AToBQAFAATQBLgEuAS4BfAEoAS4BLgEuAS4BIgF8AS4BfAEcARwBHAEcARwBFgEQAXwBCgEEAS4BLgEuAS4BLgEuASIBLgEuAP4B"
        "LgF8AS4BLgD4AXwA8gEuAS4BLgEuASIA7AEEAS4BLgEuAS4BLgABASABwgABAVMBwgABAU0BwgABAdsBwgABAYABwgABAG8CdwAB"
        "AX0BwgABAEICrQABAG8BwgABAPgCrQABAS8CdwABASUBwgABAnEBwgABAQECrQABAS4BwgABAPUDYgABAdsCdwABATgCvAABAYAC"
        "dwABAJsDYgABAMoCdwABASUCvAABAPgDVgABAPoCdwABASUCdwABAfQCagABAPgDYgABASUCdgACAAQAAQANAAAADwBPAA0AUQBW"
        "AE4AWAB4AFQABQAAAC4AAAAoAAAAIgAAABwAAAAWAAEAkwHCAAEAngHCAAEApQHCAAEAsgHCAAEAkgHCAAEABQDcAN4A3wDjAOQA"
        "AgAIAAIIHAAKAAIFDAAEAAAG+gWCAB0AFgAAAAAAAAAAAAD/7AAAAAAAAAAAAAAAAAAAAAAAAP/iAAAAAAAAAAAAAAAAAAAAAP/s"
        "/+wAAP/iAAAAAAAAAAAAAAAA/+wAAAAA/4j/7AAA/+z/2AAA/+wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/7AAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAD/4gAAAAAAAAAAAAAAAAAAAAAAAP/s/+wAAAAA/9gAAAAAAAAAAAAA/+wAAP/sAAAAAAAAAAD/7AAA"
        "AAAAAAAA/+IAAAAAAAD/4gAAAAAAAAAAAAD/7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/iP/sAAAAAP/YAAAAAAAAAAAAAAAAAAD/"
        "7AAAAAAAAAAA/+wAAAAAAAAAAAAAAAAAAP/s/+IAAP/sAAAAAAAAAAAAAP/sAAAAAAAAAAAAAAAAAAAAAAAA/9gAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/zgAAAAD/9v/O/84AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/"
        "9gAAAAAAAAAA/+wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/i/+IAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAD/zgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/iAAAAAAAAAAAAAAAAAAAA"
        "AAAA/+IAAP/sAAAAAAAAAAAAAAAA/+wAAAAA/5z/7AAA/+z/2AAA/+wAAAAAAAD/7AAA/+wAAAAAAAAAAAAAAAAAAAAAAAD/iAAA"
        "AAD/7AAAAAAAAAAAAAD/7AAAAAD/4gAAAAAAAAAA/+wAAAAAAAAAAP+I/+wAAP/s/7oAAP/sAAAAAAAAAAAAAP/sAAAAAAAAAAAA"
        "AAAAAAAAAAAA/8QAAAAAAAD/7AAA/+wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/4gAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAD/zgAAAAAAAAAA/+IAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+IAAP/OAAAAAAAAAAAAAAAAAAAAAP/s/9gAAAAAAAAA"
        "AAAA/+IAAAAA/+wAAAAA/+IAAAAAAAAAAAAAAAAAAAAAAAD/iP/s/7D/7P+cAAAAAAAA/87/4v/i/+L/nP/O/5z/2P+m/9gAAP/s"
        "/+L/2P/E/5z/4v+cAAAAAP/OAAAAAP/O/7oAAP/OAAAAAAAAAAD/4v/E/+L/4v/Y/37/zgAA/+L/kgAA/9gAAAAA/+z/4gAA/+IA"
        "AAAAAAAAAAAAAAD/7AAAAAD/iP/sAAD/7P/OAAD/7AAAAAAAAP/OAAD/nAAAAAAAAAAA/7oAAP/YAAAAAAAA/5wAAP+c/6YAAP/O"
        "AAAAAAAA/+wAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/4j/7AAAAAAAAAAAAAAAAAAA/+z/7AAA/8QAAAAAAAAAAP/sAAAAAAAAAAAA"
        "AP/OAAD/7P/YAAD/7AAAAAAAAP/2AAD/4gAAAAAAAP9q/+IAAP/2AAAAAP+I/+IAAP/sAAAAAP/sAAAAAP/sAAAAAP/sAAAAAAAA"
        "AAD/7AAA/+wAAAAAAAD/7AAA/+z/2AAA/+wAAQA5AAEACgALAAwADQAOABYAFwAcAB0AHgAfACAAIgAsAC4ALwAwADYAOwBEAEUA"
        "RgBNAE4ATwBQAFEAUgBTAFcAWQBaAFsAXABoAGkAagBsAG0AcwB1AIAAgQCDAIQAhgCHAIgAiQCYAJwAqQCqAKsArADHAAIAPgAB"
        "AAEADgAJAAkADgAKAAwAAwANAA4ABAAPAA8AAwAUABQABAAVABUAAwAWABYABAAXABcAFAAdAB0ACAAeAB4ACwAfAB8ACAAgACAA"
        "BAAiACIAAwApACkAAwAqACoACAArACsABAAsACwAAwAtAC0ACAAuAC4ADAAvAC8ADwAwADAACwA2ADYACwA7ADsABQA8AEEABwBC"
        "AEIABQBDAEMAAgBEAEUABQBGAEcAEABIAEgABQBJAEwAAQBNAE0AAgBPAE8AAgBQAFAADQBRAFEACgBTAFMADQBWAFYADQBZAFoA"
        "AgBbAFwACgBeAF4ABQBfAGIAAQBkAGQAAQBlAGUABQBnAGcAAgBoAGgABQBqAGoAEgBrAGsAAgBsAGwAEwBtAG0AFQBuAHEABgBz"
        "AHMACgCAAIAAAwCBAIEADwCGAIYAAwCJAIkADACYAJkACQCcAJwACQCpAKsAEQCsAKwACQCzALQACQDHAMcABADLAMsAAwACAC4A"
        "AQABABAACgAKAAcACwAMABEADQAOAAgAFwAXABIAHAAcAAIAHQAdABMAHgAeABQAHwAfAAkAIgAiAAIALAAsAAIALgAuAAMALwAv"
        "ABUAMAAwAAoANgA2AAoAOwA7ABYARABFABcARgBGABwATQBNABgATgBOAAEATwBPAA0AUABQAAQAUQBRABkAUgBTAAQAVwBXAAUA"
        "WQBZABoAWgBaAAYAWwBcAAEAaABoAAEAaQBpABsAagBqAA4AbABsAA8AbQBtAAUAcwBzAAUAdQB1ABkAgACAAAIAgQCBAAkAgwCD"
        "AAcAhgCGAAMAhwCHAAkAiACIAAcAiQCJAAIAmACYAAsAnACcAAsAqQCrAAwArACsAAsAAQCKAAQAAABADHwMZgxUDFQMLgwuCxAL"
        "Bgr4Cu4KzAquCqQLBgruCfoK7gngCaYJnAkeCNQIQgdQBvIGoAY2BgwGDAXeBaAFegVYBTYFMAU2BTYFHgT4BNYEiAV6BXoEUgQk"
        "A/oDgALGAigBjgUwARQK7gqkDGYLBgngCqQMZgruAQ4BDgEOCwYAAQBAAAEACgALAAwADQAOABQAFgAXABwAHQAeAB8AIAAiACoA"
        "LAAuAC8AMAA1ADYANwA4ADoAOwBDAEQARQBGAE0ATgBPAFAAUQBSAFMAVwBZAFoAWwBcAGgAaQBqAGwAbQByAHMAdAB1AHgAgACB"
        "AIMAhACGAIcAiACJAKkAqgCrAMcAAQA4/84AHgAK/+wAC//sAAz/7AAP/+wAFf/sACL/7AAp/+wALP/sAC//iAA4/5wAO//sAEL/"
        "7ABE/+IARf/sAEb/7ABH/+wASP/sAE7/4gBe/+wAZf/sAGj/7ABq/+IAbf/iAHL/7ABz/+wAeP/2AID/7ACB/4gAhv/sAMv/7AAm"
        "AAr/7AAL/+wADP/sAA//7AAV/+wAIv/sACn/7AAs/+wAL/+IADX/7AA4/5wAO//OAEL/zgBD/+wARP/OAEX/zgBG/+wAR//sAEj/"
        "zgBN/+wAT//iAFn/7ABa/+wAXv/OAGX/zgBn/+wAaP/OAGv/7ABs/+IAbf/sAHL/7ABz/+wAdf/sAHj/7ACA/+wAgf+IAIb/7ADL"
        "/+wAJwAK/+wAC//sAAz/7AAP/+wAFf/sACL/7AAp/+wALP/sAC//iAA1/+wAOP+cADv/4gBC/+IAQ//sAET/7ABF/+IARv/sAEf/"
        "7ABI/+IATf/2AE7/9gBP/+wAV//sAFn/9gBa//YAXv/iAGX/4gBn//YAaP/iAGn/7ABq//YAa//2AGz/4gBt/+IAeP/2AID/7ACB"
        "/4gAhv/sAMv/7AAuAAr/7AAL/+wADP/sAA//7AAV/+wAHP/YACL/7AAp/+wALP/sAC//ugA1/+wAOP+cADv/2ABC/9gAQ//iAET/"
        "4gBF/9gARv/YAEf/2ABI/9gATv/sAE//4gBQ/+wAUf/sAFP/7ABW/+wAV//YAFn/9gBa/+wAW//sAFz/7ABe/9gAZf/YAGj/2ABq"
        "/+wAbP/iAG3/7ABy/+wAc//sAHT/7AB1/+wAeP/sAID/7ACB/7oAhv/sAMv/7AAeAAr/7AAL/+wADP/sAA//7AAV/+wAIv/sACn/"
        "7AAs/+wANf/sADf/xAA4/5wAO//sAEL/7ABE//YARf/sAEb/7ABH/+wASP/sAE7/9gBP/+IAXv/sAGX/7ABo/+wAaf/2AGr/9gBt"
        "/+wAcv/sAID/7ACG/+wAy//sAAoANv/sADj/nABD/+wARP/sAE7/4gBX/+wAcv+6AHP/4gB0/+IAeP/sAAsANf/sADj/pgBD/+IA"
        "RP/sAE7/7ABp/+wAcv/sAHP/9gB0//YAdf/sAHj/7AANADX/4gA4/5wAQ//sAET/7ABO/+wAWf/sAFr/7ABp/+IAcv/sAHP/7AB0"
        "/+wAdf/sAHj/7AATADX/4gA4/5wAO//2AEL/9gBD/+wARP/2AEX/9gBG/+wAR//sAEj/9gBO/+wAT//sAFf/7ABZ/+wAWv/sAF7/"
        "9gBl//YAaP/2AHL/2AAIAET/4gBO/+wAWf/iAGn/9gBy/+IAc//sAHT/7AB1/+wACQBD//YARP/OAE7/9gBZ/+wAWv/sAGn/7ABy"
        "/+IAdf/sAHj/7AAEADj/nABO/+wAT//iAGn/7AABADj/nAAIADX/7AA4/+IAQ//2AET/7ABO/+wAV//sAHX/7AB4//YACAA1/+wA"
        "OP+cAET/4gBO/+wAcv/iAHP/7AB0/+IAdf/sAAkANf/iADj/nABD/+wARP/sAE7/7ABP/+wAV//sAFn/7ABy/9gADwA1/9gAOP+6"
        "AEP/4gBE/5wATv+cAE//4gBX/0IAWf/EAFr/zgBp/5IAcv+6AHP/zgB0/7AAdf+wAHj/xAALADj/7ABD/+wARP/sAE7/7ABP/+wA"
        "V//sAGn/7ABy/+IAdP/sAHX/7AB4/+wACgAc/+IANf/iADf/xAA4/5wATv/iAE//7ABZ/+wAcv/iAHT/4gB1/+IAGgAu/+wAL/+I"
        "ADX/4gA4/5wAO//sAEL/7ABE/+wARf/sAEj/7ABO/+wAUf/2AFr/7ABb//YAXP/2AF7/7ABl/+wAaP/sAGn/7ABq/+wAbP/OAHL/"
        "2ABz/+IAdP/iAHX/7ACB/4gAif/sABQAFP/OABz/xAAf/9gAKv/YADX/nAA2/+IAN//OADj/OABD/84ARP/OAE7/zgBP/+IAV//E"
        "AFn/2ABa/+IAcv+mAHP/4gB0/9gAdf+6AHj/4gAXAC//7AA1/+IAO//YAEL/2ABE/9gARf/YAEj/2ABR/+wAW//sAFz/7ABe/9gA"
        "Zf/YAGj/2ABp/+wAav/sAGz/2ABt/+wAcv/iAHP/7AB0/+wAdf/sAHj/7ACB/+wAPAAB/84ACf/OAAr/7AAL/+IADP/sAA//7AAV"
        "/+wAFv/sABf/7AAd/+IAHv/sAB//7AAi/+wAKf/sACr/4gAs/+wALf/iAC7/7AAw/+wANf/iADb/7AA3/+wAOv/sADv/ugBC/7oA"
        "RP+wAEX/ugBG/7AAR/+wAEj/ugBO/6YAUf/OAFf/YABZ/9gAW//OAFz/zgBe/7oAZf+6AGj/ugBq/5wAbP/OAG3/ugBy/7oAc/+6"
        "AHT/ugB1/84AeP/EAID/7ACG/+wAif/sAJj/zgCZ/84AnP/OAKn/zgCq/84Aq//OAKz/zgCz/84AtP/OAMv/7AAkAAH/2AAJ/9gA"
        "Cv/iAAv/2AAM/+IAD//iABX/4gAi/+IAKf/iACz/4gAu/+IAL//YADX/7AA7/7oAQv+6AET/xABF/7oASP+6AE7/4gBR/+wAW//s"
        "AFz/7ABe/7oAZf+6AGj/ugBp/+wAav/iAHP/7AB0/+wAdf/sAHj/7ACA/+IAgf/YAIb/4gCJ/+IAy//iABIAAf/sAAn/7AAf/+wA"
        "L//YADj/7AA7/+IAQv/iAET/7ABF/+IASP/iAE7/7ABe/+IAZf/iAGj/4gBs/+IAbf/sAHj/7ACB/9gAHwAB/+IACf/iAB//7AAu"
        "//YAL//sADv/2ABC/9gAQ//sAET/4gBF/9gARv/iAEf/4gBI/9gATv/iAFH/7ABZ/+wAW//sAFz/7ABe/9gAZf/YAGj/2ABp/+wA"
        "av/iAG3/7ABy//YAc//sAHT/7AB1/+wAeP/sAIH/7ACJ//YAAgAf/+wAOP/iAA4AC//iABb/4gAq/9gAMP/iADX/2AA3/8QAOP/Y"
        "AEP/7ABE/5wATv+cAGn/nABz/8QAdf+wAHj/zgAGADX/7AA3/9gAOP/iAEP/7ABE/+wATv/sACoAAf/iAAn/4gAv/+wANf/sADb/"
        "7AA3/9gAOP/iADv/4gBC/+IAQ//sAET/4gBF/+IARv/sAEf/7ABI/+IATf/sAE//7ABR/+wAWf/sAFr/7ABb/+wAXP/sAF7/4gBl"
        "/+IAZ//sAGj/4gBp/+IAav/iAGv/7ABs/+wAbf/sAHL/4gBz/+wAdf/sAHj/7ACB/+wAmP/OAJn/zgCc/84ArP/OALP/zgC0/84A"
        "AgA3/+wAOP/iAAcAC//iADf/zgA4/4gARP/sAE//2ABy/5wAdP/YAAgAC//iADX/7AA4/+IARP/OAE7/2ABy/9gAdf/iAHj/4gAC"
        "ADf/4gA4/+wAAwAL/+wARP/OAGn/4gACADj/7ABO/+IARwAB/8QACf/EAAr/7AAL/+wADP/sAA3/7AAO/+wAD//sABT/7AAV/+wA"
        "Fv/sABf/4gAc/6YAHf/YAB7/7AAf/+IAIP/sACL/7AAp/+wAKv/iACv/7AAs/+wALf/YAC7/9gAw/+wANf/sADb/7AA3/9gAOP/i"
        "ADr/7AA7/5wAQv+cAEP/4gBE/5wARf+cAEb/nABH/5wASP+cAE3/2ABO/5IAT//iAFH/zgBX/zgAWf/iAFr/2ABb/84AXP/OAF7/"
        "nABl/5wAZ//YAGj/nABp/5wAav+cAGv/2ABt/8QAcv+6AHP/sAB0/6YAdf+mAHj/pgCA/+wAhv/sAIn/9gCY/6YAmf+mAJz/pgCs"
        "/6YAs/+mALT/pgDH/+wAy//sAAkAHP/sAB//7AA1/+wAN//OADj/xABy/+IAdP/iAHX/7AB4/+wABAA1/+wAN//iADj/4gB0/+IA"
        "BQA1/+wAN//YADj/2ABO/+wAcv/iAAoAC//2ADX/7AA3/9gAOP/OAFn/7ABy/+wAc//sAHT/7AB1/+wAeP/sAAEAAAAKAIQA1AAC"
        "REZMVABqbGF0bgAOAFAACEFaRSAAQkNBVCAANENSVCAAQktBWiAAQk1PTCAAYFJPTSAAYFRBVCAAQlRSSyAAQgAA//8ABAAAAAIA"
        "AwAFAAD//wAEAAAAAgADAAQAAP//AAMAAQACAAMABAAAAAD//wADAAAAAgADAAZjY21wAEhjY21wAD5mcmFjADhsaWdhADJsb2Ns"
        "ACxsb2NsACYAAAABAAQAAAABAAMAAAABAAgAAAABAAcAAAADAAAAAgACAAAAAgAAAAIACQGGAXYBTgE6AP4A8ADiAFgAFAAEAAgA"
        "AQAIAAEANgABAAgABQAmAB4AGAASAAwAfQACAFoAfAACAFAAeQACAE0AewADAE0AWgB6AAMATQBQAAEAAQBNAAQAAAABAAgAAQB0"
        "AAUASgA+ACgAHAAQAAEABACSAAMApQCIAAEABACRAAMApQCIAAIADgAGAI4AAwClAIQAkAADAKUAiAABAAQAjAADAKUAgwAEACIA"
        "GgASAAoAigADAKUAggCLAAMApQCDAI0AAwClAIQAjwADAKUAiAABAAUAgQCCAIMAhQCHAAEAAAABAAgAAQAkAAcAAQAAAAEACAAB"
        "ABYABgAGAAAAAQAIAAEACAABAA4AAQABAKEAAgAWAAYAAQAeAAEAAQAeAAEAAAAGAAEAWgABAAEAWgABAAAABQABAAAAAQAIAAEA"
        "BgAFAAEAAQBQAAIAEAABAAoAAAABAAoAAgAYABIAAQACAHwAfQACAE0AWgACAE0AUAABABAAAQAKAAAAAQBeAAEABgAQAAEACgAA"
        "AAIATgBKADoAJAADAAAAEgASAAEABAAAAAEAAQABAAEAAAABAAIAAwDcANwAAQDeAN8AAQDjAOQAAQACAAIAUABQAAIAVwBXAAEA"
        "AgAAAAEAAgBQAFcAAAABAAEACAABAAAAFAABAAAAHAACd2dodAEAAAAAAgADAAAAAgEBAZAAAAK8AAAAAA=="),
    "PixelifySans-Bold-v3.ttf": (   # C, G and c opened up so they no longer read as O / o
        "AAEAAAAPAIAAAwBwR0RFRghxDPUAAEFQAAAAjEdQT1PuCw+yAABB3AAAFyZHU1VCr/Ww4QAAWQQAAAK6T1MvMmKDHVYAAAF4AAAA"
        "YFNUQVR5k2tJAABbwAAAACpjbWFwBGkDWwAABYgAAAJqZ2FzcAAAABAAAEFIAAAACGdseWZFzts3AAAJ1AAAMhhoZWFkK2smsAAA"
        "APwAAAA2aGhlYQe2AwMAAAE0AAAAJGhtdHjzvTVlAAAB2AAAA65sb2NhmaeM+gAAB/QAAAHebWF4cAD7AHYAAAFYAAAAIG5hbWUt"
        "7lFwAAA77AAAAi5wb3N0LroCFAAAPhwAAAMsAAEAAAABAAA/ILhKXw889QADA+gAAAAA4R9yMAAAAADnGHD+/+r/QwQxA1wAAQAG"
        "AAIAAAAAAAAAAQAAA5j+6AAABG7/6v7DBDEAAQAAAAAAAAAAAAAAAAAAAOkAAQAAAO4AUAAGACQABAABAAAAAAAAAAAAAAAAAAIA"
        "AQAEAksCvAAFAAACvAKKAAAAjAK8AooAAAHdADIA+gAAAAAAAAAAAAAAAIAAAGcAAABKAAAAAAAAAABOT05FAKAAICIVA5j+6AAA"
        "A5oBISAAAJ8AAAAAAdMCvAAAACAAAwLXAGQCWwA9AlsAPQJbAD0CWwA9AlsAPQJbAD0CWwA9AlsAPQO8AD0CWwA9AlsAPQJbAD0C"
        "WwA9AlsAFwJbAD0CWwA9AlsAPQJbAD0CWwA9AlsAPQJbAD0CWwA9AaoAPQGqAD0BqgA9AaoAMgGqAD0CWwA9AlsAPQJbAD0DCwA9"
        "AlsAPQJbAD0CWwA9AlsAPQJbAD0CWwA9AlsAPQJbAB4CWwA9A7wAPQJbAD0CWwA9AlsAPQJbAD0CWwA9AlsAPQJbAD0CWwA9AlsA"
        "PQJbAD0CWwA9AlsAPQMLAD0CWwA9AlsAPQJbAD0CWwA9ArQAPQK0AD0CtAA9ArQAPQK0AD0CtAA9ArQAPQRuAD0CWwA9AlsAPQJb"
        "AD0CWwA9Al0APQJbAD0CWwA9AlsAPQJbAD0CWwA9AlsAPQJbAD0CWwA9APkAPQD5AD0A+QAmAPkAKAD5/+oA+QA9APn//AIDAD0C"
        "AwA9AlsAPQD5AD0DCwA9AlsAPQJbAD0CWwA9AlsAPQJbAD0CWwA9AlsAPQJbACYCWwA9A7wAPQJbAD0CWwA9AlsAPQJbAD0CWwA9"
        "AlsAPQK0AD0CWwA9AlsAPQJbAD0CWwA9AlsAPQJRADIDCwA9AlsAPQJbAD0CWwA9AlsAPQJbAD0DvAA9A7wAPQO8AD0CWwA9AlsA"
        "PQGZAD4BbAA+AlsAPQGqAD0CWwA9AlsAPQJbAD0CWwA9AlsAPQJbAD0CWwA9AlsAPQM9ADwDtAA8A6gAPAN2AD0D1QA8A6sAPAPv"
        "ADwEAwA8A+UAPQEpAD0BngA8AZ4APADIAAAAyAAAAPkAPQElAD0A+QA9ASUAPQKTAD0A+QA9APkAPQJbAD0CWwA9APkAPQEcAD0B"
        "JQA9ArQAPQIkADkCJAA5APkAPQD6AD0BbwAcAakAPQIKAD0BzwA9AYwAPQGMAB8B5AAfAeQAHwGMAD0BjAAfASUAPQHmAD0B5gA9"
        "AeYAPQElAD0BJQA9A3EAHwNdAAoCPQA9Aj0AHwHmAD0BJQA9AqEAUAK0AD0DCgA9AlsAPQHKAEYBygBGAyEAPQFSAD0A+QA9AlsA"
        "PQJCADwCWwA9AlsAPQKzAD0CcgA8AiQAPQJYADwCWABlAlgATAJYAGUCWABlAlgAPAJYADwCWABlAlgApgJYAGUBJQA9AlsAPQNs"
        "AD0AAP/vAAAAVgAAADwAAABBAAAAQAAAABIAAABYAAAADwAA//4AAP//ASz/8QEjADwBLAA8AEAAVgAP//4AFgAAAAAAAgAAAAMA"
        "AAAUAAMAAQAAABQABAJWAAAANAAgAAQAFAAvADkAfgClAKwA/wECATEBUwLGAtoC3AMBAwQDCCAUIBogHiAiICYgOiCsISIiEiIV"
        "//8AAAAgADAAOgCgAKcArgECATEBUgLGAtoC3AMAAwMDCCATIBggHCAiICYgOSCsISIiEiIV//8AAABQAAAAAAAAAAD/Af8gAAD+"
        "I/4Q/g/93v3g/dTglwAAAADggOB24ILgH9+j3r7euQABADQAAABQANgA4gDsAAAAAAGKAAAAAAAAAAAAAAAAAAABfgGCAAAAAAAA"
        "AAAAAAAAAAAAAACWAJ0AvQCkAMoA2wDAAL4ArQCuAKMAzwCZAKkAmAClAJoAmwDVANMA1ACfAL8AAQAKAAsADQAPABQAFQAWABcA"
        "HAAdAB4AHwAgACIAKgAsAC0ALgAvADAANQA2ADcAOAA6ALEApgCyANkArADnADsAQwBEAEYASABNAE4ATwBQAFcAWQBaAFsAXABe"
        "AGYAaABpAGoAbABtAHIAcwB0AHUAeACvAMcAsADXAJcAngDIAMwAyQDNAMIA5gDDAH4AuQDYAMQA7ADGANYAlACVAOgA2gDBAKEA"
        "7QCTAH8AugCNAIoAjgCgAAYAAgAEAAgABQAHAAkADAATABAAEQASABsAGAAZABoADgAhACYAIwAkACgAJQDRACcANAAxADIAMwA5"
        "ACsAawA/ADwAPQBBAD4AQABCAEUATABJAEoASwBWAFIAUwBUAEcAXQBiAF8AYABkAGEA0gBjAHEAbgBvAHAAdgBnAHcAKQBlALcA"
        "uACzALUAtgC0AAAAAAAVADcAQwBPAFsAZwBzAH8AiwC+AOEA/gErAUoBcQGSAZ4BqgG2AcIB2QH8AhcCLAI4AkQCUAJcAnYCowK4"
        "At8C/gMKAyYDMgM+A0oDVgN+A4oDugPVA/AEFQQ4BF0EdgSMBJgEpASwBLwE2gUABSwFSQVVBXYFlQWhBa0FuQXEBdAF3AYVBjAG"
        "TQZ6BpUGvwbgBuwG+AcEBw8HKAdMB2YHeQeGB5EHnAenB7IHvQfSB+cICAgVCDIIRghSCG0IeQiFCJEInAjBCM0I/QkYCTMJUAll"
        "CYMJogm/CdUJ4QntCfkKBAogCj0KaQqHCpMKnwq8CuMLDQs1C1ILbAuQC68LywvgDAUMKgxKDHIMlQyrDNIM9g0/DYgN4Q4jDnUO"
        "wQ8dD30Pww/YD/wQIBAgECAQKxA9EE4QZRB8EI4QoRDBEOEQ7RD5EQ0RNhFFEVQRXxFqEXYRghGOEZoRthHSEfgSHhIzEkgSWhJ4"
        "EpYStBLGEtgTKhN8E6gT1BPyFAQURhSCFJ4UwhTxFRgVURVrFXgVnBXNFfoWHxZAFmwWiBacFqgWwRbZFuwXGBdEF14XcheBF5UX"
        "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"
        "VYh5h3gAAgA9//UCHgJ+ABMAFwAAFzUjNTMVMzUhNSM1MzUhFTMRIxUBMzUjlVh/4v73WFgBMFlZ/vfi4gtViVZ5Vd1WVv4iVQGI"
        "eAAAAwA8//MDBwJ7ABMAHwA7AAAXNTM1MzUzNTM1MxUjFSMVIxUjFQMRIxUjNTM1MxUzEQE1IzUzNTM1IxUjNTM1MxUzFSMVIxUz"
        "NTMVIxWmTk5OUHVOT05PgwdVLlUvATsuLopjVS6xLS2KY1QtDLqZTZpNuk6ZTZkBKwEOLU0uLv7S/tQsrC45Lk4uLnoual5/LAAD"
        "ADz/8wN4AnsAEwAfADsAABc1MzUzNTM1MzUzFSMVIxUjFSMVAxEjFSM1MzUzFTMRATUjNTMVMzUjNTM1IxUjNTM1MxUzFSMVMxUj"
        "FddOT01QdU1QTk+0B1UuVS8Bqy9XYIiIYFcvrzAwMDAMuplNmk26TplNmQErAQ4tTS4u/tL+1C1OLWpOOC1OLi56DKwtAAMAPP/z"
        "A5UCqQATAC8ASwAABTUzNTM1MzUzNTMVIxUjFSMVIxUBNSM1MzUzNSMVIzUzNTMVMxUjFSMVMzUzFSMVATUjNTMVMzUjNTM1IxUj"
        "NTM1MxUzFSMVMxUjFQEHT05PTndPT09O/u0uLopjVS6xLi6KY1UuAZwwV2GIiGFXMK8vLy8vDLqZTZpNuk6ZTZkBKSysLjkuTyws"
        "ey5qLk8s/tYtTi1qTjgtTi4uegysLQAEAD3/9AM5An4AEwAfACsAMQAAFzUzNTM1MzUzNTMVIxUjFSMVIxUFNSM1MzUzNTM1MxEB"
        "ESMVIzUzNTMVMxEFMzUjFSPVTU5NT3NNTk1OAZu1Li0tgv1eB1MsVS4BxTMGLQvIlUuWS8hMlUuVAViLKyws/poBJAEHLF4tLf7H"
        "blItAAAEADz/8wOQAnsAEwAvADsAQwAABTUzNTM1MzUzNTMVIxUjFSMVIxUlNSM1MxUzNSM1MzUjFSM1MzUzFTMVIxUzFSMVBTUj"
        "NTM1MzUzNTMRJzM1IxUjFSMBJU9NT092T05PTv7QL1ZhiIhhVi+vLy8vLwIiuS8tLoO4ZAcvLgy6mU2aTbpOmU2Z+i5NLDlNaSxN"
        "Li6rC3su+1p7LSwu/qSoZi0tAAUAPP/zA28CewATAB8AMwA3ADsAABc1MzUzNTM1MzUzFSMVIxUjFSMVAxEjFSM1MzUzFTMRATUj"
        "NTM1IzUzNTMVMxUjFTMVIxUnMzUjNTM1I9dOT01QdU1QTk+0B1UuVS8BoC4uLi6yLy8vL4piYmJiDLqZTZpNuk6ZTZkBKwEOLU0u"
        "Lv7S/tQtogx7Li57DKItTmBOOgAABQA8//MDswJ7ABMALwAzAEcASwAABTUzNTM1MzUzNTMVIxUjFSMVIxUlNSM1MxUzNSM1MzUj"
        "FSM1MzUzFTMVIxUzFSMVBTM1Iwc1IzUzNSM1MzUzFTMVIxUzFSMVAzM1IwEbT05OT3ZOT09O/tovVmGIiGFWL68vLy8vAeFiYigu"
        "Li4usi4uLi6KYmIMuplNmk26TplNmfouTSw5TWksTS4uqwt7Lq1quC2sDHstLXsMrC0BBjoAAAUAPP/zA8cCewATADMANwBLAE8A"
        "AAU1MzUzNTM1MzUzFSMVIxUjFSMVATUjNTMVMzUjNSM1IzUzNTMVMxUjNSMVMxUzFTMVIxUFMzUjBzUjNTM1IzUzNTMVMxUjFTMV"
        "IxUDMzUjATlNT05QdU5QTU/+vC5VY1wuLi6xL1ZjLlwvLwHyZGQnLS0tLbEwMDAwimRkDLqZTZpNuk6ZTZkBAy1OLQwuLKIuLqKC"
        "YSwuTi22argtrAx7LS17DKwtAQY6AAUAPf/0A6gCfgATAB8AKwAvADMAAAU1MzUzNTM1MzUzFSMVIxUjFSMVBTUjETM1MxUzESMV"
        "AREjFSM1MzUzFTMRBTM1IzUzNSMBSU1OTU50TU9MTgENLS2vLy/9eWJTLLAuAaphYWFhC8iVS5ZLyEyVS5UBLAEPLCz+8SwBIwEI"
        "LF4tLf7GxCVfJQAAAQA9ARgA7AJ+AAsAABMRIxUjNTM1MxUzEZcHUyxVLgEYAQcsXi0t/scAAQA8AOwBSQJ5ABsAADc1IzUzNTM1"
        "IxUjNTM1MxUzFSMVIxUzNTMVIxVqLi6KY1UusS4uimNVLuwtey1qLU4tLasuOS1OLQAAAQA8AO4BSQJ7ABsAADc1IzUzFTM1IzUz"
        "NSMVIzUzNTMVMxUjFTMVIxVrL1ZhiIhhVi+vLy8vL+4uTSw5TWksTS4uqwt7LgAAAQA9AAAAvACJAAMAADM1MxU9f4mJAAEAPf+r"
        "AOgAiQAJAAAXNSM1MxUzFSMVaSx/LCxVVYlWXCwAAAIAPQBNALwBfQADAAcAADc1MxUnNTMVPX9/f02JiaiIiAACAD3/+ADoAX0A"
        "CQANAAAXNSM1MxUzFSMVJzUzFWksfywsf38IVYlWXSv9iIgAAwA9AAACVQCJAAMABwALAAAhNTMVITUzFSE1MxUBCYD+tH8BGn+J"
        "iYmJiYkAAAIAPf/1ALwCfgADAAcAADcRMxEHNTMVPX9/f6AB3v4iq4iIAAIAPf/1ALwCfgADAAcAABcRMxEDNTMVPX9/fwsB3v4i"
        "AgGIiAAAAgA9//UCHgJ+ABEAFQAANzUzNSMVIzUzNSEVMxUjFSMVBzUzFe2x4n9YATBZWViAgKDdeKrdVlbdVVariIgAAAIAPf/1"
        "Ah4CfgARABUAABc1IzUzNTM1MxUjFTM1MxUjFQM1MxWVWFhYgLHigFnYgAtW3lRW3Xir3lYCAYiIAAABAD0A/AC8AYQAAwAANzUz"
        "FT1//IiIAAABAD0A6wDfAZUAAwAANzUzFT2i66qqAAABAD0BoADoAn4ACwAAEzUzNTMVMxUjNSMVPSxTLFMGAaCyLCyyKysAAgA9"
        "//UCdwJ+ABsAHwAAFzUjNTM1IzUzNTMVMzUzFTMVIxUzFSMVIzUjFTUzNSOVWFhYWH+KgFlZWVmAioqKC1WJeIirq6uriHiJVVVV"
        "3ngAAAEAOf/0AesCdwADAAAXATMBOQE+dP7CDAKD/X0AAAEAOf/0AesCdwADAAAFATMBAXf+wnQBPgwCg/19AAEAPQAAALwAiQAD"
        "AAAzNTMVPX+JiQABAD0AAAC8AIkAAwAAMzUzFT1/iYkAAQAcALYBTAE/AAMAADc1IRUcATC2iYkAAQA9AOQBbAFtAAMAADc1IRU9"
        "AS/kiYkAAQA9AOQBzAFtAAMAADc1IRU9AY/kiYkAAQA9AAABkwCJAAMAADM1IRU9AVaJiQAAAQA9/2kBbQL1ABMAABc1IzUjNTM1"
        "MzUzFSMVIxUzFTMV7VhYWFiAWVhYWZeuqt6sqt2seK3eAAABAB//aQFPAvUAEwAAFzUzNTM1IzUjNTMVMxUzFSMVIxUfWFlZWH9Y"
        "WVhZl96teKzdqqzeqq4AAAEAH/+bAaYC0AAbAAAXNSMRIzUzETM1MxUzFSM1IxEjFTMRMzUzFSMV0FhZWFl/V34yWFgyfldlVgEB"
        "hwEBVlaIVf8AIv7/VolWAAABAB//mwGmAtAAGwAAFzUjNTMVMxEzNSMRIxUjNTM1MxUzETMVIxEjFXZXfjNXVzN+V4BYWFhYZVaJ"
        "VgEBIgEAVYhWVv7/h/7/VgAAAQA9/8cBbQKlAAsAABc1IxEzNTMVIxEzFZVYWNixsTlWAjNViP4ziQAAAQAf/8cBTwKlAAsAABc1"
        "MxEjNTMVMxEjFR+xsddZWTmJAc2IVf3NVgAAAQA9/6sA6ACJAAkAABc1IzUzFTMVIxVpLH8sLFVViVZcLAAAAgA9/6sBqACJAAkA"
        "EwAABTUjNTMVMxUjFSE1IzUzFTMVIxUBKi2BKir+6yx/LCxVVYlWXCxViVZcLAAAAgA9AaABqAJ+AAkAEwAAATUjNTM1MxUzFSE1"
        "IzUzNTMVMxUBKSwsVCv+wCsrUy0BoFZcLFWJVlwsVYkAAgA9AaABqAJ+AAkAEwAAATUjNTMVMxUjFSE1IzUzFTMVIxUBKi2BKir+"
        "6yx/LCwBoFWJVl0rVYlWXSsAAQA9AaAA6AJ+AAkAABM1IzUzNTMVMxVoKytTLQGgVlwsVYkAAQA9AaAA6AJ+AAkAABM1IzUzFTMV"
        "IxVpLH8sLAGgVYlWXSsAAgAf/5sDNQLQACMARwAABTUjNSM1IzUjNTM1MzUzNTM1MxUjFSMVIxUjFTMVMxUzFTMVITUjNSM1IzUj"
        "NTM1MzUzNTM1MxUjFSMVIxUjFTMVMxUzFTMVArVYWFlYWFlYWIBZWFhZWVhYWf5MWVhZWFhZWFl/WldZWFhZV1plVlZVVodWVlVW"
        "iVVWVSJWVVaJVlZVVodWVlVWiVVWVSJWVVaJAAACAAr/mwMhAtAAIwBHAAAFNTM1MzUzNTM1IzUjNSM1IzUzFTMVMxUzFTMVIxUj"
        "FSMVIxUhNTM1MzUzNTM1IzUjNSM1IzUzFTMVMxUzFTMVIxUjFSMVIxUBP1lYWVhYWVhZgFhZWFlZWFlY/ktZWFlYWFlYWYBYWFlY"
        "WFlYWGWJVlVWIlVWVYlWVVZWh1ZVVlaJVlVWIlVWVYlWVVZWh1ZVVlYAAAEAPf+bAh4C0AAjAAAFNSM1IzUjNSM1MzUzNTM1MzUz"
        "FSMVIxUjFSMVMxUzFTMVMxUBnlhZWFhYWFlYgFlYWVhYWVhZZVZWVVaHVlZVVolVVlUiVlVWiQABAB//mwIAAtAAIwAAFzUzNTM1"
        "MzUzNSM1IzUjNSM1MxUzFTMVMxUzFSMVIxUjFSMVH1hZWFlZWFlYf1hZV1paV1lYZYlWVVYiVVZViVZVVlaHVlVWVgAAAgA9AaAB"
        "qAJ+AAkAEwAAATUjNTMVMxUjFSE1IzUzFTMVIxUBKi2BKir+6yx/LCwBoFWJVl0rVYlWXSsAAQA9AaAA6AJ+AAkAABM1IzUzFTMV"
        "IxVpLH8sLAGgVYlWXSsAAgBQAE8CGgHUADMANwAANzUjNSM1MzUzNSEVMxUzFTMVIxUjFSM1IxUjNSM1MzUzFTMVMzUzNSM1IzUj"
        "FSMVMxUzFSczNSOWLRkZLQEHGS03LRpaFZIWFqYUIC0jLekQLbR4V1dPLRj8KxkZKyx5LBgSEhKNExNtMzcsLCzOKyeKTAAAAwA9"
        "//UCdwJ+AB8AJwAvAAAXNSM1MzUzNSM1IzUzNSEVMxUjFSMVMxUzFTMVIzUjFSUzNSM1IxUjNzM1MzUjFTOVWFhYWFhYATBZWVhY"
        "WVmAMv734lgyWFgyWOJYC1WJViJViFZWiFUiVlaIVVWII1ZW3VYiIgAAAQA9/0oCzQJ+AA8AAAURITUjETM1IRUjESMRIxEBnv73"
        "WFgCODFPYLYBWFUBMVaJ/VUCq/1VAAABAD3/9QIeAn4AGQAAFzUjNTM1IzUzNSEVMxUjNSMVIRUzFSEVIRWVWFhYWAEwWYDiAQlZ"
        "/p4BYgtV3yLdVlaIVXhUiSOIAAADAEYBdAFsAlQACwAPACMAABM1IzUzNTMVMxUjFSczNSMXNSM1MzUzFTMVIzUjFTM1MxUjFXMt"
        "LcsuLsK5uTIICFoHJCAgJAcBdA/CDw/CDzCAcgdTCQknBhEIKQcAAwBGAWgBhQJZAAsADwAbAAATNSM1MzUzFTMVIxUnMzUjFzUz"
        "NTMVMxUjNSMVcy0t5S0tv5mZJAxXDCsOAWgP0w8P0w9GZV4zHxUkDCUAAgA9ARkC4wJ+ABsAKwAAAREzNTMVMxUzNTM1MxUzESMR"
        "IxUjFSM1IzUjESERIxUjNTM1MxUzFSM1IxEBgS1ULQYtVitSCC1ULQb+wgdTLLAsUwcBGQE4LS1VVS0t/sgBBlaEhFb++gEGLF4t"
        "LV4s/voAAgA9AXMBFQJRAAsADwAAEzUjNTM1MxUzFSMVJzM1I2AjI5IjI2tERAFzIpoiIpoiVTQAAAEAPf/1ALwCfgADAAAXETMR"
        "PX8LAon9dwAAAQA9AAACHgKYABsAADM1IzUjETM1MzUzFTMVMxUjNSMVMzUzFSMVIxXqVVhYVYdUWYDi4oBZVF1VATNWXV1WiFXN"
        "VYhVXQAABgA8AIcCBQHhAAsADwATABcAGwAfAAA3NSM1MzUzFTMVIxUFNTMVAzUzFRczNSMXNTMVAzUzFcgtLbEtLf7DVVVVX2Fh"
        "wFVVVbQspy0tpywtTk4BDE5OkmXfTk4BDE5OAAABAD3/nwIeAtQAIwAAFzUjNSM1MxUzNSE1IzUzNTM1MxUzFTMVIzUjFSEVMxUj"
        "FSMV9mFYf+L+91hYYYBPWYDiAQlZWU9hVlWJVnlV3VZWVlaIVXhU31VWAAABAD3/9QIeAn4AGwAAFzUjETM1IRUzFSM1IxUzFSMV"
        "MxUjFTM1MxUjFZVYWAEwWYDisrKysuKAWQtVAd5WVt2qN4kFiCus31UAAAEAPf/1AnYCfgAXAAAXNTMRMzUhFTMVIzUjFTMVIxUz"
        "NTMVIxU9WFgBMVh/47Gx439YC4gBq1ZWiFV4h3lWiVUAAAEAPP/0AiQCewAjAAAXNSM1MzUjNTM1IzUjNTMVMxUzNTM1MxUjFSMV"
        "MxUjFTMVIxXvWVlZWVlagVkzWYJbWFhYWFgMRlEyUkRX0bBYWLDRV0RSMlFGAAABAD3/9QHnAn4AEwAAFzUzNTM1MzUzNTMVIxUj"
        "FSMVIxU9TU1NT3RNT01OC8iVS5ZLyEyVS5UAAAEAPABSAh0CMAALAAA3NSM1MzUzFTMVIxXssLCAsbFSoYi1tYihAAABAGUA8gH0"
        "AXsAAwAANzUhFWUBj/KJiQABAEwAZQIMAhYACwAANyc3JzcXNxcHFwcnsl99hF+FfV98dWB1ZV14f12AeVx5cVxxAAMAZQBFAfQC"
        "JwADAAcACwAANzUhFQU1MxUDNTMVZQGP/viAgIDyiYmtiYkBWoiIAAIAZQBdAfQBsAADAAcAABM1IRUFNSEVZQGP/nEBjwEniYnK"
        "iYkAAQA8/5sCHQLQACMAABc1MzUzNTM1MzUjNSM1IzUjNTMVMxUzFTMVMxUjFSMVIxUjFTxYWVhZWVhZWH9YWVdaWldZWGWJVlVW"
        "IlVWVYlWVVZWh1ZVVlYAAAEAPP+bAh0C0AAjAAAFNSM1IzUjNSM1MzUzNTM1MzUzFSMVIxUjFSMVMxUzFTMVMxUBnVhZWFhYWFlY"
        "gFlYWVhYWVhZZVZWVVaHVlZVVolVVlUiVlVWiQACAGX/+QH0AesACwAPAAA3NSM1MzUzFTMVIxUFNSEV7IeHgIiI/vkBj5tudG5u"
        "dG6idXUAAQCmALoBswFFAAsAADc1MxUzNTMVIzUjFaauDVKvDbqLKyuLLS0AAAEAZQDRAfQBsAAFAAAlNSE1IRUBdf7wAY/RVonf"
        "AAEAPQH1AOgCfgALAAATNTM1MxUzFSM1IxU9LFMsUwYB9V0sLF0rKwABAD3/TwIeAdMACwAAFxEzETMRMxEjFSEVPX/igFn+97EC"
        "hP6qAVb+d1WmAAMAPf/1Ay8CfgAbACcAMwAAFzUzNTM1MzUzNTM1MzUzFSMVIxUjFSMVIxUjFQM1IzUzNTMVMxUjFQE1IzUzNTMV"
        "MxUjFWxaV1pXWVl/WFlZV1pXWFhYf1lZAUNYWIBYWAuIVlZUVlVWiVVVVVZWVQFWVYhWVohV/qpViVZWiVUAAv/vAfgBPQKBAAMA"
        "BwAAAzUzFTM1MxURgE9/AfiJiYmJAAEAVgH/ANYCiAADAAATNTMVVoAB/4mJAAEAPAH+AOcCsQALAAATNSM1IzUzFTMVMxWULCxS"
        "LSwB/iorXiwqXQABAEEB/gDsArEACwAAEzUzNTM1MxUjFSMVQSwtUiwsAf5dKixeKyoAAQBAAf4A6wKHAAsAABM1MzUzFTMVIzUj"
        "FUAsUyxTBgH+XSwsXSsrAAEAEgH+ARsChwAHAAATNTMVMzUzFRJSZlEB/okrK4kAAgBYAf8A1QKIAAMABwAAEzUzFSczNSNYfVw7"
        "OwH/iYkhRwAAAQAPAf4BHAKJAAsAABM1MxUzNTMVIzUjFQ+xB1WyBwH+iysriy0tAAH//gH+AS4ChwADAAADNSEVAgEwAf6JiQAA"
        "Av//AfgBJQKBAAMABwAAAzUzFTM1MxUBgCd/AfiJiYmJAAL/8QH4AT8CgQADAAcAAAM1MxUzNTMVD4BPfwH4iYmJif//ADwB/gDn"
        "ArEABgDeAAAAAQA8Af4A5wKxAAsAABM1MzUzNTMVIxUjFTwsLVIsLAH+XSosXisq//8AQAH+AOsChwAGAOAAAAACAFYB/wDTAogA"
        "AwAHAAATNTMVJzM1I1Z9XDs7Af+JiSFHAP//AA8B/gEcAokABgDjAAAAAf/+AkgBLgLRAAMAAAM1IRUCATACSImJAAABABb/QwEZ"
        "ABUADwAAFzUjNTMVMzUjNTMVMxUjFUIsUzEsfywsvStdKiJSSl0rAAAAAAoAfgADAAEECQAAALQA/AADAAEECQABABoA4gADAAEE"
        "CQACAAgA2gADAAEECQADADgAogADAAEECQAEACQAfgADAAEECQAFABoAZAADAAEECQAGACIAQgADAAEECQAOADYADAADAAEECQEA"
        "AAwAAAADAAEECQEEAAgA2gBXAGUAaQBnAGgAdABoAHQAdABwAHMAOgAvAC8AcwBjAHIAaQBwAHQAcwAuAHMAaQBsAC4AbwByAGcA"
        "LwBPAEYATABQAGkAeABlAGwAaQBmAHkAUwBhAG4AcwAtAEIAbwBsAGQAVgBlAHIAcwBpAG8AbgAgADEALgAwADAAMABQAGkAeABl"
        "AGwAaQBmAHkAIABTAGEAbgBzACAAQgBvAGwAZAAxAC4AMAAwADAAOwBOAE8ATgBFADsAUABpAHgAZQBsAGkAZgB5AFMAYQBuAHMA"
        "LQBCAG8AbABkAEIAbwBsAGQAUABpAHgAZQBsAGkAZgB5ACAAUwBhAG4AcwBDAG8AcAB5AHIAaQBnAGgAdAAgADIAMAAyADEAIABU"
        "AGgAZQAgAFAAaQB4AGUAbABpAGYAeQAgAFMAYQBuAHMAIABQAHIAbwBqAGUAYwB0ACAAQQB1AHQAaABvAHIAcwAgACgAaAB0AHQA"
        "cABzADoALwAvAGcAaQB0AGgAdQBiAC4AYwBvAG0ALwBlAGkAZgBlAHQAeAAvAFAAaQB4AGUAbABpAGYAeQAtAFMAYQBuAHMAKQAA"
        "AAIAAAAAAAD/tQAyAAAAAAAAAAAAAAAAAAAAAAAAAAAA7gAAACQAyQECAMcAYgCtAGMArgCQACUAJgBkACcA6QAoAGUAyADKAMsA"
        "KQAqACsALADMAM0AzgDPAC0ALgAvADAAMQBmADIA0ADRAGcA0wCRAK8AsAAzAO0ANAA1ADYANwA4ANQA1QBoANYAOQA6ADsAPADr"
        "AD0ARABpAGsAbABqAG4AbQCgAEUARgBvAEcA6gBIAHAAcgBzAHEASQBKAEsATADXAHQAdgB3AQMAdQBNAQQATgBPAFAAUQB4AFIA"
        "eQB7AHwAegChAH0AsQBTAO4AVABVAFYAiQBXAFgAfgCAAIEAfwBZAFoAWwBcAOwAugBdAQUBBgEHAMAAwQCdAJ4AEwAUABUAFgAX"
        "ABgAGQAaABsAHAD0AQgBCQD1APYBCgELAQwBDQEOAQ8BEAADAREAEQAPAB0AHgCrAAQAowAiAKIAwwCHAA0ABgASAD8BEgETABAA"
        "sgCzAEIACwAMAF4AYAA+AEAAxADFALQAtQC2ALcAqQCqAL4AvwAFAAoAIwAJAIgAhgCLAIoAjACDAF8AhAC9AAcBFACFAJYBFQAO"
        "AO8A8AC4ACAAIQAfAJMAYQCkAEEBFgAIARcBGAEZARoBGwEcAR0BHgEfASAAjgBDAI0A2ADdANkA2gDeBkFicmV2ZQlpLmxvY2xU"
        "UksHdW5pMDIzNwNmX2YFZl9mX2kFZl9mX2wHdW5pMjE1Mwd1bmkyMTU0CW9uZWVpZ2h0aAx0aHJlZWVpZ2h0aHMLZml2ZWVpZ2h0"
        "aHMMc2V2ZW5laWdodGhzB3VuaTAwQjkHdW5pMDBCMgd1bmkwMEIzB3VuaTAwQTAWcGVyaW9kY2VudGVyZWQubG9jbENBVBtwZXJp"
        "b2RjZW50ZXJlZC5sb2NsQ0FULmNhc2UERXVybwd1bmkyMjE1B3VuaTAwQjUHdW5pMDMwOAd1bmkwMzA3CWdyYXZlY29tYglhY3V0"
        "ZWNvbWIHdW5pMDMwMgd1bmkwMzA2B3VuaTAzMEEJdGlsZGVjb21iB3VuaTAzMDQOdW5pMDMwOC5uYXJyb3cAAQAB//8ADwABAAIA"
        "RAAAAA4AAAByAA4ABQAuACAAIAAYABgAAgABAHkAfQAAAAEABAABAS4AAgAKAAYAAQJ9AAEBPwABAAQAAQHeAAIABwABAA0AAQAP"
        "AFYAAQBYAHgAAQB5AH0AAgDcANwAAwDeAN8AAwDjAOQAAwABAAIAAAAMAAAADAABAAUA3ADeAN8A4wDkAAEAAAAKACgATgACREZM"
        "VAAObGF0bgAOAAQAAAAA//8AAwAAAAEAAgADa2VybgAgbWFyawAabWttawAUAAAAAQACAAAAAQABAAAAAQAAAAMCFgAuAAgABgAQ"
        "AAEACgABAAEB9gAWAAEBzgAMAAEABAABAJICsQABAAEA3gAEAAAAAQAIAAEB0gGOAAEBqgAMAHUBfAF8AXwBfAF8AXYBfAF8AXAB"
        "fAFqAWoBZAFeAV4BXgFeAVgBUgF8AXwBTAFMAUwBTAFGAXwBfAFSAUABfAF8AXwBfAF8AXwBdgFSAXwBOgFSAVIBUgF8AXwBfAF8"
        "AXwBfAF8AVgBUgFAAVIBfAF8AXwBNAE0ATQBNAEuATQBNAEoATQBNAE0AXwBIgE0ATQBNAE0AS4BfAE0AXwBHAEcARwBHAEcARYB"
        "EAF8AQoBBAE0ATQBNAE0ATQBNAEuATQBNAD+ATQBfAE0ATQA+AF8APIBNAE0ATQBNAEuAOwBBAE0ATQBNAE0ATQAAQEpAdMAAQFa"
        "AdMAAQFoAdMAAQHeAdMAAQGGAdMAAQB9An4AAQGCAdMAAQBSArEAAQB9AdMAAQEvAn4AAQJmAdMAAQEDArEAAQEuAdMAAQHjAn4A"
        "AQGGAn4AAQCqA1wAAQDVAn4AAQEuArwAAQD/A1wAAQEqAn4AAQD5An4AAQEsAn4AAQHqAmIAAQEDA1wAAQEuAn4AAgAEAAEADQAA"
        "AA8ATwANAFEAVgBOAFgAeABUAAUAAAAiAAAAHAAAABYAAAAWAAAAFgABAJgB0wABAL0B0wABAJIB0wABAAUA3ADeAN8A4wDkAAIA"
        "CAACCBwACgACBQwABAAABvoFggAdABYAAAAAAAAAAAAA/+wAAAAAAAAAAAAAAAAAAAAAAAD/4gAAAAAAAAAAAAAAAAAAAAD/7P/s"
        "AAD/4gAAAAAAAAAAAAAAAP/sAAAAAP+I/+wAAP/s/9gAAP/sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+wAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAA/+IAAAAAAAAAAAAAAAAAAAAAAAD/7P/sAAAAAP/YAAAAAAAAAAAAAP/sAAD/7AAAAAAAAAAA/+wAAAAA"
        "AAAAAP/iAAAAAAAA/+IAAAAAAAAAAAAA/+wAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/4j/7AAAAAD/2AAAAAAAAAAAAAAAAAAA/+wA"
        "AAAAAAAAAP/sAAAAAAAAAAAAAAAAAAD/7P/iAAD/7AAAAAAAAAAAAAD/7AAAAAAAAAAAAAAAAAAAAAAAAP/YAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/84AAAAA//b/zv/OAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//YA"
        "AAAAAAAAAP/sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/4v/iAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AP/iAAD/7AAAAAAAAAAAAAAAAP/sAAAAAP+c/+wAAP/s/9gAAP/sAAAAAAAA/+wAAP/sAAAAAAAAAAAAAAAAAAAAAAAA/4gAAAAA"
        "/+wAAAAAAAAAAAAA/+wAAAAA/+IAAAAAAAAAAP/sAAAAAAAAAAD/iP/sAAD/7P+6AAD/7AAAAAAAAAAAAAD/7AAAAAAAAAAAAAAA"
        "AAAAAAAAAP/EAAAAAAAA/+wAAP/sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+IAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "/84AAAAAAAAAAP/iAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/iAAD/zgAAAAAAAAAAAAAAAAAAAAD/7P/YAAAAAAAAAAAA"
        "AP/iAAAAAP/sAAAAAP/iAAAAAAAAAAAAAAAAAAAAAAAA/4j/7P/i/+z/nAAAAAAAAP/O/+L/4v/i/5z/zv+w/9j/nP/YAAD/7P/i"
        "/9j/xP+cAAD/nAAAAAD/zgAAAAD/zv+6AAD/zgAAAAAAAAAA/+L/xP/i/+L/2P9+/84AAP/i/5IAAP/YAAAAAP/s/+IAAP/iAAAA"
        "AAAAAAAAAAAA/+wAAAAA/4j/7AAA/+z/zgAA/+wAAAAAAAD/zgAA/5wAAAAAAAAAAP+6AAD/2AAAAAAAAP+cAAD/nP+mAAD/zgAA"
        "AAAAAP/sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP+I/+wAAAAAAAAAAAAAAAAAAP/s/+wAAP/EAAAAAAAAAAD/7AAAAAAAAAAAAAD/"
        "zgAA/+z/2AAA/+wAAAAAAAD/9gAA/+IAAAAAAAD/av/iAAD/9gAAAAD/iP/iAAD/7AAAAAD/7AAAAAD/7AAAAAD/7AAAAAAAAAAA"
        "/+wAAP/sAAAAAAAA/+wAAP/s/9gAAP/sAAEAOQABAAoACwAMAA0ADgAWABcAHAAdAB4AHwAgACIALAAuAC8AMAA2ADsARABFAEYA"
        "TQBOAE8AUABRAFIAUwBXAFkAWgBbAFwAaABpAGoAbABtAHMAdQCAAIEAgwCEAIYAhwCIAIkAmACcAKkAqgCrAKwAxwACAD4AAQAB"
        "AA4ACQAJAA4ACgAMAAMADQAOAAQADwAPAAMAFAAUAAQAFQAVAAMAFgAWAAQAFwAXABQAHQAdAAgAHgAeAAsAHwAfAAgAIAAgAAQA"
        "IgAiAAMAKQApAAMAKgAqAAgAKwArAAQALAAsAAMALQAtAAgALgAuAAwALwAvAA8AMAAwAAsANgA2AAsAOwA7AAUAPABBAAcAQgBC"
        "AAUAQwBDAAIARABFAAUARgBHABAASABIAAUASQBMAAEATQBNAAIATwBPAAIAUABQAA0AUQBRAAoAUwBTAA0AVgBWAA0AWQBaAAIA"
        "WwBcAAoAXgBeAAUAXwBiAAEAZABkAAEAZQBlAAUAZwBnAAIAaABoAAUAagBqABIAawBrAAIAbABsABMAbQBtABUAbgBxAAYAcwBz"
        "AAoAgACAAAMAgQCBAA8AhgCGAAMAiQCJAAwAmACZAAkAnACcAAkAqQCrABEArACsAAkAswC0AAkAxwDHAAQAywDLAAMAAgAuAAEA"
        "AQAQAAoACgAHAAsADAARAA0ADgAIABcAFwASABwAHAACAB0AHQATAB4AHgAUAB8AHwAJACIAIgACACwALAACAC4ALgADAC8ALwAV"
        "ADAAMAAKADYANgAKADsAOwAWAEQARQAXAEYARgAcAE0ATQAYAE4ATgABAE8ATwANAFAAUAAEAFEAUQAZAFIAUwAEAFcAVwAFAFkA"
        "WQAaAFoAWgAGAFsAXAABAGgAaAABAGkAaQAbAGoAagAOAGwAbAAPAG0AbQAFAHMAcwAFAHUAdQAZAIAAgAACAIEAgQAJAIMAgwAH"
        "AIYAhgADAIcAhwAJAIgAiAAHAIkAiQACAJgAmAALAJwAnAALAKkAqwAMAKwArAALAAEAigAEAAAAQAx8DGYMVAxUDC4MLgsQCwYK"
        "+AruCswKrgqkCwYK7gn6Cu4J4AmmCZwJHgjUCEIHUAbyBqAGNgYMBgwF3gWgBXoFWAU2BTAFNgU2BR4E+ATWBIgFegV6BFIEJAP6"
        "A4ACxgIoAY4FMAEUCu4KpAxmCwYJ4AqkDGYK7gEOAQ4BDgsGAAEAQAABAAoACwAMAA0ADgAUABYAFwAcAB0AHgAfACAAIgAqACwA"
        "LgAvADAANQA2ADcAOAA6ADsAQwBEAEUARgBNAE4ATwBQAFEAUgBTAFcAWQBaAFsAXABoAGkAagBsAG0AcgBzAHQAdQB4AIAAgQCD"
        "AIQAhgCHAIgAiQCpAKoAqwDHAAEAOP/iAB4ACv/sAAv/7AAM/+wAD//sABX/7AAi/+wAKf/sACz/7AAv/4gAOP+cADv/7ABC/+wA"
        "RP/iAEX/7ABG/+wAR//sAEj/7ABO/+IAXv/sAGX/7ABo/+wAav/iAG3/4gBy/+wAc//sAHj/9gCA/+wAgf+IAIb/7ADL/+wAJgAK"
        "/+wAC//sAAz/7AAP/+wAFf/sACL/7AAp/+wALP/sAC//iAA1/+wAOP+cADv/zgBC/84AQ//sAET/zgBF/84ARv/sAEf/7ABI/84A"
        "Tf/sAE//4gBZ/+wAWv/sAF7/zgBl/84AZ//sAGj/zgBr/+wAbP/iAG3/7ABy/+wAc//sAHX/7AB4/+wAgP/sAIH/iACG/+wAy//s"
        "ACcACv/sAAv/7AAM/+wAD//sABX/7AAi/+wAKf/sACz/7AAv/4gANf/sADj/nAA7/+IAQv/iAEP/7ABE/+wARf/iAEb/7ABH/+wA"
        "SP/iAE3/9gBO//YAT//sAFf/7ABZ//YAWv/2AF7/4gBl/+IAZ//2AGj/4gBp/+wAav/2AGv/9gBs/+IAbf/iAHj/9gCA/+wAgf+I"
        "AIb/7ADL/+wALgAK/+wAC//sAAz/7AAP/+wAFf/sABz/2AAi/+wAKf/sACz/7AAv/7oANf/sADj/nAA7/9gAQv/YAEP/4gBE/+IA"
        "Rf/YAEb/2ABH/9gASP/YAE7/7ABP/+IAUP/sAFH/7ABT/+wAVv/sAFf/2ABZ//YAWv/sAFv/7ABc/+wAXv/YAGX/2ABo/9gAav/s"
        "AGz/4gBt/+wAcv/sAHP/7AB0/+wAdf/sAHj/7ACA/+wAgf+6AIb/7ADL/+wAHgAK/+wAC//sAAz/7AAP/+wAFf/sACL/7AAp/+wA"
        "LP/sADX/7AA3/8QAOP+cADv/7ABC/+wARP/2AEX/7ABG/+wAR//sAEj/7ABO//YAT//iAF7/7ABl/+wAaP/sAGn/9gBq//YAbf/s"
        "AHL/7ACA/+wAhv/sAMv/7AAKADb/7AA4/5wAQ//sAET/7ABO/+IAV//sAHL/ugBz/+IAdP/iAHj/7AALADX/7AA4/6YAQ//iAET/"
        "7ABO/+wAaf/sAHL/7ABz//YAdP/2AHX/7AB4/+wADQA1/+IAOP+cAEP/7ABE/+wATv/sAFn/7ABa/+wAaf/iAHL/7ABz/+wAdP/s"
        "AHX/7AB4/+wAEwA1/+IAOP+cADv/9gBC//YAQ//sAET/9gBF//YARv/sAEf/7ABI//YATv/sAE//7ABX/+wAWf/sAFr/7ABe//YA"
        "Zf/2AGj/9gBy/9gACABE/+IATv/sAFn/4gBp//YAcv/iAHP/7AB0/+wAdf/sAAkAQ//2AET/zgBO//YAWf/sAFr/7ABp/+wAcv/i"
        "AHX/7AB4/+wABAA4/5wATv/sAE//4gBp/+wAAQA4/5wACAA1/+wAOP/iAEP/9gBE/+wATv/sAFf/7AB1/+wAeP/2AAgANf/sADj/"
        "nABE/+IATv/sAHL/4gBz/+wAdP/iAHX/7AAJADX/4gA4/5wAQ//sAET/7ABO/+wAT//sAFf/7ABZ/+wAcv/YAA8ANf/YADj/ugBD"
        "/+IARP+cAE7/nABP/+IAV/9CAFn/xABa/84Aaf+SAHL/ugBz/84AdP+wAHX/sAB4/8QACwA4/+wAQ//sAET/7ABO/+wAT//sAFf/"
        "7ABp/+wAcv/iAHT/7AB1/+wAeP/sAAoAHP/iADX/4gA3/8QAOP+cAE7/4gBP/+wAWf/sAHL/4gB0/+IAdf/iABoALv/sAC//iAA1"
        "/+IAOP+cADv/7ABC/+wARP/sAEX/7ABI/+wATv/sAFH/9gBa/+wAW//2AFz/9gBe/+wAZf/sAGj/7ABp/+wAav/sAGz/zgBy/9gA"
        "c//iAHT/4gB1/+wAgf+IAIn/7AAUABT/zgAc/8QAH//YACr/2AA1/5wANv/iADf/zgA4/zgAQ//OAET/zgBO/84AT//iAFf/xABZ"
        "/9gAWv/iAHL/pgBz/+IAdP/YAHX/ugB4/+IAFwAv/+wANf/iADv/2ABC/9gARP/YAEX/2ABI/9gAUf/sAFv/7ABc/+wAXv/YAGX/"
        "2ABo/9gAaf/sAGr/7ABs/9gAbf/sAHL/4gBz/+wAdP/sAHX/7AB4/+wAgf/sADwAAf/OAAn/zgAK/+wAC//iAAz/7AAP/+wAFf/s"
        "ABb/7AAX/+wAHf/iAB7/7AAf/+wAIv/sACn/7AAq/+IALP/sAC3/4gAu/+wAMP/sADX/4gA2/+wAN//sADr/7AA7/7oAQv+6AET/"
        "sABF/7oARv+wAEf/sABI/7oATv+mAFH/zgBX/2AAWf/YAFv/zgBc/84AXv+6AGX/ugBo/7oAav+cAGz/zgBt/7oAcv+6AHP/ugB0"
        "/7oAdf/OAHj/xACA/+wAhv/sAIn/7ACY/7oAmf+6AJz/ugCp/+IAqv/iAKv/4gCs/7oAs/+6ALT/ugDL/+wAJAAB/9gACf/YAAr/"
        "4gAL/9gADP/iAA//4gAV/+IAIv/iACn/4gAs/+IALv/iAC//2AA1/+wAO/+6AEL/ugBE/8QARf+6AEj/ugBO/+IAUf/sAFv/7ABc"
        "/+wAXv+6AGX/ugBo/7oAaf/sAGr/4gBz/+wAdP/sAHX/7AB4/+wAgP/iAIH/2ACG/+IAif/iAMv/4gASAAH/7AAJ/+wAH//sAC//"
        "2AA4/+wAO//iAEL/4gBE/+wARf/iAEj/4gBO/+wAXv/iAGX/4gBo/+IAbP/iAG3/7AB4/+wAgf/YAB8AAf/iAAn/4gAf/+wALv/2"
        "AC//7AA7/9gAQv/YAEP/7ABE/+IARf/YAEb/4gBH/+IASP/YAE7/4gBR/+wAWf/sAFv/7ABc/+wAXv/YAGX/2ABo/9gAaf/sAGr/"
        "4gBt/+wAcv/2AHP/7AB0/+wAdf/sAHj/7ACB/+wAif/2AAIAH//sADj/4gAOAAv/4gAW/+IAKv/YADD/4gA1/9gAN//EADj/2ABD"
        "/+wARP+cAE7/nABp/5wAc//EAHX/sAB4/84ABgA1/+wAN//YADj/4gBD/+wARP/sAE7/7AAqAAH/4gAJ/+IAL//sADX/7AA2/+wA"
        "N//YADj/4gA7/+IAQv/iAEP/7ABE/+IARf/iAEb/7ABH/+wASP/iAE3/7ABP/+wAUf/sAFn/7ABa/+wAW//sAFz/7ABe/+IAZf/i"
        "AGf/7ABo/+IAaf/iAGr/4gBr/+wAbP/sAG3/7ABy/+IAc//sAHX/7AB4/+wAgf/sAJj/4gCZ/+IAnP/iAKz/4gCz/+IAtP/iAAIA"
        "N//sADj/4gAHAAv/4gA3/84AOP+IAET/7ABP/9gAcv+cAHT/2AAIAAv/4gA1/+wAOP/iAET/zgBO/9gAcv/YAHX/4gB4/+IAAgA3"
        "/+IAOP/sAAMAC//sAET/zgBp/+IAAgA4/+wATv/iAEcAAf/EAAn/xAAK/+wAC//sAAz/7AAN/+wADv/sAA//7AAU/+wAFf/sABb/"
        "7AAX/+IAHP+mAB3/2AAe/+wAH//iACD/7AAi/+wAKf/sACr/4gAr/+wALP/sAC3/2AAu//YAMP/sADX/7AA2/+wAN//YADj/4gA6"
        "/+wAO/+cAEL/nABD/+IARP+cAEX/nABG/5wAR/+cAEj/nABN/9gATv+SAE//4gBR/84AV/84AFn/4gBa/9gAW//OAFz/zgBe/5wA"
        "Zf+cAGf/2ABo/5wAaf+cAGr/nABr/9gAbf/EAHL/ugBz/7AAdP+mAHX/pgB4/6YAgP/sAIb/7ACJ//YAmP+cAJn/nACc/5wArP+c"
        "ALP/nAC0/5wAx//sAMv/7AAJABz/7AAf/+wANf/sADf/zgA4/8QAcv/iAHT/4gB1/+wAeP/sAAQANf/sADf/4gA4/+IAdP/iAAUA"
        "Nf/sADf/2AA4/9gATv/sAHL/4gAKAAv/9gA1/+wAN//YADj/zgBZ/+wAcv/sAHP/7AB0/+wAdf/sAHj/7AAAAAEAAAAKAIQA1AAC"
        "REZMVABqbGF0bgAOAFAACEFaRSAAQkNBVCAANENSVCAAQktBWiAAQk1PTCAAYFJPTSAAYFRBVCAAQlRSSyAAQgAA//8ABAAAAAIA"
        "AwAFAAD//wAEAAAAAgADAAQAAP//AAMAAQACAAMABAAAAAD//wADAAAAAgADAAZjY21wAEhjY21wAD5mcmFjADhsaWdhADJsb2Ns"
        "ACxsb2NsACYAAAABAAQAAAABAAMAAAABAAgAAAABAAcAAAADAAAAAgACAAAAAgAAAAIACQGGAXYBTgE6AP4A8ADiAFgAFAAEAAgA"
        "AQAIAAEANgABAAgABQAmAB4AGAASAAwAfQACAFoAfAACAFAAeQACAE0AewADAE0AWgB6AAMATQBQAAEAAQBNAAQAAAABAAgAAQB0"
        "AAUASgA+ACgAHAAQAAEABACSAAMApQCIAAEABACRAAMApQCIAAIADgAGAI4AAwClAIQAkAADAKUAiAABAAQAjAADAKUAgwAEACIA"
        "GgASAAoAigADAKUAggCLAAMApQCDAI0AAwClAIQAjwADAKUAiAABAAUAgQCCAIMAhQCHAAEAAAABAAgAAQAkAAcAAQAAAAEACAAB"
        "ABYABgAGAAAAAQAIAAEACAABAA4AAQABAKEAAgAWAAYAAQAeAAEAAQAeAAEAAAAGAAEAWgABAAEAWgABAAAABQABAAAAAQAIAAEA"
        "BgAFAAEAAQBQAAIAEAABAAoAAAABAAoAAgAYABIAAQACAHwAfQACAE0AWgACAE0AUAABABAAAQAKAAAAAQBeAAEABgAQAAEACgAA"
        "AAIATgBKADoAJAADAAAAEgASAAEABAAAAAEAAQABAAEAAAABAAIAAwDcANwAAQDeAN8AAQDjAOQAAQACAAIAUABQAAIAVwBXAAEA"
        "AgAAAAEAAgBQAFcAAAABAAEACAABAAAAFAABAAAAHAACd2dodAEAAAAAAgABAAAAAAEEArwAAAAA"),
    "VT323-Regular.ttf": (
        "AAEAAAAOAIAAAwBgR0RFRgUBBVgAAL3QAAAAVEdQT1OJFakeAAC+JAAAA8BHU1VCzW3JywAAweQAAALyT1MvMmgmqN8AAAFoAAAA"
        "YGNtYXAo/QbGAAAFZAAAAoBnYXNwAAAAEAAAvcgAAAAIZ2x5ZuRCjCYAAAm8AACvgmhlYWQZ5ZMPAAAA7AAAADZoaGVhAzcBlAAA"
        "ASQAAAAkaG10eFG4JB4AAAHIAAADnGxvY2FDcG4SAAAH5AAAAdhtYXhwAP0BoQAAAUgAAAAgbmFtZSAvPCgAALlAAAABsHBvc3RN"
        "l7TUAAC68AAAAtgAAQAAAAIAAIReY0ZfDzz1AAMD6AAAAADTom6rAAAAAOcW4GD+bP8QAagEEAAAAAcAAgAAAAAAAAABAAADIP84"
        "AAABkP5s/+gBqAABAAAAAAAAAAAAAAAAAAAA4wABAAAA6wDZAAYAxgAIAAEAAAAAAAAAAAAAAAAAAwABAAQBkAGQAAUAAAKKAlgA"
        "AABLAooCWAAAAV4AMgDwAAAAAAUJAAAAAAAAAAAABwAAAAAAAAAAAAAAAFVLV04AwAAAIhUDIP84AAAEEADwIAABkwAAAAABkAIw"
        "AAAAIAADAZAAAAAAAAABkAAAAZAAAAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQB"
        "kABMAZAATAGQAEwBkABMAZAATAGQAEwBkAAkAZAAJAGQAGABkABgAZAAVgGQAEwBkABgAZAAJAGQACQBkABMAZAAJAGQACQBkAAk"
        "AZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAA"
        "JAGQACQBkAAkAZAAJAGQACQBkAAkAZAAOAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQ"
        "ACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQAEwBkAAkAZAAJAGQAEwBkABMAZAATAGQAEwBkABMAZAATAGQAEwBkABMAZAATAGQACQB"
        "kABMAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAOAGQACQBkAAk"
        "AZAAJAGQACQBkAAkAZAAJAGQACQBkAAkAZAAJAGQADgBkAAaAZAAGgGQABoBkAA4AZAAJAGQACQBkAAkAZAAVgGQAFYBkABCAZAA"
        "TAGQADgBkAA4AZAAJAGQADgBkAAzAZAAOAGQAEIBkAAzAZAAfgGQAHQBkAB0AZAAWwGQABUBkAAVAZAAJAGQADgBkAAkAZAAkgGQ"
        "AHQBkACSAZAAkgGQACQBkACcAZAAnAGQACQBkACSAZAAJAGQACQBkABMAZAAnAGQAJIBkAAkAZAAJAGQAJwBkABMAZAATAGQAIgB"
        "kAB0AZAAfgGQAG8BkAAkAZAAJAGQAGABkABgAZAAJAGQACQBkABvAZAAbwGQAEIBkABCAZAAQgGQAJIBkACSAZAAkgGQAAABkAAk"
        "AZAAJAGQACQBkAAkAZAAJAGQACQBkAA4AZAATAGQAEwBkABMAZAATAGQAFEBkABRAZAAOAGQACQBkAAkAZAAJAGQACQBkAAkAZAA"
        "JAGQADgBkAAkAZAAJAGQACQBkABWAZAAnAGQAJwBkAAkAZAAJAGQ//wAAP68AAD/DAAA/uQAAP8MAAD+xgAA/sYAAP6UAAD+vAAA"
        "/wwAAP8MAAD/AgGQACQAnACSAFYATAB0AEwAVgAkAAAAAgAAAAMAAAAUAAMAAQAAABQABAJsAAAAOAAgAAQAGAAAAA0ALwA5AH4A"
        "/wExAVMCvALGAtoC3AMBAwQDCQMjIBQgGiAeICIgJiA6IEQgrCEiIhIiFf//AAAAAAANACAAMAA6AKABMQFSArwCxgLaAtwDAAMD"
        "AwgDIyATIBggHCAiICYgOSBEIKwhIiISIhX//wAB//UAAABQAAAAAP8iAAD+Jv4f/g/+Dv3Z/doAAP29AADgnQAA4HLgceB34Eng"
        "EN+u3q7ewAABAAAAAAA0AAAAUADYAAABlAAAAAAAAAAAAAAAAAGKAAABigAAAYoAAAAAAAAAAAAAAAAAAAAAAAAAAwCYAJ4AmgC7"
        "AMkAywCfAKgAqQCRAL8AlgCsAJsAoQCVAKAAxQDDAMQAnADKAAQADAANAA8AEQAWABcAGAAZAB4AHwAgACEAIgAkACwALgAvADAA"
        "MQAyADcAOAA5ADoAPACmAJIApwDUAKIA5wA9AEUARgBIAEoATwBQAFEAUgBZAFsAXABdAF4AYABoAGoAawBsAG4AbwB0AHUAdgB3"
        "AHoApADSAKUAxwC4AJkAuQC9ALoAvgDTAM0A5gDOAH4ArgDIAK0AzwDoANEAxgCLAIwA4wDWAMwAkwDkAIoAfwCvAI8AjgCQAJ0A"
        "CAAFAAYACgAHAAkACwAOABUAEgATABQAHQAaABsAHAAQACMAKAAlACYAKgAnAMEAKQA2ADMANAA1ADsALQBtAEEAPgA/AEMAQABC"
        "AEQARwBOAEsATABNAFgAVABVAFYASQBfAGQAYQBiAGYAYwDCAGUAcwBwAHEAcgB4AGkAeQArAGcA1wDfAKsAqgCzALQAsgAAAAAA"
        "AAAAAAAAhwEoATQB1gJ3AoMCjwMfA6MEEwQfBKoFOwWPBf0GCQZ4BuYHOQe+CE4IogkQCRwJiwn5CloK9AtFDBkMwwzPDWAOCw4X"
        "DsMPbhA7EEcQ1xFCEb4SZxL3E2cTuhRKFPMU/xWpFlMW4xe5GF0Y1hloGcQaHhqSGp4bExuHG5MbnxwVHKYdAh0OHaAeQh6THv0f"
        "CR90H94gNyC+IUchlCHTIiwiOCKSIp4i9yNZI64kMCSDJS8lpCWwJhomniaqJy8nsyhCKE4o1ilaKegqayrEKwgroiv4LG4s/i0K"
        "LZsuKy6ULy8vozAuMNIxdzG+Mlcy2DNtM8g0NjTHNRs1gjXzNmw26jdoN8Q4SzjIOQY5SzmQOeE6mDtzPDo8sT0lPUM9Yj2XPcs9"
        "+T5CPos/CD8mP4M/30AUQDJAfkDzQQhBHEGIQfVCW0LBQzNDpEO5Q85D40PrRG1E7kUyRXZF2EY7Rp5G00cIRzxHPEfASFpJEEmE"
        "SgFKgErBStVLU0uVS7ZME0xvTL5NJU1OThBOwU96UDdQt1GuUshTZFOyVBZUc1TDVThV1FX1VglWKVZJVnVWr1brVv9XHlcyV1JX"
        "cVd7V4VXj1eZV6NXrVe3V8EAAgAkAAABbAIwAFMAZwAAJAcWFRQHIyY1NDcmNTQ3IxYVFAcWFRQHIyY1NDcmNTQ3MyY1NDcmNTQ3"
        "MyY1NDczJjU0NzMmNTQ3MxYVFAczFhUUBzMWFRQHMxYVFAcWFRQHMxYVJjU0NyMmNTQ3IxYVFAcjFhUUBzMBbAQEBFAEBAQEoAQE"
        "BARQBAQEBB4EBAQEFAQEHgQEFAQEeAQEFAQEHgQEFAQEBAQeBHYEFAQEPAQEFAQEZGEREBgXEREXGBARFxgQEBgXERAYFxERFxgQ"
        "ERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXERAYFxEQGIkXGBARFxgQEBgXERAYFxEAAwAkAAABbAMgABMA"
        "ZwB7AAATJjU0NzMmNTQ3MxYVFAcjFhUUBxIHFhUUByMmNTQ3JjU0NyMWFRQHFhUUByMmNTQ3JjU0NzMmNTQ3JjU0NzMmNTQ3MyY1"
        "NDczJjU0NzMWFRQHMxYVFAczFhUUBzMWFRQHFhUUBzMWFSY1NDcjJjU0NyMWFRQHIxYVFAczoAQEKAQEUAQEKAQEfAQEBFAEBAQE"
        "oAQEBARQBAQEBB4EBAQEFAQEHgQEFAQEeAQEFAQEHgQEFAQEBAQeBHYEFAQEPAQEFAQEZAKAERcYEBEXGBAQGBcREBgXEf3hERAY"
        "FxERFxgQERcYEBAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcREBiJFxgQERcY"
        "EBAYFxEQGBcR//8AJAAAAWwDIAAiAAQAAAAHANsBkACgAAQAJAAAAWwC0AAJABMAZwB7AAATJjU0NzMWFRQHMyY1NDczFhUUBxIH"
        "FhUUByMmNTQ3JjU0NyMWFRQHFhUUByMmNTQ3JjU0NzMmNTQ3JjU0NzMmNTQ3MyY1NDczJjU0NzMWFRQHMxYVFAczFhUUBzMWFRQH"
        "FhUUBzMWFSY1NDcjJjU0NyMWFRQHIxYVFAczUAQEUAQEUAQEUAQELAQEBFAEBAQEoAQEBARQBAQEBB4EBAQEFAQEHgQEFAQEeAQE"
        "FAQEHgQEFAQEBAQeBHYEFAQEPAQEFAQEZAKAERcYEBAYFxERFxgQEBgXEf3hERAYFxERFxgQERcYEBAYFxEQGBcRERcYEBEXGBAR"
        "FxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcREBiJFxgQERcYEBAYFxEQGBcRAAMAJAAAAWwDIAATAGcAewAA"
        "EyY1NDczFhUUBzMWFRQHIyY1NDcSBxYVFAcjJjU0NyY1NDcjFhUUBxYVFAcjJjU0NyY1NDczJjU0NyY1NDczJjU0NzMmNTQ3MyY1"
        "NDczFhUUBzMWFRQHMxYVFAczFhUUBxYVFAczFhUmNTQ3IyY1NDcjFhUUByMWFRQHM3gEBFAEBCgEBFAEBMwEBARQBAQEBKAEBAQE"
        "UAQEBAQeBAQEBBQEBB4EBBQEBHgEBBQEBB4EBBQEBAQEHgR2BBQEBDwEBBQEBGQC0BEXGBAQGBcREBgXEREXGBD9kREQGBcRERcY"
        "EBEXGBAQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYiRcYEBEXGBAQGBcR"
        "EBgXEf//ACQAAAFsA3AAIgAEAAAABwDcAZAAoP//ACQAAAFsAyAAIgAEAAAABwDdAZAAoAACACQAAAFsAjAAUgBsAAAAByMWFRQH"
        "FhUUBzMWFRQHIyY1NDcmNTQ3IxYVFAcWFRQHIyY1NDcmNTQ3JjU0NzMmNTQ3JjU0NzMmNTQ3MyY1NDchFhUUByMWFRQHFhUUBzMW"
        "FQcmNTQ3JjU0NyY1NDcjFhUUBxYVFAcWFRQHAWwEUAQEBARQBASgBAQEBFAEBAQEUAQEBAQEBBQEBAQEFAQEFAQEAQQEBFAEBAQE"
        "UASkBAQEBAQEPAQEBAQEBAEBERAYFxEQGBcREBgXEREXGBARFxgQEBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQ"
        "EBgXERAYFxEQGBcREBgoERcYEBEXGBARFxgQEBgXERAYFxEQGBcRAAADACQAAAFsAjAAPQBPAGEAAAAHIxYVFAczFhUUBxYVFAcj"
        "FhUUByEmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3IRYVFAczFhUUBxYVBjU0NyY1NDcjFhUUBxYVFAczBjU0NyMWFRQHFhUU"
        "BzMmNTQ3AWwEKAQEKAQEBAQoBAT+6AQEBAQEBAQEBAQEBAQEARgEBCgEBARYBAQEoAQEBASgBASgBAQEBKAEBAFRERAYFxEQGBcR"
        "EBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcXGBARFxgQEBgXERAYFxGPFxgQEBgXERAYFxER"
        "FxgQAAABACQAAAFsAjAAVQAAJRYVFAcjFhUUByMmNTQ3IyY1NDcjJjU0NyY1NDcmNTQ3MyY1NDczJjU0NzMWFRQHMxYVFAcjJjU0"
        "NyMWFRQHIxYVFAcWFRQHFhUUBzMWFRQHMyY1NDcBaAQEKAQEyAQEKAQEKAQEBAQEBCgEBCgEBMgEBCgEBFAEBHgEBCgEBAQEBAQo"
        "BAR4BASgEBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxERFxgQEBgXERAYFxEQGBcREBgXERAYFxER"
        "FxgQ//8AJP9gAWwCMAAiAA0AAAADAOEBkAAAAAIAJAAAAWwCMAA9AGkAAAAVFAcWFRQHIxYVFAcjFhUUByMmNTQ3JjU0NyY1NDcm"
        "NTQ3JjU0NyY1NDcmNTQ3MxYVFAczFhUUBzMWFRQHBjU0NyY1NDcmNTQ3IyY1NDcjFhUUBxYVFAcWFRQHFhUUBxYVFAczJjU0NzMB"
        "bAQEBCgEBCgEBPAEBAQEBAQEBAQEBAQEBPAEBCgEBCgEBFQEBAQEBCgEBHgEBAQEBAQEBAQEeAQEKAEwGBcREBgXERAYFxEQGBcR"
        "ERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXEY8XGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgX"
        "EREXGBAAAgAkAAABbAIwAEEAbwAAABUUBxYVFAcjFhUUByMWFRQHIyY1NDczJjU0NyY1NDcjJjU0NzMmNTQ3JjU0NyMmNTQ3MxYV"
        "FAczFhUUBzMWFRQHBjU0NyY1NDcmNTQ3IyY1NDcjFhUUBxYVFAczFhUUByMWFRQHFhUUBzMmNTQ3MwFsBAQEKAQEKAQE8AQEKAQE"
        "BAQoBAQoBAQEBCgEBPAEBCgEBCgEBFQEBAQEBCgEBFAEBAQEKAQEKAQEBARQBAQoATAYFxEQGBcREBgXERAYFxERFxgQERcYEBEX"
        "GBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcRjxcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcRERcYEAABAEwA"
        "AAFEAjAAPQAANxYVFAcWFRQHMxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NzMWFRQHIxYVFAcWFRQHMxYVFAegBAQE"
        "BKAEBPAEBAQEBAQEBAQEBAQEBPAEBKAEBAQEoAQE8BAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcR"
        "EBgXERAYFxEQGBcRAAACAEwAAAFEAyAAEwBRAAATJjU0NzMmNTQ3MxYVFAcjFhUUBwMWFRQHFhUUBzMWFRQHIyY1NDcmNTQ3JjU0"
        "NyY1NDcmNTQ3JjU0NyY1NDczFhUUByMWFRQHFhUUBzMWFRQHoAQEKAQEUAQEKAQEUAQEBASgBATwBAQEBAQEBAQEBAQEBATwBASg"
        "BAQEBKAEBAKAERcYEBEXGBAQGBcREBgXEf5wEBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcR"
        "EBgXERAYFxH//wBMAAABRAMgACIAEQAAAAcA2wGQAKAAAwBMAAABRALQAAkAEwBRAAATJjU0NzMWFRQHMyY1NDczFhUUBwcWFRQH"
        "FhUUBzMWFRQHIxYVFAcWFRQHMxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NzMWFRQHUAQEUAQEUAQEUAQEoAQEBASg"
        "BASgBAQEBKAEBPAEBAQEBAQEBAQEBAQEBPAEBAKAERcYEBAYFxERFxgQEBgXEaAQGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQ"
        "ERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXEQAAAgBMAAABRAMgABMAUQAAEyY1NDczFhUUBzMWFRQHIyY1NDcRFhUUBxYVFAcz"
        "FhUUByMmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3MxYVFAcjFhUUBxYVFAczFhUUB3gEBFAEBCgEBFAEBAQEBASgBATwBAQE"
        "BAQEBAQEBAQEBATwBASgBAQEBKAEBALQERcYEBAYFxEQGBcRERcYEP4gEBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAR"
        "FxgQERcYEBAYFxEQGBcREBgXERAYFxEAAAEATAAAAUQCMAA8AAAAFRQHIxYVFAcWFRQHFhUUByMmNTQ3JjU0NyY1NDcmNTQ3JjU0"
        "NyY1NDcmNTQ3MxYVFAcjFhUUBxYVFAczAUQEoAQEBAQEBFAEBAQEBAQEBAQEBAQEBPAEBKAEBAQEoAEwGBcREBgXERAYFxEQGBcR"
        "ERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXEQABACQAAAFsAjAAZgAAABUUBxYVFAcWFRQHIxYVFAcjJjU0"
        "NyMmNTQ3IyY1NDcmNTQ3JjU0NzMmNTQ3MyY1NDczFhUUBzMWFRQHIyY1NDcjFhUUByMWFRQHFhUUBxYVFAczFhUUBzMmNTQ3JjU0"
        "NyMmNTQ3MwFsBAQEBAQoBATIBAQoBAQoBAQEBAQEKAQEKAQEyAQEKAQEUAQEeAQEKAQEBAQEBCgEBHgEBAQEPAQEjAEwGBcREBgX"
        "ERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcRERcYEBAYFxEQGBcREBgXERAYFxEQGBcRERcYEBEX"
        "GBARFxgQAAEAJAAAAWwCMABtAAAAFRQHFhUUBxYVFAcWFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3IxYVFAcWFRQHFhUUByMmNTQ3"
        "JjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3MxYVFAcWFRQHFhUUBzMmNTQ3JjU0NyY1NDczFhUUBwFsBAQEBAQEBAQEBARQBAQEBAQE"
        "oAQEBAQEBFAEBAQEBAQEBAQEBAQEBFAEBAQEBASgBAQEBAQEUAQEAdAYFxEQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcY"
        "EBAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxERFxgQERcYEBEXGBAQGBcRAAEAYAAA"
        "ATACMAA9AAAlFhUUByMmNTQ3MyY1NDcmNTQ3JjU0NyY1NDcmNTQ3IyY1NDczFhUUByMWFRQHFhUUBxYVFAcWFRQHFhUUBwEsBATI"
        "BAQ8BAQEBAQEBAQEBDwEBMgEBDwEBAQEBAQEBAQEUBAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcR"
        "EBgXERAYFxEQGBcRAAIAYAAAATADIAATAFEAABMmNTQ3MyY1NDczFhUUByMWFRQHExYVFAcjJjU0NzMmNTQ3JjU0NyY1NDcmNTQ3"
        "JjU0NyMmNTQ3MxYVFAcjFhUUBxYVFAcWFRQHFhUUBxYVFAegBAQoBARQBAQoBAQ8BATIBAQ8BAQEBAQEBAQEBDwEBMgEBDwEBAQE"
        "BAQEBAQEAoARFxgQERcYEBAYFxEQGBcR/dAQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQ"
        "GBcREBgXEf//AFYAAAE6AyAAIgAZAAAABwDbAZAAoAADAEwAAAFEAtAACQATAFEAABIHIyY1NDczFhU2FRQHIyY1NDczBgcjFhUU"
        "BxYVFAcWFRQHFhUUBxYVFAczFhUUByMmNTQ3MyY1NDcmNTQ3JjU0NyY1NDcmNTQ3IyY1NDczFhWkBFAEBFAEoARQBARQEAQ8BAQE"
        "BAQEBAQEBDwEBMgEBDwEBAQEBAQEBAQEPAQEyAQCkRERFxgQEBgYGBcRERcYEN8REBgXERAYFxEQGBcREBgXERAYFxEQGBcRERcY"
        "EBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYAAACAGAAAAEwAyAAEwBRAAATJjU0NzMWFRQHMxYVFAcjJjU0NxMWFRQHIyY1NDcz"
        "JjU0NyY1NDcmNTQ3JjU0NyY1NDcjJjU0NzMWFRQHIxYVFAcWFRQHFhUUBxYVFAcWFRQHeAQEUAQEKAQEUAQEjAQEyAQEPAQEBAQE"
        "BAQEBAQ8BATIBAQ8BAQEBAQEBAQEBALQERcYEBAYFxEQGBcRERcYEP2AEBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQ"
        "GBcREBgXERAYFxEQGBcREBgXERAYFxEAAQAkAAABWAIwAEcAAAAHIxYVFAcWFRQHFhUUBxYVFAcWFRQHIxYVFAcjJjU0NyMmNTQ3"
        "MxYVFAczJjU0NyY1NDcmNTQ3JjU0NyY1NDcjJjU0NzMWFQFYBDwEBAQEBAQEBAQEKAQEoAQEKAQEUAQEUAQEBAQEBAQEBAQ8BATI"
        "BAHxERAYFxEQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQEBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBAYAAABACQAAAFs"
        "AjAAdwAAJRYVFAcjJjU0NyMmNTQ3IyY1NDcjFhUUBxYVFAcWFRQHIyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDczFhUUBxYV"
        "FAcWFRQHMyY1NDczJjU0NzMmNTQ3MxYVFAcjFhUUByMWFRQHIxYVFAczFhUUBzMWFRQHAWgEBFAEBB4EBDwEBEYEBAQEBARQBAQE"
        "BAQEBAQEBAQEBARQBAQEBAQERgQEPAQEHgQEUAQEHgQEPAQEMgQEMgQEPAQEUBAYFxERFxgQERcYEBEXGBAQGBcREBgXERAYFxER"
        "FxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcRERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXERAYFxEQGBcR"
        "AAEATAAAAWwCMAA6AAAkFRQHISY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDczFhUUBxYVFAcWFRQHFhUUBxYVFAcWFRQHMwFs"
        "BP7oBAQEBAQEBAQEBAQEBARQBAQEBAQEBAQEBAQEyEAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcR"
        "EBgXERAYFxEQGBcRAAEAJAAAAWwCMAClAAAAFRQHFhUUBxYVFAcWFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDcjFhUU"
        "BxYVFAcjFhUUBxYVFAcjJjU0NyY1NDcjJjU0NyY1NDcjFhUUBxYVFAcWFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDcm"
        "NTQ3JjU0NzMWFRQHMxYVFAczFhUUBzMmNTQ3MyY1NDczJjU0NzMWFRQHAWwEBAQEBAQEBAQEBFAEBAQEBAQEBAQEHgQEBAQUBAQE"
        "BDwEBAQEFAQEBAQeBAQEBAQEBAQEBFAEBAQEBAQEBAQEBAQEBGQEBB4EBA8EBB4EBA8EBB4EBGQEBAHQGBcREBgXERAYFxEQGBcR"
        "EBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgX"
        "ERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcRERcYEBEXGBARFxgQEBgXEQABACQAAAFsAjAAgwAA"
        "ABUUBxYVFAcWFRQHFhUUBxYVFAcWFRQHIyY1NDcjJjU0NyMmNTQ3IyY1NDcjFhUUBxYVFAcWFRQHFhUUByMmNTQ3JjU0NyY1NDcm"
        "NTQ3JjU0NyY1NDcmNTQ3MxYVFAczFhUUBzMWFRQHMxYVFAczJjU0NyY1NDcmNTQ3JjU0NzMWFRQHAWwEBAQEBAQEBAQEBFAEBDIE"
        "BB4EBCgEBCgEBAQEBAQEBFAEBAQEBAQEBAQEBAQEBGQEBB4EBB4EBCgEBCgEBAQEBAQEBFAEBAHQGBcREBgXERAYFxEQGBcREBgX"
        "ERAYFxERFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAY"
        "FxEQGBcRERcYEBEXGBARFxgQERcYEBAYFxH//wAkAAABbAMgACIAIgAAAAcA3QGQAKAAAgAkAAABbAIwAEEAbwAAABUUBxYVFAcj"
        "FhUUByMWFRQHIyY1NDcjJjU0NyMmNTQ3JjU0NyY1NDczJjU0NzMmNTQ3MxYVFAczFhUUBzMWFRQHBjU0NyY1NDcmNTQ3IyY1NDcj"
        "FhUUByMWFRQHFhUUBxYVFAczFhUUBzMmNTQ3MwFsBAQEHgQEMgQEoAQEMgQEHgQEBAQEBB4EBDIEBKAEBDIEBB4EBFQEBAQEBB4E"
        "BGQEBB4EBAQEBAQeBARkBAQeATAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcR"
        "jxcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcRERcYEAADACQAAAFsAyAAEwBVAIMAABMmNTQ3MyY1NDczFhUUByMW"
        "FRQHEhUUBxYVFAcjFhUUByMWFRQHIyY1NDcjJjU0NyMmNTQ3JjU0NyY1NDczJjU0NzMmNTQ3MxYVFAczFhUUBzMWFRQHBjU0NyY1"
        "NDcmNTQ3IyY1NDcjFhUUByMWFRQHFhUUBxYVFAczFhUUBzMmNTQ3M6AEBCgEBFAEBCgEBHwEBAQeBAQyBASgBAQyBAQeBAQEBAQE"
        "HgQEMgQEoAQEMgQEHgQEVAQEBAQEHgQEZAQEHgQEBAQEBB4EBGQEBB4CgBEXGBARFxgQEBgXERAYFxH+sBgXERAYFxEQGBcREBgX"
        "EREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxGPFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXERAY"
        "FxERFxgQAP//ACQAAAFsAyAAIgAkAAAABwDbAZAAoAAEACQAAAFsAtAACQATAFUAgwAAEyY1NDczFhUUBzMmNTQ3MxYVFAcSFRQH"
        "FhUUByMWFRQHIxYVFAcjJjU0NyMmNTQ3IyY1NDcmNTQ3JjU0NzMmNTQ3MyY1NDczFhUUBzMWFRQHMxYVFAcGNTQ3JjU0NyY1NDcj"
        "JjU0NyMWFRQHIxYVFAcWFRQHFhUUBzMWFRQHMyY1NDczUAQEUAQEUAQEUAQELAQEBB4EBDIEBKAEBDIEBB4EBAQEBAQeBAQyBASg"
        "BAQyBAQeBARUBAQEBAQeBARkBAQeBAQEBAQEHgQEZAQEHgKAERcYEBAYFxERFxgQEBgXEf6wGBcREBgXERAYFxEQGBcRERcYEBEX"
        "GBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXEY8XGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXEREXGBAA"
        "AAMAJAAAAWwDIAATAFUAgwAAEyY1NDczFhUUBzMWFRQHIyY1NDcSFRQHFhUUByMWFRQHIxYVFAcjJjU0NyMmNTQ3IyY1NDcmNTQ3"
        "JjU0NzMmNTQ3MyY1NDczFhUUBzMWFRQHMxYVFAcGNTQ3JjU0NyY1NDcjJjU0NyMWFRQHIxYVFAcWFRQHFhUUBzMWFRQHMyY1NDcz"
        "eAQEUAQEKAQEUAQEzAQEBB4EBDIEBKAEBDIEBB4EBAQEBAQeBAQyBASgBAQyBAQeBARUBAQEBAQeBARkBAQeBAQEBAQEHgQEZAQE"
        "HgLQERcYEBAYFxEQGBcRERcYEP5gGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgX"
        "EY8XGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXEREXGBAAAAMAJP+wAWwCgABTAHkAnwAAABUUBxYVFAcWFRQHFhUU"
        "ByMWFRQHIxYVFAcjFhUUByMmNTQ3MyY1NDcjJjU0NyY1NDcmNTQ3JjU0NzMmNTQ3MyY1NDczJjU0NzMWFRQHIxYVFAczAhUUBzMm"
        "NTQ3MyY1NDczJjU0NzMmNTQ3IxYVFAcjFhUUBxYVFAc2NTQ3IxYVFAcjFhUUByMWFRQHIxYVFAczJjU0NzMmNTQ3JjU0NwFsBAQE"
        "BAQEBB4EBDIEBKAEBFAEBB4EBB4EBAQEBAQEBB4EBDIEBKAEBFAEBB4EBB7sBCMEBBQEBBQEBCMEBFAEBB4EBAQEnAQjBAQUBAQU"
        "BAQjBARQBAQeBAQEBAHQGBcREBgXERAYFxEQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAR"
        "FxgQEBgXERAYFxH/ABgXEREXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxFhFxgQEBgXERAYFxEQGBcREBgXEREXGBARFxgQERcY"
        "EAD//wAkAAABbAMgACIAJAAAAAcA3QGQAKAAAgAkAAABbAIwAEEAbQAAAAcjFhUUBxYVFAczFhUUByMmNTQ3IyY1NDcjJjU0NyY1"
        "NDcmNTQ3MyY1NDczJjU0NzMWFRQHIxYVFAcWFRQHMxYVBjU0NyY1NDcmNTQ3JjU0NyMWFRQHIxYVFAcWFRQHFhUUBzMWFRQHMyY1"
        "NDcBbARQBAQEBFAEBPAEBDIEBB4EBAQEBAQeBAQyBATwBARQBAQEBFAEqAQEBAQEBAQyBAQeBAQEBAQEHgQEMgQEAQEREBgXERAY"
        "FxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYZxcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgX"
        "ERAYFxEQGBcRERcYEAAAAgAkAAABbAIwADwATgAAAAcWFRQHIxYVFAcjFhUUBxYVFAcWFRQHIyY1NDcmNTQ3JjU0NyY1NDcmNTQ3"
        "JjU0NyY1NDchFhUUBzMWFQY1NDcmNTQ3IxYVFAcWFRQHMwFsBAQEKAQEyAQEBAQEBFAEBAQEBAQEBAQEBAQEBAEYBAQoBFgEBASg"
        "BAQEBKABoREQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBhnFxgQERcYEBAYFxEQ"
        "GBcRAAIAJAAAAWwCMABBAF0AAAAHIxYVFAcjFhUUByMWFRQHIyY1NDczJjU0NyY1NDcmNTQ3JjU0NyY1NDcjJjU0NzMWFRQHMxYV"
        "FAczFhUUBzMWFQcmNTQ3IyY1NDcjFhUUBxYVFAcWFRQHMyY1NDcBbAQeBAQyBAR4BAR4BAQoBAQEBAQEBAQEBCgEBHgEBHgEBDIE"
        "BB4EVAQEHgQEWgQEBAQEBFoEBAEBERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQ"
        "GCgRFxgQERcYEBAYFxEQGBcREBgXEREXGBAAAgAk/2ABbAIwAFUAgwAAABUUBxYVFAcjFhUUByMWFRQHMxYVFAczFhUUByMmNTQ3"
        "IyY1NDcjJjU0NyMmNTQ3IyY1NDcmNTQ3JjU0NzMmNTQ3MyY1NDczFhUUBzMWFRQHMxYVFAcGNTQ3JjU0NyY1NDcjJjU0NyMWFRQH"
        "IxYVFAcWFRQHFhUUBzMWFRQHMyY1NDczAWwEBAQeBAQyBAQoBAQoBARQBAQoBAR4BAQyBAQeBAQEBAQEHgQEMgQEoAQEMgQEHgQE"
        "VAQEBAQEHgQEZAQEHgQEBAQEBB4EBGQEBB4BMBgXERAYFxEQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQ"
        "ERcYEBEXGBARFxgQEBgXERAYFxEQGBcRjxcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcRERcYEAACACQAAAFsAjAA"
        "WwBtAAAlFhUUByMmNTQ3IyY1NDcjJjU0NyMWFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NyEWFRQHMxYV"
        "FAcjFhUUByMWFRQHMxYVFAczFhUUBwI1NDcmNTQ3IxYVFAcWFRQHMwFoBARQBAQeBAQeBARkBAQEBAQEUAQEBAQEBAQEBAQEBAQE"
        "ARgEBCgEBBQEBDwEBBQEBB4EBEoEBASMBAQEBIxQEBgXEREXGBARFxgQERcYEBAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBAR"
        "FxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYFxEBARcYEBEXGBAQGBcREBgXEQABACQAAAFsAjAAVQAAJBUUBxYVFAcj"
        "FhUUByMmNTQ3IyY1NDczFhUUBzMmNTQ3JjU0NyMmNTQ3IyY1NDcmNTQ3MyY1NDczFhUUBzMWFRQHIyY1NDcjFhUUBxYVFAczFhUU"
        "BzMBbAQEBCgEBPAEBCgEBFAEBKAEBAQEyAQEKAQEBAQoBATwBAQoBARQBASgBAQEBMgEBCjgGBcREBgXERAYFxERFxgQERcYEBAY"
        "FxERFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXEREXGBAQGBcREBgXERAYFxEAAAEAJAAAAWwCMAA7AAAAByMWFRQHFhUU"
        "BxYVFAcWFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3IyY1NDchFhUBbAR4BAQEBAQEBAQEBAQEUAQEBAQEBAQE"
        "BAQEBHgEBAFABAHxERAYFxEQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGAABACQAAAFs"
        "AjAAbQAAABUUBxYVFAcWFRQHFhUUBxYVFAcjFhUUByMmNTQ3IyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NzMWFRQHFhUUBxYVFAcW"
        "FRQHFhUUBxYVFAczJjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3MxYVFAcBbAQEBAQEBAQEBCgEBPAEBCgEBAQEBAQEBAQEBARQBAQE"
        "BAQEBAQEBAQEoAQEBAQEBAQEBAQEBFAEBAHQGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBAR"
        "FxgQEBgXERAYFxEQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXEQACACQAAAFsAyAAEwCBAAATJjU0"
        "NzMmNTQ3MxYVFAcjFhUUBxYVFAcWFRQHFhUUBxYVFAcWFRQHIxYVFAcjJjU0NyMmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDczFhUU"
        "BxYVFAcWFRQHFhUUBxYVFAcWFRQHMyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NzMWFRQHoAQEKAQEUAQEKAQEfAQEBAQEBAQEBCgE"
        "BPAEBCgEBAQEBAQEBAQEBARQBAQEBAQEBAQEBAQEoAQEBAQEBAQEBAQEBFAEBAKAERcYEBEXGBAQGBcREBgXEbAYFxEQGBcREBgX"
        "ERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEX"
        "GBARFxgQERcYEBEXGBAQGBcR//8AJAAAAWwDIAAiADIAAAAHANsBkACgAAMAJAAAAWwC0AAJABMAgQAAEyY1NDczFhUUBzMmNTQ3"
        "MxYVFAcWFRQHFhUUBxYVFAcWFRQHFhUUByMWFRQHIyY1NDcjJjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3MxYVFAcWFRQHFhUUBxYV"
        "FAcWFRQHFhUUBzMmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDczFhUUB1AEBFAEBFAEBFAEBCwEBAQEBAQEBAQoBATwBAQoBAQEBAQE"
        "BAQEBAQEUAQEBAQEBAQEBAQEBKAEBAQEBAQEBAQEBARQBAQCgBEXGBAQGBcRERcYEBAYFxGwGBcREBgXERAYFxEQGBcREBgXERAY"
        "FxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAR"
        "FxgQEBgXEQACACQAAAFsAyAAEwCBAAATJjU0NzMWFRQHMxYVFAcjJjU0NxIVFAcWFRQHFhUUBxYVFAcWFRQHIxYVFAcjJjU0NyMm"
        "NTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDczFhUUBxYVFAcWFRQHFhUUBxYVFAcWFRQHMyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NzMW"
        "FRQHeAQEUAQEKAQEUAQEzAQEBAQEBAQEBCgEBPAEBCgEBAQEBAQEBAQEBARQBAQEBAQEBAQEBAQEoAQEBAQEBAQEBAQEBFAEBALQ"
        "ERcYEBAYFxEQGBcRERcYEP8AGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAY"
        "FxEQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXEQAAAQAkAAABbAIwAG8AAAAVFAcWFRQHIxYVFAcj"
        "FhUUByMWFRQHIxYVFAcjJjU0NyMmNTQ3IyY1NDcjJjU0NyMmNTQ3JjU0NyY1NDczFhUUBxYVFAcWFRQHMxYVFAczFhUUBzMmNTQ3"
        "MyY1NDczJjU0NyY1NDcmNTQ3MxYVFAcBbAQEBB4EBB4EBBQEBCgEBFAEBCgEBBQEBB4EBB4EBAQEBARQBAQEBAQEHgQEHgQEKAQE"
        "HgQEHgQEBAQEBFAEBAHQGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQ"
        "GBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEAAQAkAAABbAIwAKcAAAAVFAcWFRQHFhUUByMWFRQHFhUUByMWFRQH"
        "IyY1NDcjJjU0NyMWFRQHIxYVFAcjJjU0NyMmNTQ3JjU0NyMmNTQ3JjU0NyY1NDcmNTQ3MxYVFAcWFRQHFhUUBxYVFAcWFRQHMyY1"
        "NDczJjU0NyY1NDcmNTQ3JjU0NzMWFRQHFhUUBxYVFAcWFRQHMxYVFAczJjU0NyY1NDcmNTQ3JjU0NyY1NDczFhUUBwFsBAQEBAQe"
        "BAQEBBQEBDwEBBQEBDwEBBQEBDwEBBQEBAQEHgQEBAQEBAQEUAQEBAQEBAQEBAQeBAQUBAQEBAQEBAQ8BAQEBAQEBAQUBAQeBAQE"
        "BAQEBAQEBFAEBAHQGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQ"
        "ERcYEBAYFxEQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcY"
        "EBEXGBARFxgQEBgXEQABACQAAAFsAjAAgQAAJRYVFAcjJjU0NyMmNTQ3IyY1NDcjFhUUByMWFRQHIxYVFAcjJjU0NzMmNTQ3MyY1"
        "NDczJjU0NyMmNTQ3IyY1NDcjJjU0NzMWFRQHMxYVFAczFhUUBzMmNTQ3MyY1NDczJjU0NzMWFRQHIxYVFAcjFhUUByMWFRQHMxYV"
        "FAczFhUUBwFoBARQBAQeBAQUBAQ8BAQUBAQeBARQBAQeBAQoBAQeBAQeBAQoBAQeBARQBAQeBAQUBAQ8BAQUBAQeBARQBAQeBAQo"
        "BAQeBAQeBAQoBARQEBgXEREXGBARFxgQERcYEBAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgX"
        "ERAYFxERFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYFxEAAQAkAAABbAIwAFsAAAAHFhUUByMWFRQHIxYVFAcjFhUU"
        "BxYVFAcWFRQHIyY1NDcmNTQ3JjU0NyMmNTQ3IyY1NDcjJjU0NyY1NDczFhUUBxYVFAczFhUUBzMmNTQ3MyY1NDcmNTQ3MxYVAWwE"
        "BAQoBAQoBAQoBAQEBAQEUAQEBAQEBCgEBCgEBCgEBAQEUAQEBAQoBARQBAQoBAQEBFAEAfEREBgXERAYFxEQGBcREBgXERAYFxEQ"
        "GBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXEREXGBARFxgQERcYEBAYAAACACQAAAFsAyAAEwBvAAAT"
        "JjU0NzMmNTQ3MxYVFAcjFhUUBxYHFhUUByMWFRQHIxYVFAcjFhUUBxYVFAcWFRQHIyY1NDcmNTQ3JjU0NyMmNTQ3IyY1NDcjJjU0"
        "NyY1NDczFhUUBxYVFAczFhUUBzMmNTQ3MyY1NDcmNTQ3MxYVoAQEKAQEUAQEKAQEfAQEBCgEBCgEBCgEBAQEBARQBAQEBAQEKAQE"
        "KAQEKAQEBARQBAQEBCgEBFAEBCgEBAQEUAQCgBEXGBARFxgQEBgXERAYFxGPERAYFxEQGBcREBgXERAYFxEQGBcREBgXEREXGBAR"
        "FxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxERFxgQERcYEBEXGBAQGAAAAQA4AAABWAIwAEMAAAAHIxYVFAcjFhUU"
        "ByMWFRQHIxYVFAczFhUUByEmNTQ3JjU0NzMmNTQ3MyY1NDczJjU0NzMmNTQ3IyY1NDchFhUUBxYVAVgEHgQEPAQEPAQEMgQEyAQE"
        "/ugEBAQEMgQEPAQEPAQEHgQEyAQEARgEBAQBoREQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEX"
        "GBAQGBcREBgAAAEAJAAAAWwBkABDAAAkFRQHIyY1NDcjJjU0NyMWFRQHMxYVFAcjJjU0NyMmNTQ3MyY1NDczJjU0NyMmNTQ3MxYV"
        "FAczFhUUBxYVFAcWFRQHMwFsBFAEBCgEBHgEBHgEBKAEBCgEBCgEBKAEBIwEBLQEBCgEBAQEBAQoQBgXEREXGBARFxgQEBgXERAY"
        "FxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEAAAIAJAAAAWwCgAATAFcAABMmNTQ3MyY1NDczFhUUByMWFRQH"
        "EhUUByMmNTQ3IyY1NDcjFhUUBzMWFRQHIyY1NDcjJjU0NzMmNTQ3MyY1NDcjJjU0NzMWFRQHMxYVFAcWFRQHFhUUBzOgBAQoBARQ"
        "BAQoBAR8BFAEBCgEBHgEBHgEBKAEBCgEBCgEBKAEBIwEBLQEBCgEBAQEBAQoAeARFxgQERcYEBAYFxEQGBcR/mAYFxERFxgQERcY"
        "EBAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcRAP//ACQAAAFsAoAAIgA9AAAAAwDbAZAAAAADACQA"
        "AAFsAjAACQATAFcAABMmNTQ3MxYVFAczJjU0NzMWFRQHEhUUByMmNTQ3IyY1NDcjFhUUBzMWFRQHIyY1NDcjJjU0NzMmNTQ3MyY1"
        "NDcjJjU0NzMWFRQHMxYVFAcWFRQHFhUUBzNQBARQBARQBARQBAQsBFAEBCgEBHgEBHgEBKAEBCgEBCgEBKAEBIwEBLQEBCgEBAQE"
        "BAQoAeARFxgQEBgXEREXGBAQGBcR/mAYFxERFxgQERcYEBAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQ"
        "GBcRAAACACQAAAFsAoAAEwBXAAATJjU0NzMWFRQHMxYVFAcjJjU0NxIVFAcjJjU0NyMmNTQ3IxYVFAczFhUUByMmNTQ3IyY1NDcz"
        "JjU0NzMmNTQ3IyY1NDczFhUUBzMWFRQHFhUUBxYVFAczeAQEUAQEKAQEUAQEzARQBAQoBAR4BAR4BASgBAQoBAQoBASgBASMBAS0"
        "BAQoBAQEBAQEKAIwERcYEBAYFxEQGBcRERcYEP4QGBcRERcYEBEXGBAQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAY"
        "FxEQGBcREBgXEQD//wAkAAABbALQACIAPQAAAAMA3AGQAAD//wAkAAABbAKAACIAPQAAAAMA3QGQAAAAAwAkAAABbAGQAEQATgBY"
        "AAAkByMWFRQHMxYVFAcjJjU0NyMWFRQHIyY1NDcjJjU0NzMmNTQ3MyY1NDcjJjU0NzMWFRQHMyY1NDczFhUUBzMWFRQHFhUnJjU0"
        "NyMWFRQHByY1NDcjFhUUBwFsBGQEBGQEBHgEBCgEBHgEBCgEBCgEBGQEBFAEBGQEBCgEBGQEBBQEBAQsBAQ8BARQBAQ8BASxERAY"
        "FxEQGBcRERcYEBAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxERFxgQEBgXERAYFxEQGCgRFxgQEBgXEaARFxgQEBgXEQADACQA"
        "AAFsAjAAPABkAG4AADYVFAcjFhUUByMmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3MxYVFAcWFRQHFhUUBzMWFRQHIxYVFAc2"
        "ByMWFRQHIyY1NDczJjU0NyMmNTQ3IyY1NDczFhUUBzMWFRQHMxYVBjczFhUUByMmNXwEKAQEKAQEBAQEBAQEBAQEBAQEUAQEBAQE"
        "BCgEBCgEBPQEKAQEUAQEKAQEKAQEUAQEeAQEKAQEKAT4BHgEBHgEkBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQ"
        "EBgXERAYFxEQGBcREBgXERAYFxERERAYFxERFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGIgQEBgXEREXAAEAJAAAAWwBkABFAAAl"
        "FhUUByMWFRQHIyY1NDcjJjU0NyMmNTQ3MyY1NDczJjU0NzMWFRQHMxYVFAcjJjU0NyMWFRQHIxYVFAczFhUUBzMmNTQ3AWgEBCgE"
        "BMgEBCgEBCgEBCgEBCgEBMgEBCgEBFAEBHgEBCgEBCgEBHgEBKAQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxER"
        "FxgQEBgXERAYFxEQGBcRERcYEP//ACT/YAFsAZAAIgBGAAAAAwDhAZAAAAACACQAAAFsAjAAPQBvAAAAFRQHFhUUBxYVFAcWFRQH"
        "FhUUBxYVFAcjJjU0NyMmNTQ3MyY1NDcjJjU0NzMmNTQ3JjU0NyY1NDczFhUUBwYHIxYVFAcjFhUUBzMWFRQHMxYVFAcjJjU0NyMm"
        "NTQ3IyY1NDczJjU0NzMmNTQ3MxYVAWwEBAQEBAQEBAQEBFAEBB4EBB4EBB4EBB4EBAQEBARQBAR+BGQEBB4EBB4EBGQEBG4EBDIE"
        "BB4EBB4EBDIEBG4EAdAYFxEQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcRjxEQGBcR"
        "EBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGAAAAwAkAAABbALQAFYAYAB8AAAAFRQHFhUUBxYVFAcjFhUUByMmNTQ3"
        "IyY1NDcjJjU0NzMmNTQ3MyY1NDczJjU0NzMmNTQ3IyY1NDczJjU0NzMWFRQHIxYVFAczFhUUBzMWFRQHMxYVFAcmFRQHMyY1NDcj"
        "EjU0NyY1NDcjFhUUByMWFRQHMxYVFAczJjU0NwFsBAQEBAQoBATIBAQyBAQeBAQeBAQyBAQeBAQoBARGBASCBAQ8BAQeBAQeBAQe"
        "BAQUBASSBEYEBEZCBAQEggQEHgQEHgQEggQEATAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcY"
        "EBEXGBAQGBcREBgXERAYFxEQGBcREBgXEZAYFxERFxgQ/tEXGBARFxgQEBgXERAYFxEQGBcRERcYEAAAAgAkAAABbAGQADAAOgAA"
        "AAcWFRQHIxYVFAczFhUUByMmNTQ3IyY1NDcjJjU0NzMmNTQ3MyY1NDczFhUUBzMWFQY1NDcjFhUUBzMBbAQEBNIEBKoEBMgEBDIE"
        "BB4EBB4EBDIEBMgEBCgEWASCBASCAQEREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXFxgQEBgXEQAAAwAk"
        "AAABbAKAABMARABOAAATJjU0NzMmNTQ3MxYVFAcjFhUUBxYHFhUUByMWFRQHMxYVFAcjJjU0NyMmNTQ3IyY1NDczJjU0NzMmNTQ3"
        "MxYVFAczFhUGNTQ3IxYVFAcztAQEKAQEUAQEKAQEaAQEBNIEBKoEBMgEBDIEBB4EBB4EBDIEBMgEBCgEWASCBASCAeARFxgQERcY"
        "EBAYFxEQGBcR3xEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcXGBAQGBcRAP//ACQAAAFsAoAAIgBKAAAA"
        "AwDbAaQAAAAEACQAAAFsAjAACQATAEQATgAAEyY1NDczFhUUBzMmNTQ3MxYVFAcWBxYVFAcjFhUUBzMWFRQHIyY1NDcjJjU0NyMm"
        "NTQ3MyY1NDczJjU0NzMWFRQHMxYVBjU0NyMWFRQHM2QEBFAEBFAEBFAEBBgEBATSBASqBATIBAQyBAQeBAQeBAQyBATIBAQoBFgE"
        "ggQEggHgERcYEBAYFxERFxgQEBgXEd8REBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXFxgQEBgXEQAAAwAk"
        "AAABbAKAABMARABOAAATJjU0NzMWFRQHMxYVFAcjJjU0NxIHFhUUByMWFRQHMxYVFAcjJjU0NyMmNTQ3IyY1NDczJjU0NzMmNTQ3"
        "MxYVFAczFhUGNTQ3IxYVFAczjAQEUAQEKAQEUAQEuAQEBNIEBKoEBMgEBDIEBB4EBB4EBDIEBMgEBCgEWASCBASCAjARFxgQEBgX"
        "ERAYFxERFxgQ/tEREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXFxgQEBgXEQABAEwAAAFEAjAAQQAAARYV"
        "FAcjFhUUBxYVFAcWFRQHMxYVFAcjJjU0NzMmNTQ3JjU0NyY1NDcjJjU0NzMmNTQ3MyY1NDczFhUUByMWFRQHAUAEBHgEBAQEBARQ"
        "BATIBAQoBAQEBAQEKAQEKAQEKAQEoAQEeAQEAZAQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEX"
        "GBAQGBcREBgXEQAAAQAk/2ABbAGQAGgAAAAVFAcWFRQHFhUUBxYVFAcjFhUUByMWFRQHIyY1NDczJjU0NzMmNTQ3IyY1NDczJjU0"
        "NyY1NDcjFhUUByMWFRQHMxYVFAczFhUUByMmNTQ3IyY1NDcjJjU0NzMmNTQ3MyY1NDczFhUUBwFsBAQEBAQEBCgEBCgEBKAEBHgE"
        "BCgEBCgEBCgEBAQEggQEHgQEHgQEWgQEeAQEMgQEHgQEHgQEMgQE8AQEATAYFxEQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQ"
        "ERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEAAgAkAAABbAIwADsAZwAAEgcz"
        "FhUUByMWFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NzMWFRQHFhUUBxYVFhUUBxYVFAcWFRQHIyY1NDcm"
        "NTQ3JjU0NyY1NDcjJjU0NzMWFRQHMxYVFAd8BB4EBB4EBAQEBARQBAQEBAQEBAQEBAQEBARQBAQEBATwBAQEBARQBAQEBAQEBASC"
        "BASgBAQyBAQBUREQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBiIGBcREBgXERAY"
        "FxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcRAAIATAAAAUQCMAAJADYAABMmNTQ3MxYVFAcSFRQHIyY1NDczJjU0NyY1NDcm"
        "NTQ3IyY1NDczFhUUBxYVFAcWFRQHFhUUBzOgBARQBARUBPAEBFAEBAQEBAQ8BASMBAQEBAQEBARQAeARFxgQEBgXEf5gGBcRERcY"
        "EBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcRAAABAEwAAAFEAZAALAAAJBUUByMmNTQ3MyY1NDcmNTQ3JjU0NyMmNTQ3"
        "MxYVFAcWFRQHFhUUBxYVFAczAUQE8AQEUAQEBAQEBDwEBIwEBAQEBAQEBFBAGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgX"
        "ERAYFxEQGBcRAAACAEwAAAFEAoAAEwBAAAATJjU0NzMmNTQ3MxYVFAcjFhUUBxIVFAcjJjU0NzMmNTQ3JjU0NyY1NDcjJjU0NzMW"
        "FRQHFhUUBxYVFAcWFRQHM6AEBCgEBFAEBCgEBFQE8AQEUAQEBAQEBDwEBIwEBAQEBAQEBFAB4BEXGBARFxgQEBgXERAYFxH+YBgX"
        "EREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXEQD//wBMAAABRAKAACIAUwAAAAMA2wGQAAAAAwBMAAABRAIwAAkA"
        "EwBAAAATJjU0NzMWFRQHMyY1NDczFhUUBxEWFRQHIyY1NDczJjU0NyY1NDcmNTQ3IyY1NDczFhUUBxYVFAcWFRQHFhUUB1AEBFAE"
        "BFAEBFAEBAQE8AQEUAQEBAQEBDwEBIwEBAQEBAQEBAHgERcYEBAYFxERFxgQEBgXEf5wEBgXEREXGBARFxgQERcYEBEXGBARFxgQ"
        "EBgXERAYFxEQGBcREBgXEQD//wBMAAABRAIwACIAUwAAAAMA2AGQAAAAAgBMAAABRAKAABMAQAAAEyY1NDczFhUUBzMWFRQHIyY1"
        "NDcSFRQHIyY1NDczJjU0NyY1NDcmNTQ3IyY1NDczFhUUBxYVFAcWFRQHFhUUBzN4BARQBAQoBARQBASkBPAEBFAEBAQEBAQ8BASM"
        "BAQEBAQEBARQAjARFxgQEBgXERAYFxERFxgQ/hAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEAAAIATP9g"
        "ARwCMAAJAEgAABMmNTQ3MxYVFAcWFRQHFhUUBxYVFAcWFRQHFhUUByMWFRQHIxYVFAcjJjU0NzMmNTQ3MyY1NDcmNTQ3JjU0NyY1"
        "NDcjJjU0NzPIBARQBAQEBAQEBAQEBAQEKAQEKAQEeAQEUAQEKAQEBAQEBAQEUAQEoAHgERcYEBAYFxFgGBcREBgXERAYFxEQGBcR"
        "EBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEAABAEz/YAEcAZAAPgAAABUUBxYVFAcWFRQHFhUUByMWFRQH"
        "IxYVFAcjJjU0NzMmNTQ3MyY1NDcmNTQ3JjU0NyY1NDcjJjU0NzMWFRQHARwEBAQEBAQEKAQEKAQEeAQEUAQEKAQEBAQEBAQEUAQE"
        "oAQEATAYFxEQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcRAAEAJAAAAWwCMABjAAAk"
        "FRQHIyY1NDcjJjU0NyMWFRQHFhUUByMmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3MxYVFAcWFRQHFhUUBxYVFAczJjU0NzMm"
        "NTQ3MxYVFAcjFhUUByMWFRQHMxYVFAczAWwEjAQEKAQEPAQEBARQBAQEBAQEBAQEBAQEBARQBAQEBAQEBAQ8BAQoBAR4BARQBAQo"
        "BAQoBARkQBgXEREXGBARFxgQEBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXEREXGBAR"
        "FxgQEBgXERAYFxEQGBcREBgXEQAAAQBMAAABRAIwADwAACQVFAcjJjU0NzMmNTQ3JjU0NyY1NDcmNTQ3JjU0NyMmNTQ3MxYVFAcW"
        "FRQHFhUUBxYVFAcWFRQHFhUUBzMBRATwBARQBAQEBAQEBAQEBDwEBIwEBAQEBAQEBAQEBARQQBgXEREXGBARFxgQERcYEBEXGBAR"
        "FxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYFxEAAAMAJAAAAWwBkAAqAFYAggAAEgczFhUUBxYVFAcWFRQHFhUUByMm"
        "NTQ3JjU0NyY1NDcmNTQ3JjU0NzMWFRYHMxYVFAcWFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyMmNTQ3MxYVFhUUBxYVFAcW"
        "FRQHIyY1NDcmNTQ3JjU0NyY1NDcjJjU0NzMWFRQHMxYVFAdeBB4EBAQEBAQEBFAEBAQEBAQEBAQEMgRuBB4EBAQEBAQEBDwEBAQE"
        "BAQEBDIEBFAEoAQEBAQEUAQEBAQEBAQEMgQEWgQEKAQEAVEREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgX"
        "ERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYiBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcR"
        "EBgXEQAAAgAkAAABbAGQACsAVwAAEgczFhUUByMWFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDczFhUWFRQHFhUUBxYV"
        "FAcjJjU0NyY1NDcmNTQ3JjU0NyMmNTQ3MxYVFAczFhUUB3IEKAQEHgQEBAQEBFAEBAQEBAQEBAQERgT6BAQEBARQBAQEBAQEBASC"
        "BASgBAQyBAQBUREQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGIgYFxEQGBcREBgXEREXGBARFxgQERcYEBEX"
        "GBARFxgQEBgXERAYFxH//wAkAAABbAKAACIAXgAAAAMA3QGQAAAAAgAkAAABbAGQADEATwAAJAcjFhUUByMWFRQHIyY1NDcjJjU0"
        "NyMmNTQ3MyY1NDczJjU0NzMWFRQHMxYVFAczFhUHJjU0NyMmNTQ3IxYVFAcjFhUUBzMWFRQHMyY1NDcBbAQeBAQyBASgBAQyBAQe"
        "BAQeBAQyBASgBAQyBAQeBFQEBB4EBGQEBB4EBB4EBGQEBLEREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgo"
        "ERcYEBEXGBAQGBcREBgXERAYFxERFxgQAAADACQAAAFsAoAAEwBFAGMAABMmNTQ3MyY1NDczFhUUByMWFRQHEgcjFhUUByMWFRQH"
        "IyY1NDcjJjU0NyMmNTQ3MyY1NDczJjU0NzMWFRQHMxYVFAczFhUHJjU0NyMmNTQ3IxYVFAcjFhUUBzMWFRQHMyY1NDegBAQoBARQ"
        "BAQoBAR8BB4EBDIEBKAEBDIEBB4EBB4EBDIEBKAEBDIEBB4EVAQEHgQEZAQEHgQEHgQEZAQEAeARFxgQERcYEBAYFxEQGBcR/tER"
        "EBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgoERcYEBEXGBAQGBcREBgXERAYFxERFxgQAP//ACQAAAFsAoAA"
        "IgBgAAAAAwDbAZAAAAAEACQAAAFsAjAACQATAEUAYwAAEyY1NDczFhUUBzMmNTQ3MxYVFAcSByMWFRQHIxYVFAcjJjU0NyMmNTQ3"
        "IyY1NDczJjU0NzMmNTQ3MxYVFAczFhUUBzMWFQcmNTQ3IyY1NDcjFhUUByMWFRQHMxYVFAczJjU0N1AEBFAEBFAEBFAEBCwEHgQE"
        "MgQEoAQEMgQEHgQEHgQEMgQEoAQEMgQEHgRUBAQeBARkBAQeBAQeBARkBAQB4BEXGBAQGBcRERcYEBAYFxH+0REQGBcREBgXEREX"
        "GBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGCgRFxgQERcYEBAYFxEQGBcREBgXEREXGBAAAAMAJAAAAWwCgAATAEUAYwAAEyY1"
        "NDczFhUUBzMWFRQHIyY1NDcSByMWFRQHIxYVFAcjJjU0NyMmNTQ3IyY1NDczJjU0NzMmNTQ3MxYVFAczFhUUBzMWFQcmNTQ3IyY1"
        "NDcjFhUUByMWFRQHMxYVFAczJjU0N3gEBFAEBCgEBFAEBMwEHgQEMgQEoAQEMgQEHgQEHgQEMgQEoAQEMgQEHgRUBAQeBARkBAQe"
        "BAQeBARkBAQCMBEXGBAQGBcREBgXEREXGBD+gREQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGCgRFxgQERcY"
        "EBAYFxEQGBcREBgXEREXGBAAAAMAJP+wAWwB4ABFAGMAbQAAJAcjFhUUByMWFRQHIxYVFAcjJjU0NzMmNTQ3IyY1NDcjJjU0NzMm"
        "NTQ3MyY1NDczJjU0NzMWFRQHIxYVFAczFhUUBzMWFQcmNTQ3IyY1NDcjFhUUByMWFRQHMxYVFAczJjU0NyYHIyY1NDczFhUBbAQe"
        "BAQyBASMBARQBAQoBAQeBAQeBAQeBAQyBASMBARQBAQoBAQeBAQeBFQEBDIEBFAEBB4EBDIEBFAEBBAEPAQEPASxERAYFxEQGBcR"
        "EBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGCgRFxgQERcYEBAYFxEQGBcREBgXEREXGBAREREX"
        "GBAQGP//ACQAAAFsAoAAIgBgAAAAAwDdAZAAAAADACQAAAFsAZAAQgBcAGYAACQHIxYVFAczFhUUByMmNTQ3IxYVFAcjJjU0NyMm"
        "NTQ3JjU0NyY1NDczJjU0NzMWFRQHMyY1NDczFhUUBzMWFRQHFhUGNTQ3JjU0NyY1NDcjFhUUBxYVFAcWFRQHMzcmNTQ3IxYVFAcB"
        "bARkBARkBAR4BAQoBAR4BAQoBAQEBAQEKAQEeAQEKAQEZAQEFAQEBLwEBAQEBDwEBAQEBAQ8jAQEPAQEsREQGBcREBgXEREXGBAQ"
        "GBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcRERcYEBAYFxEQGBcREBhnFxgQERcYEBEXGBAQGBcREBgXERAYFxGgERcYEBAYFxEA"
        "AAEAJP9gAWwBkABlAAAkByMWFRQHIxYVFAcjFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NzMWFRQHMxYVFAcj"
        "FhUUBxYVFAczJjU0NzMmNTQ3IyY1NDcjJjU0NzMWFRQHMxYVFAczFhUBbAQoBAQoBASgBAQEBFAEBAQEBAQEBAQEBAQEBFAEBCgE"
        "BCgEBAQEeAQEKAQEKAQEUAQEeAQEKAQEKASxERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgX"
        "ERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBAQGBcREBgXERAYAAIAJP9gAWwCMABPAGsAACQHIxYVFAcjFhUUByMWFRQHFhUU"
        "ByMmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDczFhUUBxYVFAczFhUUBzMWFRQHMxYVByY1NDcjJjU0NyMWFRQH"
        "FhUUBxYVFAczJjU0NwFsBCgEBCgEBKAEBAQEUAQEBAQEBAQEBAQEBAQEBAQEBFAEBAQEoAQEKAQEKARUBAQoBAR4BAQEBAQEeAQE"
        "sREQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXERAYKBEX"
        "GBARFxgQEBgXERAYFxEQGBcRERcYEAAAAQAk/2ABbAGQAGQAAAAVFAcWFRQHFhUUBxYVFAcWFRQHFhUUByMmNTQ3JjU0NyY1NDcj"
        "JjU0NzMmNTQ3JjU0NyMWFRQHIxYVFAczFhUUBzMWFRQHIyY1NDcjJjU0NyMmNTQ3MyY1NDczJjU0NzMWFRQHAWwEBAQEBAQEBAQE"
        "BFAEBAQEBAQoBAQoBAQEBHgEBCgEBCgEBFAEBHgEBCgEBCgEBCgEBCgEBPAEBAEwGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQ"
        "ERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcRAAEAJAAAAWwBkABCAAAA"
        "FRQHIyY1NDcjFhUUByMWFRQHFhUUBzMWFRQHIyY1NDczJjU0NyY1NDcmNTQ3IyY1NDczFhUUBzMmNTQ3MxYVFAczAWwEUAQERgQE"
        "HgQEBAQ8BATIBAQ8BAQEBAQEPAQEZAQEKAQElgQEHgEwGBcRERcYEBAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcY"
        "EBAYFxERFxgQEBgXEQABADgAAAFYAZAAMQAAJAcjFhUUByMmNTQ3MyY1NDcjJjU0NyMmNTQ3MyY1NDczFhUUByMWFRQHMxYVFAcz"
        "FhUBWAQoBATcBAS0BASgBAQoBAQoBATcBAS0BASgBAQoBGEREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgA"
        "AQAkAAABbAIwAHYAAAAHIxYVFAczFhUUBxYVFAcjFhUUByMmNTQ3MyY1NDcmNTQ3IyY1NDczJjU0NyY1NDcjFhUUBxYVFAcWFRQH"
        "FhUUBxYVFAcWFRQHIyY1NDczJjU0NyY1NDcmNTQ3IyY1NDczJjU0NzMmNTQ3MxYVFAczFhUUBxYVAWwEKAQEKAQEBAQoBAR4BARQ"
        "BAQEBFAEBFAEBAQEeAQEBAQEBAQEBAQEBHgEBCgEBAQEBAQoBAQoBAQoBATIBAQoBAQEAVEREBgXERAYFxEQGBcREBgXEREXGBAR"
        "FxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcR"
        "EBgXERAYAAABACQAAAFEAjAAPwAAJRYVFAcjJjU0NyMmNTQ3JjU0NyY1NDcjJjU0NzMmNTQ3JjU0NzMWFRQHFhUUBzMWFRQHIxYV"
        "FAcWFRQHFhUUBwFABASgBAQoBAQEBAQEUAQEUAQEBARQBAQEBHgEBHgEBAQEBARQEBgXEREXGBARFxgQERcYEBEXGBARFxgQERcY"
        "EBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYFxEAAgAkAAABbAGQACwAWAAANgczFhUUByMmNTQ3IyY1NDcmNTQ3JjU0NyY1NDcz"
        "FhUUBxYVFAcWFRQHMxYVNhUUBxYVFAcWFRQHFhUUByMmNTQ3IyY1NDczJjU0NyY1NDcmNTQ3MxYVFAeaBGQEBKAEBDIEBAQEBAQE"
        "BFAEBAQEBAQeBNIEBAQEBAQEUAQEHgQEHgQEBAQEBFAEBGEREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBi4"
        "GBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcRAAADACQAAAFsAoAAEwBAAGwAABMmNTQ3MyY1NDczFhUUByMW"
        "FRQHAgczFhUUByMmNTQ3IyY1NDcmNTQ3JjU0NyY1NDczFhUUBxYVFAcWFRQHMxYVNhUUBxYVFAcWFRQHFhUUByMmNTQ3IyY1NDcz"
        "JjU0NyY1NDcmNTQ3MxYVFAegBAQoBARQBAQoBARWBGQEBKAEBDIEBAQEBAQEBFAEBAQEBAQeBNIEBAQEBAQEUAQEHgQEHgQEBAQE"
        "BFAEBAHgERcYEBEXGBAQGBcREBgXEf6BERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYuBgXERAYFxEQGBcR"
        "EBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXEf//ACQAAAFsAoAAIgBvAAAAAwDbAZAAAAAEACQAAAFsAjAACQATAEAAbAAAEyY1"
        "NDczFhUUBzMmNTQ3MxYVFAcCBzMWFRQHIyY1NDcjJjU0NyY1NDcmNTQ3JjU0NzMWFRQHFhUUBxYVFAczFhU2FRQHFhUUBxYVFAcW"
        "FRQHIyY1NDcjJjU0NzMmNTQ3JjU0NyY1NDczFhUUB1AEBFAEBFAEBFAEBKYEZAQEoAQEMgQEBAQEBAQEUAQEBAQEBB4E0gQEBAQE"
        "BARQBAQeBAQeBAQEBAQEUAQEAeARFxgQEBgXEREXGBAQGBcR/oEREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcR"
        "EBi4GBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcRAAMAJAAAAWwCgAATAEAAbAAAEyY1NDczFhUUBzMWFRQH"
        "IyY1NDcCBzMWFRQHIyY1NDcjJjU0NyY1NDcmNTQ3JjU0NzMWFRQHFhUUBxYVFAczFhU2FRQHFhUUBxYVFAcWFRQHIyY1NDcjJjU0"
        "NzMmNTQ3JjU0NyY1NDczFhUUB3gEBFAEBCgEBFAEBAYEZAQEoAQEMgQEBAQEBAQEUAQEBAQEBB4E0gQEBAQEBARQBAQeBAQeBAQE"
        "BAQEUAQEAjARFxgQEBgXERAYFxERFxgQ/jEREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBi4GBcREBgXERAY"
        "FxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcRAAEAJAAAAWwBkABPAAAAByMWFRQHIxYVFAcjFhUUByMWFRQHIyY1NDcjJjU0"
        "NyMmNTQ3IyY1NDcjJjU0NzMWFRQHMxYVFAczFhUUBzMmNTQ3MyY1NDczJjU0NzMWFQFsBB4EBB4EBBQEBCgEBFAEBCgEBBQEBB4E"
        "BB4EBFAEBB4EBB4EBCgEBB4EBB4EBFAEAVEREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcR"
        "ERcYEBEXGBARFxgQEBgAAAEAJAAAAWwBkAB3AAAABxYVFAcjFhUUBxYVFAcjFhUUByMmNTQ3IyY1NDcjFhUUByMWFRQHIyY1NDcj"
        "JjU0NyY1NDcjJjU0NyY1NDczFhUUBxYVFAcWFRQHMyY1NDczJjU0NyY1NDczFhUUBxYVFAczFhUUBzMmNTQ3JjU0NyY1NDczFhUB"
        "bAQEBB4EBAQEFAQEPAQEFAQEPAQEFAQEPAQEFAQEBAQeBAQEBFAEBAQEBAQeBAQUBAQEBDwEBAQEFAQEHgQEBAQEBFAEAVEREBgX"
        "ERAYFxEQGBcREBgXEREXGBARFxgQEBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXEREXGBARFxgQERcYEBAY"
        "FxEQGBcREBgXEREXGBARFxgQERcYEBAYAAABADgAAAFYAZAAWQAAJRYVFAcjJjU0NyMmNTQ3IxYVFAcjFhUUByMmNTQ3MyY1NDcz"
        "JjU0NyMmNTQ3IyY1NDczFhUUBzMWFRQHMyY1NDczJjU0NzMWFRQHIxYVFAcjFhUUBzMWFRQHAVQEBFAEBB4EBDIEBCgEBFAEBCgE"
        "BCgEBCgEBCgEBFAEBCgEBDIEBB4EBFAEBB4EBDIEBDIEBFAQGBcRERcYEBEXGBAQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQ"
        "EBgXERAYFxERFxgQERcYEBAYFxEQGBcREBgXERAYFxEAAQAa/2ABbAGQAGsAAAAHIxYVFAcjFhUUByMWFRQHIxYVFAcjFhUUByMW"
        "FRQHIyY1NDczJjU0NyY1NDcjJjU0NyMmNTQ3IyY1NDcjJjU0NzMWFRQHMxYVFAczFhUUBxYVFAczJjU0NzMmNTQ3MyY1NDczJjU0"
        "NzMWFQFsBB4EBB4EBBQEBB4EBBQEBCgEBHgEBFAEBAQEKAQEFAQEHgQEHgQEUAQEHgQEHgQEBAQeBAQUBAQeBAQeBARQBAFRERAY"
        "FxEQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcRERcYEBEXGBAR"
        "FxgQERcYEBAYAAACABr/YAFsAoAAEwB/AAATJjU0NzMmNTQ3MxYVFAcjFhUUBxYHIxYVFAcjFhUUByMWFRQHIxYVFAcjFhUUByMW"
        "FRQHIyY1NDczJjU0NyY1NDcjJjU0NyMmNTQ3IyY1NDcjJjU0NzMWFRQHMxYVFAczFhUUBxYVFAczJjU0NzMmNTQ3MyY1NDczJjU0"
        "NzMWFaAEBCgEBFAEBCgEBHwEHgQEHgQEFAQEHgQEFAQEKAQEeAQEUAQEBAQoBAQUBAQeBAQeBARQBAQeBAQeBAQEBB4EBBQEBB4E"
        "BB4EBFAEAeARFxgQERcYEBAYFxEQGBcRjxEQGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBAR"
        "FxgQEBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBAQGAAAAwAa/2ABbAIwAAkAEwB/AAATJjU0NzMWFRQHMyY1NDczFhUU"
        "BxYHIxYVFAcjFhUUByMWFRQHIxYVFAcjFhUUByMWFRQHIyY1NDczJjU0NyY1NDcjJjU0NyMmNTQ3IyY1NDcjJjU0NzMWFRQHMxYV"
        "FAczFhUUBxYVFAczJjU0NzMmNTQ3MyY1NDczJjU0NzMWFVAEBFAEBFAEBFAEBCwEHgQEHgQEFAQEHgQEFAQEKAQEeAQEUAQEBAQo"
        "BAQUBAQeBAQeBARQBAQeBAQeBAQEBB4EBBQEBB4EBB4EBFAEAeARFxgQEBgXEREXGBAQGBcRjxEQGBcREBgXERAYFxEQGBcREBgX"
        "ERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBAQGAAAAwA4AAAB"
        "WAGQABMAHQAwAAAAByMmNTQ3IyY1NDchFhUUByMWFQYHIyY1NDczFhUWFRQHISY1NDcmNTQ3MxYVFAczATAEUAQEoAQEARgEBCgE"
        "UARQBARQBHgE/ugEBAQEUAQEyAEBEREXGBARFxgQEBgXERAYZxERFxgQEBiIGBcRERcYEBEXGBAQGBcRAAEAJAAAAWwCMAB1AAAA"
        "ByMWFRQHFhUUBxYVFAcWFRQHIyY1NDcmNTQ3JjU0NyY1NDcjFhUUBxYVFAcWFRQHFhUUByMmNTQ3JjU0NyY1NDcmNTQ3IyY1NDcz"
        "JjU0NzMmNTQ3MxYVFAcjFhUUBzMmNTQ3MyY1NDczFhUUByMWFRQHMxYVAWwEMgQEBAQEBAQEUAQEBAQEBAQERgQEBAQEBAQEUAQE"
        "BAQEBAQEKAQEKAQEKAQEUAQEKAQERgQEKAQEUAQEKAQEMgQBUREQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBAYFxEQ"
        "GBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxERFxgQERcYEBAYFxEQGBcREBgAAAEAJAAAAWwC"
        "MABiAAAAFRQHFhUUBxYVFAcWFRQHIyY1NDcmNTQ3JjU0NyY1NDcjFhUUBxYVFAcWFRQHMxYVFAcjJjU0NzMmNTQ3JjU0NyY1NDcj"
        "JjU0NzMmNTQ3MyY1NDczFhUUByMWFRQHMxYVFAcBbAQEBAQEBARQBAQEBAQEBAR4BAQEBAQEKAQEoAQEKAQEBAQEBCgEBCgEBCgE"
        "BKAEBHgEBMgEBAEwGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQ"
        "ERcYEBEXGBARFxgQEBgXERAYFxEQGBcRAAEAJAAAAWwCMAByAAAAFRQHFhUUBxYVFAcWFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3"
        "JjU0NyY1NDcmNTQ3IxYVFAczFhUUByMWFRQHFhUUBxYVFAczFhUUByMmNTQ3MyY1NDcmNTQ3JjU0NyMmNTQ3MyY1NDczJjU0NzMW"
        "FRQHAWwEBAQEBAQEBAQEBFAEBAQEBAQEBAQEBAR4BAQoBAQoBAQEBAQEKAQEoAQEKAQEBAQEBCgEBCgEBCgEBPAEBAHQGBcREBgX"
        "ERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEX"
        "GBARFxgQERcYEBEXGBARFxgQEBgXEQADAFYAAAE6AjAALgA4AEIAAAAVFAcWFRQHFhUUByMmNTQ3IyY1NDczJjU0NzMmNTQ3IyY1"
        "NDczFhUUBzMWFRQHBjU0NyMWFRQHMxYVFAcjJjU0NzMBOgQEBAQEvgQEHgQEHgQEggQEbgQEjAQEHgQEQARkBARkQATcBATcAYAY"
        "FxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxGPFxgQEBgXEbAYFxERFxgQAAMAVgAAAToCMAAtAEcAUQAAABUU"
        "BxYVFAcjFhUUByMmNTQ3IyY1NDcmNTQ3JjU0NzMmNTQ3MxYVFAczFhUUBwY1NDcmNTQ3JjU0NyMWFRQHFhUUBxYVFAczFhUUByMm"
        "NTQ3MwE6BAQEHgQEoAQEHgQEBAQEBB4EBKAEBB4EBEAEBAQEBGQEBAQEBARkQATcBATcAYAYFxEQGBcREBgXEREXGBARFxgQERcY"
        "EBEXGBARFxgQEBgXERAYFxGPFxgQERcYEBEXGBAQGBcREBgXERAYFxGwGBcRERcYEAAEAEIAAAFOAjAACQA1AGEAawAAEgcjJjU0"
        "NzMWFQIVFAcjJjU0NyMmNTQ3JjU0NyY1NDczJjU0NzMWFRQHFhUUBxYVFAcWFRQHNhUUBxYVFAcjFhUUByMmNTQ3JjU0NyY1NDcm"
        "NTQ3JjU0NzMWFRQHMxYVFAcCNzMWFRQHIyY1/gRkBARkBGQEMgQEHgQEBAQEBB4EBDIEBAQEBAQEBLgEBAQeBAQyBAQEBAQEBAQE"
        "BDIEBB4EBLgEZAQEZAQB8RERFxgQEBj+iBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXEZAYFxEQGBcREBgX"
        "EREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxH/ABAQGBcRERcAAAEATAAAAUQCMAA9AAAkFRQHIyY1NDczJjU0NyY1NDcmNTQ3"
        "JjU0NyMmNTQ3MyY1NDczFhUUBxYVFAcWFRQHFhUUBxYVFAcWFRQHMwFEBPAEBFAEBAQEBAQEBDwEBDwEBFAEBAQEBAQEBAQEBARQ"
        "QBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYFxEAAAEAOAAAAVgCMABNAAAAByMW"
        "FRQHIxYVFAcjFhUUBzMWFRQHISY1NDczJjU0NzMmNTQ3MyY1NDczJjU0NyY1NDcjFhUUByMmNTQ3MyY1NDczFhUUBzMWFRQHFhUB"
        "WAQyBAQyBAQyBASWBAT+6AQEMgQEMgQEMgQEMgQEBASMBAQ8BAQoBATIBAQoBAQEAVEREBgXERAYFxEQGBcREBgXEREXGBARFxgQ"
        "ERcYEBEXGBARFxgQERcYEBAYFxERFxgQERcYEBAYFxEQGBcREBgAAQA4AAABWAIwAFUAAAAHIxYVFAczFhUUBxYVFAcjFhUUByMm"
        "NTQ3IyY1NDczFhUUBzMmNTQ3JjU0NyMmNTQ3MyY1NDcmNTQ3IxYVFAcjJjU0NzMmNTQ3MxYVFAczFhUUBxYVAVgEKAQEKAQEBAQo"
        "BATIBAQoBARQBAR4BAQEBGQEBGQEBAQEeAQEUAQEKAQEyAQEKAQEBAFRERAYFxEQGBcREBgXERAYFxERFxgQERcYEBAYFxERFxgQ"
        "ERcYEBEXGBARFxgQERcYEBAYFxERFxgQERcYEBAYFxEQGBcREBgAAAEAJAAAAWwCMABcAAAkByMWFRQHFhUUByMmNTQ3JjU0NyMm"
        "NTQ3MyY1NDczJjU0NzMmNTQ3MxYVFAcjFhUUByMWFRQHMyY1NDcmNTQ3JjU0NyMmNTQ3MxYVFAcWFRQHFhUUBxYVFAczFhUBbAQo"
        "BAQEBFAEBAQEyAQEHgQEHgQEHgQEMgQEHgQEHgQEeAQEBAQEBDwEBIwEBAQEBAQEBCgEsREQGBcREBgXEREXGBARFxgQERcYEBEX"
        "GBARFxgQERcYEBAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgAAgA4AAABbAIwACMAXwAAEgcz"
        "FhUUByMmNTQ3JjU0NyY1NDcmNTQ3IRYVFAcjFhUUBxYVFgcjFhUUByMWFRQHIyY1NDcjJjU0NzMWFRQHMyY1NDczJjU0NyMmNTQ3"
        "IyY1NDczFhUUBzMWFRQHMxYVkAQeBARuBAQEBAQEBAQBDgQEvgQEBNwEHgQEMgQEtAQEKAQEPAQEggQEHgQEHgQEUAQEbgQEMgQE"
        "HgQBUREQGBcRERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBi3ERAYFxEQGBcRERcYEBEXGBAQGBcRERcYEBEXGBARFxgQERcYEBAY"
        "FxEQGBcREBgAAwAzAAABXQIwAAkANwBdAAAAByMmNTQ3MxYVAhUUByMmNTQ3IyY1NDcmNTQ3JjU0NzMmNTQ3MxYVFAcjFhUUBxYV"
        "FAczFhUUBzYHFhUUByMWFRQHIyY1NDczJjU0NyY1NDcjJjU0NzMWFRQHMxYVATUEjAQEjASMBFAEBB4EBAQEBAQeBARQBAQeBAQE"
        "BB4EBLgEBAQ8BAR4BARkBAQEBGQEBIwEBCgEAfERERcYEBAY/ogYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAY"
        "FxERERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBAYFxEQGAAAAQA4AAABWAIwAEQAAAAHFhUUByMWFRQHIxYVFAcjFhUUByMWFRQH"
        "IxYVFAcjJjU0NzMmNTQ3MyY1NDczJjU0NzMmNTQ3MyY1NDcjJjU0NyEWFQFYBAQEHgQEHgQEHgQEHgQEHgQEUAQEHgQEHgQEHgQE"
        "HgQEHgQEyAQEARgEAfEREBgXERAYFxEQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYAAMAQgAA"
        "AU4CMABBAFMAZQAAAAcjFhUUBzMWFRQHFhUUByMWFRQHIyY1NDcjJjU0NyY1NDczJjU0NyMmNTQ3JjU0NzMmNTQ3MxYVFAczFhUU"
        "BxYVBjU0NyY1NDcjFhUUBxYVFAczBjU0NyMWFRQHFhUUBzMmNTQ3AU4EMgQEMgQEBAQyBASgBAQyBAQEBDIEBDIEBAQEMgQEoAQE"
        "MgQEBFgEBARkBAQEBGQEBGQEBAQEZAQEAVEREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcR"
        "EBgXERAYFxcYEBEXGBAQGBcREBgXEY8XGBAQGBcREBgXEREXGBAAAAMAMwAAAV0CMAAlAFMAXQAAEgczFhUUByMmNTQ3IyY1NDcm"
        "NTQ3MyY1NDczFhUUByMWFRQHFhUWFRQHFhUUByMWFRQHIyY1NDczJjU0NyY1NDcjJjU0NyY1NDczFhUUBzMWFRQHAjczFhUUByMm"
        "NYsEZAQEjAQEKAQEBAQ8BAR4BARkBAQE0gQEBB4EBFAEBB4EBAQEHgQEBARQBAQeBAT+BIwEBIwEAVEREBgXEREXGBARFxgQERcY"
        "EBEXGBAQGBcREBgXERAYOBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXEf8AEBAYFxERFwABAH4A8ADqAoAA"
        "KwAAEhUUBxYVFAcWFRQHFhUUByMmNTQ3JjU0NyY1NDcjJjU0NzMmNTQ3MxYVFAfqBAQEBAQEBDwEBAQEBAQoBAQoBAQ8BAQCIBgX"
        "ERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXEQAAAQB0APABHAKAADEAAAEWFRQHIyY1NDczJjU0NzMmNTQ3MyY1"
        "NDcjJjU0NzMWFRQHMxYVFAcjFhUUByMWFRQHARgEBKAEBCgEBB4EBB4EBGQEBIIEBB4EBB4EBB4EBAFAEBgXEREXGBARFxgQERcY"
        "EBEXGBARFxgQEBgXERAYFxEQGBcREBgXEQAAAQB0APABHAKAADEAAAEWFRQHIxYVFAcjJjU0NzMmNTQ3IyY1NDczJjU0NyMmNTQ3"
        "MxYVFAczFhUUByMWFRQHARgEBB4EBIIEBGQEBEYEBEYEBGQEBIIEBB4EBB4EBAGQEBgXERAYFxERFxgQERcYEBEXGBARFxgQERcY"
        "EBAYFxEQGBcREBgXEQAAAQBbAFABNQIwADsAAAAHIxYVFAcjFhUUByMWFRQHIxYVFAcjFhUUByMmNTQ3MyY1NDczJjU0NzMmNTQ3"
        "MyY1NDczJjU0NzMWFQE1BB4EBB4EBB4EBB4EBB4EBDwEBB4EBB4EBB4EBB4EBB4EBDwEAfEREBgXERAYFxEQGBcREBgXERAYFxER"
        "FxgQERcYEBEXGBARFxgQERcYEBEXGBAQGAAAAgAVAAABbAKAACsAjwAAEhUUByMmNTQ3JjU0NyY1NDcjJjU0NzMmNTQ3MxYVFAcW"
        "FRQHFhUUBxYVFAcXFhUUByMmNTQ3MyY1NDczJjU0NzMmNTQ3IxYVFAcjFhUUByMWFRQHIyY1NDczJjU0NzMmNTQ3MyY1NDczJjU0"
        "NzMmNTQ3MxYVFAcjFhUUBzMWFRQHMxYVFAcjFhUUByMWFRQHgQQ8BAQEBAQEKAQEKAQEPAQEBAQEBAQE6wQEoAQEKAQEHgQEHgQE"
        "VQQEHgQEHgQEPAQEHgQEHgQEHgQEHgQEHgQEPAQEHgQENwQEHgQEHgQEHgQEATAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQ"
        "GBcREBgXERAYFxHwEBgXEREXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgX"
        "ERAYFxEQGBcREBgXERAYFxEABAAV/7ABgAKAACsAZwCXAKoAABIVFAcjJjU0NyY1NDcmNTQ3IyY1NDczJjU0NzMWFRQHFhUUBxYV"
        "FAcWFRQHFxYVFAcjFhUUByMmNTQ3MyY1NDczJjU0NzMmNTQ3MyY1NDczJjU0NzMWFRQHIxYVFAcjFhUUByMWFRQHFgcjFhUUByMm"
        "NTQ3IyY1NDczJjU0NzMmNTQ3MyY1NDczFhUUBxYVFAcWFRQHMxYVJhUUBzMmNTQ3JjU0NyMWFRQHI4EEPAQEBAQEBCgEBCgEBDwE"
        "BAQEBAQEBDwEBB4EBDwEBB4EBB4EBB4EBB4EBB4EBDwEBB4EBB4EBB4EBKkEFAQEPAQEZAQEFAQEFAQEFAQEZAQEBAQEBBQEeAQo"
        "BAQEBBQEBBQBMBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXEVAQGBcREBgXEREXGBARFxgQERcYEBEXGBAR"
        "FxgQERcYEBAYFxEQGBcREBgXERAYFxHfERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYaBgXEREXGBARFxgQ"
        "EBgXEQAAAwAk/7ABgAKAAFkAiQCcAAA3FhUUByMWFRQHIyY1NDczJjU0NyMmNTQ3MyY1NDcjJjU0NzMmNTQ3IyY1NDczFhUUBzMW"
        "FRQHIxYVFAczJjU0NzMmNTQ3MxYVFAcjFhUUByMWFRQHIxYVFAcWByMWFRQHIyY1NDcjJjU0NzMmNTQ3MyY1NDczJjU0NzMWFRQH"
        "FhUUBxYVFAczFhUmFRQHMyY1NDcmNTQ3IxYVFAcjuQQEHgQEPAQEHgQEVQQEZAQERgQERgQEZAQEggQEHgQEHgQELQQEHgQEPAQE"
        "HgQEHgQEHgQEqQQUBAQ8BARkBAQUBAQUBAQUBARkBAQEBAQEFAR4BCgEBAQEFAQEFPAQGBcREBgXEREXGBARFxgQERcYEBEXGBAR"
        "FxgQERcYEBEXGBAQGBcREBgXERAYFxERFxgQERcYEBAYFxEQGBcREBgXERAYFxHfERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAY"
        "FxEQGBcREBgXERAYaBgXEREXGBARFxgQEBgXEQAFADgAUAFYAeAALQA3AEEASwBVAAAAFRQHIxYVFAcWFRQHIyY1NDcmNTQ3IyY1"
        "NDczJjU0NyY1NDczFhUUBxYVFAczJhUUByMmNTQ3MxYHIyY1NDczFhUENzMWFRQHIyY1JRYVFAcjJjU0NwEIBB4EBAQEPAQEBAQe"
        "BAQeBAQEBDwEBAQEHnQEUAQEUMwEUAQEUAT+4ARQBARQBAEcBARQBAQBMBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQ"
        "GBcREBgXEUAYFxERFxgQPxERFxgQEBiIEBAYFxERFygQGBcRERcYEAAAAQAk/7ABbAKAAFkAAAQVFAcjJjU0NyMmNTQ3IyY1NDcj"
        "JjU0NyMmNTQ3IyY1NDcjJjU0NyMmNTQ3IyY1NDczFhUUBzMWFRQHMxYVFAczFhUUBzMWFRQHMxYVFAczFhUUBzMWFRQHMwFsBFAE"
        "BB4EBB4EBB4EBB4EBB4EBB4EBB4EBB4EBFAEBB4EBB4EBB4EBB4EBB4EBB4EBB4EBB4QGBcRERcYEBEXGBARFxgQERcYEBEXGBAR"
        "FxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXERAYFxEQGBcREBgXERAYFxEAAAEAkgCgAP4BQAARAAASBxYVFAcjJjU0NyY1"
        "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"
        "GBAQGP7YGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEAABACT/sAFsAoAAWQAAAAcjFhUUByMWFRQHIxYVFAcjFhUUByMW"
        "FRQHIxYVFAcjFhUUByMWFRQHIyY1NDczJjU0NzMmNTQ3MyY1NDczJjU0NzMmNTQ3MyY1NDczJjU0NzMmNTQ3MxYVAWwEHgQEHgQE"
        "HgQEHgQEHgQEHgQEHgQEHgQEUAQEHgQEHgQEHgQEHgQEHgQEHgQEHgQEHgQEUAQCQREQGBcREBgXERAYFxEQGBcREBgXERAYFxEQ"
        "GBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYAAABACQAAAFsAFAACQAAJBUUByEmNTQ3IQFsBP7A"
        "BAQBQEAYFxERFxgQAAABAJwAoAD0APAACQAANxYVFAcjJjU0N/AEBFAEBPAQGBcRERcYEAAAAQBM/7ABRAKAAFEAACEWFRQHIyY1"
        "NDcjJjU0NyY1NDcmNTQ3IyY1NDczJjU0NyY1NDcmNTQ3MyY1NDczFhUUByMWFRQHFhUUBxYVFAcjFhUUBzMWFRQHFhUUBxYVFAcB"
        "QAQEeAQEKAQEBAQEBFAEBFAEBAQEBAQoBAR4BARQBAQEBAQEKAQEKAQEBAQEBBAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBAR"
        "FxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYFxEQGBcREBgXEQAAAQBM/7ABRAKAAFEAAAAHIxYVFAcWFRQHFhUUByMW"
        "FRQHIyY1NDczJjU0NyY1NDcmNTQ3MyY1NDcjJjU0NyY1NDcmNTQ3IyY1NDczFhUUBzMWFRQHFhUUBxYVFAczFhUBRARQBAQEBAQE"
        "KAQEeAQEUAQEBAQEBCgEBCgEBAQEBARQBAR4BAQoBAQEBAQEUAQBAREQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEX"
        "GBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXERAYAAABAIj/sAEcAoAASwAAIRYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1"
        "NDcmNTQ3JjU0NyY1NDcmNTQ3MxYVFAcjFhUUBxYVFAcWFRQHFhUUBxYVFAcWFRQHFhUUBwEYBASMBAQEBAQEBAQEBAQEBAQEBAQE"
        "jAQEPAQEBAQEBAQEBAQEBAQEEBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQ"
        "GBcREBgXERAYFxEQGBcRAAABAHT/sAEIAoAASwAAABUUBxYVFAcWFRQHFhUUBxYVFAcWFRQHFhUUBxYVFAcjJjU0NzMmNTQ3JjU0"
        "NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3IyY1NDczFhUUBwEIBAQEBAQEBAQEBAQEBAQEjAQEPAQEBAQEBAQEBAQEBAQEPAQEjAQEAiAY"
        "FxEQGBcREBgXERAYFxEQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXEQADAH7/"
        "sAEhAoAACQBJAFMAAAAHIyY1NDczFhUCFRQHIyY1NDcjJjU0NyMmNTQ3JjU0NyY1NDczJjU0NzMmNTQ3MxYVFAcjFhUUBxYVFAcW"
        "FRQHFhUUBxYVFAczFxYVFAcjJjU0NwEhBDIEBDIEMgQyBAQZBAQeBAQEBAQEHgQEGQQEMgQEGQQEBAQEBAQEBAQZMgQEMgQEAkER"
        "ERcYEBAY/egYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXERAYFxEQGBcRUBAYFxERFxgQAAAD"
        "AG//sAESAoAACQBJAFMAABIVFAcjJjU0NzMSFRQHFhUUByMWFRQHIxYVFAcjJjU0NzMmNTQ3JjU0NyY1NDcmNTQ3JjU0NyMmNTQ3"
        "MxYVFAczFhUUBzMWFRQHAjczFhUUByMmNakEMgQEMm0EBAQeBAQZBAQyBAQZBAQEBAQEBAQEBBkEBDIEBBkEBB4EBJ8EMgQEMgQC"
        "cBgXEREXGBD+sBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxH+sBAQGBcRERcA"
        "AQAkAPABbAFAAAkAAAAVFAchJjU0NyEBbAT+wAQEAUABMBgXEREXGBAAAQAkAPABbAFAAAkAAAAVFAchJjU0NyEBbAT+wAQEAUAB"
        "MBgXEREXGBAAAQBgAPABMAFAAAkAAAEWFRQHIyY1NDcBLAQEyAQEAUAQGBcRERcYEAD//wBgAPABMAFAAAIArAAAAAIAJAAAAWwB"
        "kAAxAGMAABIHIxYVFAcjFhUUBzMWFRQHMxYVFAcjJjU0NyMmNTQ3IyY1NDczJjU0NzMmNTQ3MxYVExYVFAcjJjU0NyMmNTQ3IyY1"
        "NDczJjU0NzMmNTQ3MxYVFAcjFhUUByMWFRQHMxYVFAe4BCgEBCgEBCgEBCgEBDwEBCgEBCgEBCgEBCgEBDwEsAQEPAQEKAQEKAQE"
        "KAQEKAQEPAQEKAQEKAQEKAQEAVEREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBj+6BAYFxERFxgQERcYEBEX"
        "GBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEAAgAkAAABbAGQADEAYwAANxYVFAcjFhUUByMWFRQHIyY1NDczJjU0NzMmNTQ3IyY1"
        "NDcjJjU0NzMWFRQHMxYVFAcWByMWFRQHIxYVFAcjJjU0NzMmNTQ3MyY1NDcjJjU0NyMmNTQ3MxYVFAczFhUUBzMWFbQEBCgEBCgE"
        "BDwEBCgEBCgEBCgEBCgEBDwEBCgEBOAEKAQEKAQEPAQEKAQEKAQEKAQEKAQEPAQEKAQEKATwEBgXERAYFxEQGBcRERcYEBEXGBAR"
        "FxgQERcYEBEXGBAQGBcREBgXET8REBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgAAQBvAAABIQGQADEAACUW"
        "FRQHIyY1NDcjJjU0NyMmNTQ3MyY1NDczJjU0NzMWFRQHIxYVFAcjFhUUBzMWFRQHAR0EBFAEBDwEBB4EBB4EBDwEBFAEBDwEBDIE"
        "BDIEBFAQGBcRERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcRAAEAbwAAASEBkAAxAAAkByMWFRQHIxYVFAcjJjU0"
        "NzMmNTQ3MyY1NDcjJjU0NyMmNTQ3MxYVFAczFhUUBzMWFQEhBB4EBDwEBFAEBDwEBDIEBDIEBDwEBFAEBDwEBB4EsREQGBcREBgX"
        "EREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGAACAEL/YAFOAKAAJABJAAA2FRQHFhUUBxYVFAcjFhUUByMmNTQ3MyY1NDcj"
        "JjU0NyY1NDczFhUUBxYVFAcjFhUUByMmNTQ3MyY1NDcjJjU0NyY1NDczFhUUB64EBAQEBCgEBDwEBCgEBCgEBAQEZKQEBAQoBAQ8"
        "BAQoBAQoBAQEBGQEBJAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQYBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBAY"
        "FxEAAgBCAZABTgLQACQASQAAEgcjFhUUBzMWFRQHFhUUByMmNTQ3JjU0NyY1NDczJjU0NzMWFRYVFAcWFRQHIyY1NDcmNTQ3JjU0"
        "NzMmNTQ3MxYVFAcjFhUUBzOuBCgEBCgEBAQEZAQEBAQEBCgEBDwEoAQEBGQEBAQEBAQoBAQ8BAQoBAQoApEREBgXERAYFxEQGBcR"
        "ERcYEBEXGBARFxgQERcYEBAYiBgXERAYFxERFxgQERcYEBEXGBARFxgQEBgXERAYFxEAAgBCAZABTgLQACQASQAAEhUUBxYVFAcW"
        "FRQHIxYVFAcjJjU0NzMmNTQ3IyY1NDcmNTQ3MxYVFAcWFRQHIxYVFAcjJjU0NzMmNTQ3IyY1NDcmNTQ3MxYVFAeuBAQEBAQoBAQ8"
        "BAQoBAQoBAQEBGSkBAQEKAQEPAQEKAQEKAQEBARkBAQCwBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBBgGBcREBgXERAY"
        "FxERFxgQERcYEBEXGBARFxgQEBgXEQAAAQCSAZAA/gLQACQAABIVFAcWFRQHIyY1NDcmNTQ3JjU0NzMmNTQ3MxYVFAcjFhUUBzP+"
        "BAQEZAQEBAQEBCgEBDwEBCgEBCgCIBgXERAYFxERFxgQERcYEBEXGBARFxgQEBgXERAYFxEAAAEAkgGQAP4C0AAkAAASFRQHFhUU"
        "ByMWFRQHIyY1NDczJjU0NyMmNTQ3JjU0NzMWFRQH/gQEBCgEBDwEBCgEBCgEBAQEZAQEAnAYFxEQGBcREBgXEREXGBARFxgQERcY"
        "EBEXGBAQGBcRAAABAJL/YAD+AKAAJAAANhUUBxYVFAcjFhUUByMmNTQ3MyY1NDcjJjU0NyY1NDczFhUUB/4EBAQoBAQ8BAQoBAQo"
        "BAQEBGQEBEAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBAQGBcRAAEAJP+wAWwCgABlAAAlFhUUByMWFRQHIxYVFAcWFRQHIyY1"
        "NDcmNTQ3IyY1NDcjJjU0NyY1NDcmNTQ3MyY1NDczJjU0NyY1NDczFhUUBxYVFAczFhUUBzMWFRQHIyY1NDcjFhUUBxYVFAcWFRQH"
        "MyY1NDcBaAQEKAQEWgQEBAQ8BAQEBFoEBCgEBAQEBAQoBARaBAQEBDwEBAQEWgQEKAQEUAQEoAQEBAQEBKAEBPAQGBcREBgXERAY"
        "FxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXEREXGBAQGBcREBgXERAYFxER"
        "FxgQAAIAJAAAAWwBkABZAHcAACQHIxYVFAczFhUUByMmNTQ3IxYVFAcjJjU0NyMWFRQHIyY1NDczJjU0NyMmNTQ3MyY1NDcjJjU0"
        "NzMWFRQHMyY1NDczFhUUBzMmNTQ3MxYVFAcjFhUUBzMWFQcmNTQ3IyY1NDcjFhUUByMWFRQHMxYVFAczJjU0NwFsBCgEBCgEBDwE"
        "BDIEBGQEBDIEBDwEBCgEBCgEBCgEBCgEBDwEBDIEBGQEBDIEBDwEBCgEBCgEVAQEKAQEUAQEKAQEKAQEUAQEsREQGBcREBgXEREX"
        "GBAQGBcRERcYEBAYFxERFxgQERcYEBEXGBARFxgQERcYEBAYFxERFxgQEBgXEREXGBAQGBcREBgXERAYKBEXGBARFxgQEBgXERAY"
        "FxEQGBcRERcYEAAAAwAk/7ABbAKAAGkAewCNAAAkFRQHFhUUByMWFRQHIxYVFAcjJjU0NyMmNTQ3IyY1NDczFhUUBzMmNTQ3JjU0"
        "NyMmNTQ3IyY1NDcmNTQ3MyY1NDczJjU0NzMWFRQHMxYVFAczFhUUByMmNTQ3IxYVFAcWFRQHMxYVFAczJyY1NDcmNTQ3IxYVFAcW"
        "FRQHFjU0NyY1NDcjFhUUBxYVFAczAWwEBAQoBARaBAQ8BARaBAQoBARQBAQyBAQEBFoEBCgEBAQEKAQEWgQEPAQEWgQEKAQEUAQE"
        "MgQEBARaBAQovgQEBAQyBAQEBJwEBAQyBAQEBDLgGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQEBgXEREXGBARFxgQERcYEBEX"
        "GBARFxgQERcYEBEXGBAQGBcREBgXERAYFxERFxgQEBgXERAYFxEQGBcRUBEXGBARFxgQEBgXERAYFxHfFxgQERcYEBAYFxEQGBcR"
        "AAEAJAAAAWwCMABZAAAlFhUUByMWFRQHIyY1NDcjJjU0NyMmNTQ3MyY1NDcjJjU0NzMmNTQ3MyY1NDczFhUUBzMWFRQHIyY1NDcj"
        "FhUUBzMWFRQHIxYVFAczFhUUByMWFRQHMyY1NDcBaAQEKAQEyAQEKAQEKAQEKAQEKAQEKAQEKAQEyAQEKAQEPAQEjAQEUAQEUAQE"
        "UAQEUAQEjAQEoBAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcRERcYEBAYFxEQGBcREBgXERAYFxEQ"
        "GBcRERcYEAACACQAAAFsAjAASwBfAAA2FRQHIxYVFAcjJjU0NzMmNTQ3JjU0NyMmNTQ3MyY1NDcmNTQ3MyY1NDczFhUUBzMWFRQH"
        "IyY1NDcjFhUUBxYVFAczFhUUByMWFRQHFgcjFhUUByMmNTQ3MyY1NDczFhW4BCgEBGQEBDwEBAQEPAQEPAQEBAQoBASgBAQoBAQ8"
        "BARkBAQEBDwEBDwEBLgEFAQEoAQEeAQEPASQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXEREXGBAQ"
        "GBcREBgXERAYFxEQGBcRPxEQGBcRERcYEBEXGBAQGAAAAQAkAAABbAIwAGEAAAAHIxYVFAcjFhUUBzMWFRQHIxYVFAczFhUUByMW"
        "FRQHIyY1NDcjJjU0NzMmNTQ3IyY1NDczJjU0NyMmNTQ3IyY1NDczFhUUBxYVFAczFhUUBzMmNTQ3MyY1NDcmNTQ3MxYVAWwEFAQE"
        "KAQEKAQEZAQEZAQEZAQEUAQEZAQEZAQEZAQEKAQEKAQEFAQEZAQEBAQoBAQoBAQoBAQEBGQEAfEREBgXERAYFxEQGBcREBgXERAY"
        "FxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXEREXGBARFxgQERcYEBAYAAABADgAUAFYAeAALQAA"
        "AAcjFhUUBxYVFAcjJjU0NyY1NDcjJjU0NzMmNTQ3JjU0NzMWFRQHFhUUBzMWFQFYBGQEBAQEUAQEBARkBARkBAQEBFAEBAQEZAQB"
        "AREQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGAAAAQBMAPABRAFAAAkAAAAVFAcjJjU0NzMBRATwBATwATAY"
        "FxERFxgQAAEATABQAUQCMABhAAAlFhUUByMmNTQ3IyY1NDcjFhUUByMWFRQHIyY1NDczJjU0NzMmNTQ3JjU0NyMmNTQ3IyY1NDcz"
        "FhUUBzMWFRQHMyY1NDczJjU0NzMWFRQHIxYVFAcjFhUUBxYVFAczFhUUBwFABAQ8BAQeBAQ8BAQeBAQ8BAQeBAQoBAQEBCgEBB4E"
        "BDwEBB4EBDwEBB4EBDwEBB4EBCgEBAQEKAQEoBAYFxERFxgQERcYEBAYFxEQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgX"
        "ERAYFxERFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcRAAMATAAAAUQCMAARABsALQAAEjU0NyY1NDczFhUUBxYVFAcjFhUUByMm"
        "NTQ3MwYVFAcWFRQHIyY1NDcmNTQ3M5wEBARQBAQEBFCkBPAEBPBMBAQEUAQEBARQAaEXGBARFxgQEBgXERAYFxFgGBcRERcYELAY"
        "FxEQGBcRERcYEBEXGBAAAAIATACgAUQBkAAJABMAABI1NDczFhUUByMWFRQHIyY1NDczTATwBATw9ATwBATwAVEXGBAQGBcRYBgX"
        "EREXGBAAAAEAUQAAAT8CMABFAAAAByMWFRQHIxYVFAcjFhUUByMmNTQ3MyY1NDczJjU0NzMmNTQ3IyY1NDcjJjU0NyMmNTQ3MxYV"
        "FAczFhUUBzMWFRQHMxYVAT8EMgQEMgQEMgQEUAQEMgQEMgQEMgQEMgQEMgQEMgQEUAQEMgQEMgQEMgQBAREQGBcREBgXERAYFxER"
        "FxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgAAAEAUQAAAT8CMABFAAAlFhUUByMmNTQ3IyY1NDcjJjU0"
        "NyMmNTQ3MyY1NDczJjU0NzMmNTQ3MxYVFAcjFhUUByMWFRQHIxYVFAczFhUUBzMWFRQHATsEBFAEBDIEBDIEBDIEBDIEBDIEBDIE"
        "BFAEBDIEBDIEBDIEBDIEBDIEBFAQGBcRERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcREBgX"
        "EQACADgAAAFYAjAALQA3AAATJjU0NzMmNTQ3JjU0NzMWFRQHFhUUBzMWFRQHIxYVFAcWFRQHIyY1NDcmNTQ3EhUUByEmNTQ3ITwE"
        "BGQEBAQEUAQEBARkBARkBAQEBFAEBAQEuAT+6AQEARgBQBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcRERcYEBEXGBD/"
        "ABgXEREXGBAAAAEAJACgAWwB4ABNAAAABxYVFAcjFhUUByMWFRQHIyY1NDcjJjU0NyMWFRQHIxYVFAcjJjU0NyY1NDczJjU0NzMm"
        "NTQ3MxYVFAczFhUUBzMmNTQ3MyY1NDczFhUBbAQEBB4EBB4EBGQEBB4EBDIEBBQEBDwEBAQEHgQEHgQEZAQEHgQEMgQEFAQEPAQB"
        "oREQGBcREBgXERAYFxERFxgQERcYEBAYFxEQGBcRERcYEBEXGBARFxgQERcYEBAYFxEQGBcRERcYEBEXGBAQGAAAAQAkAFABbAFA"
        "ABoAACQVFAcWFRQHIyY1NDcmNTQ3IyY1NDchFhUUBwFsBAQEUAQEBATwBAQBQAQE4BgXERAYFxERFxgQERcYEBEXGBAQGBcRAAUA"
        "JAAAAWwCMABFAGMAbQCLAJUAADcWFRQHIxYVFAcjFhUUByMmNTQ3MyY1NDczJjU0NzMmNTQ3MyY1NDczJjU0NzMmNTQ3MxYVFAcj"
        "FhUUByMWFRQHIxYVFAcnJjU0NzMmNTQ3MxYVFAczFhUUByMWFRQHIyY1NDc3FhUUBzMmNTQ3ExYVFAcjFhUUByMmNTQ3IyY1NDcz"
        "JjU0NzMWFRQHByY1NDcjFhUUB7kEBCgEBC0EBDwEBC0EBCgEBC0EBC0EBCgEBC0EBDwEBC0EBCgEBC0EBL4EBCMEBFAEBCMEBCME"
        "BFAEBBkEBB4EBOYEBCMEBFAEBCMEBCMEBFAEBBkEBB4EBPAQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQ"
        "EBgXERAYFxEQGBcREBgXEaARFxgQERcYEBAYFxEQGBcREBgXEREXGBBQEBgXEREXGBD+wBAYFxEQGBcRERcYEBEXGBARFxgQEBgX"
        "EVARFxgQEBgXEQACACQAAAFsAoAAdwCJAAAAFRQHFhUUBxYVFAcjJjU0NyMmNTQ3JjU0NzMmNTQ3MyY1NDcjFhUUByMWFRQHFhUU"
        "BxYVFAcWFRQHMxYVFAczFhUUByMmNTQ3IyY1NDcjJjU0NyY1NDcmNTQ3JjU0NzMmNTQ3MyY1NDczFhUUBzMWFRQHMxYVFAcGNTQ3"
        "JjU0NyMWFRQHFhUUBzMBbAQEBAQEoAQEHgQEBAQeBAQoBARkBAQoBAQEBAQEBAQoBAS0BATIBAQoBAQoBAQEBAQEBAQoBAQoBASg"
        "BAQoBAQoBARABAQERgQEBARGAYAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcREBgXERAYFxEQGBcR"
        "EBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQGBcRjxcYEBEXGBAQGBcREBgXEQACACQAAAFsAjAA"
        "cwCQAAAAByMWFRQHMxYVFAczFhUUByMmNTQ3JjU0NyMWFRQHIxYVFAcjJjU0NyMmNTQ3JjU0NzMmNTQ3MyY1NDcjJjU0NzMmNTQ3"
        "MxYVFAczFhUUByMmNTQ3IxYVFAczFhUUBzMWFRQHMyY1NDcmNTQ3MxYVFAcWFQcmNTQ3IyY1NDcjFhUUByMWFRQHFhUUBzMmNTQ3"
        "AWwEMgQEHgQEFAQEUAQEBAQeBAQeBASMBAQoBAQEBCgEBCgEBCgEBCgEBHgEBCgEBDwEBFAEBFAEBB4EBDIEBAQEPAQEBJAEBB4E"
        "BB4EBCgEBAQERgQEAQEREBgXERAYFxEQGBcRERcYEBEXGBAQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcR"
        "EBgXEREXGBAQGBcREBgXERAYFxERFxgQERcYEBAYFxEQGHgRFxgQERcYEBAYFxEQGBcREBgXEREXGBAAAQAk/7ABbAKAAJEAAAAH"
        "IxYVFAcWFRQHFhUUBxYVFAcWFRQHFhUUBxYVFAcWFRQHIyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3IxYVFAcWFRQH"
        "FhUUBxYVFAcWFRQHFhUUBxYVFAcWFRQHIyY1NDcmNTQ3JjU0NyMmNTQ3IyY1NDcjJjU0NyY1NDczJjU0NzMmNTQ3MxYVAWwEKAQE"
        "BAQEBAQEBAQEBAQEBAQ8BAQEBAQEBAQEBAQEBAQEBDwEBAQEBAQEBAQEBAQEBAQEPAQEBAQEBBQEBCgEBCgEBAQEKAQEKAQE8AQC"
        "QREQGBcREBgXERAYFxEQGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQEBgXERAYFxEQ"
        "GBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGAAAAgA4/7ABWAIwAE0A"
        "YQAAJAcjFhUUByMmNTQ3MyY1NDcjJjU0NyMmNTQ3JjU0NzMmNTQ3IyY1NDczJjU0NzMWFRQHIxYVFAczFhUUBzMWFRQHFhUUByMW"
        "FRQHMxYVJyY1NDcjJjU0NyMWFRQHMxYVFAcBWAQoBATmBAS+BAR4BARGBAQEBB4EBCgEBCgEBOYEBL4EBHgEBEYEBAQEHgQEKARK"
        "BAQoBARkBAQoBAQRERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcREBgXERAY"
        "eBEXGBARFxgQEBgXERAYFxEAAAUAJP+wAWwCgAAJAEcAhQCzAL0AAAAHIyY1NDczFhUCFRQHIyY1NDcjJjU0NyY1NDcmNTQ3JjU0"
        "NyY1NDczJjU0NzMWFRQHIxYVFAcWFRQHFhUUBxYVFAcWFRQHMxIVFAcWFRQHFhUUBxYVFAcjFhUUByMmNTQ3MyY1NDcmNTQ3JjU0"
        "NyY1NDcmNTQ3IyY1NDczFhUUBzMWFRQHJgcjFhUUBxYVFAcWFRQHMxYVFAcjJjU0NyMmNTQ3JjU0NyY1NDczJjU0NzMWFQI3MxYV"
        "FAcjJjUBHASgBASgBKAEMgQEHgQEBAQEBAQEBAQeBAQyBAQeBAQEBAQEBAQEBB70BAQEBAQEBB4EBDIEBB4EBAQEBAQEBAQEHgQE"
        "MgQEHgQEagRBBAQEBAQEQQQEZAQEDwQEBAQEBA8EBGQEigSgBASgBAJBEREXGBAQGP3oGBcRERcYEBEXGBARFxgQERcYEBEXGBAR"
        "FxgQERcYEBAYFxEQGBcREBgXERAYFxEQGBcREBgXEQEwGBcREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQERcY"
        "EBEXGBAQGBcREBgXEREREBgXERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBj+OBAQGBcRERcABgAk/7ABbAKAAAkA"
        "RwCFAMQAzgDYAAAAByMmNTQ3MxYVAhUUByMmNTQ3IyY1NDcmNTQ3JjU0NyY1NDcmNTQ3MyY1NDczFhUUByMWFRQHFhUUBxYVFAcW"
        "FRQHFhUUBzMSFRQHFhUUBxYVFAcWFRQHIxYVFAcjJjU0NzMmNTQ3JjU0NyY1NDcmNTQ3JjU0NyMmNTQ3MxYVFAczFhUUBwYHIxYV"
        "FAczFhUUBxYVFAcjJjU0NyY1NDcjFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NyY1NDczFhUUBzMWFQcmNTQ3IxYVFAcCNzMWFRQH"
        "IyY1ARwEoAQEoASgBDIEBB4EBAQEBAQEBAQEHgQEMgQEHgQEBAQEBAQEBAQe9AQEBAQEBAQeBAQyBAQeBAQEBAQEBAQEBB4EBDIE"
        "BB4EBFsEHgQEHgQEBAQyBAQEBB4EBAQEMgQEBAQEBAQEBARkBAQeBDYEBB4EBEUEoAQEoAQCQRERFxgQEBj96BgXEREXGBARFxgQ"
        "ERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEQGBcREBgXERAYFxEBMBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEX"
        "GBARFxgQERcYEBEXGBARFxgQEBgXERAYFxE/ERAYFxEQGBcREBgXEREXGBARFxgQEBgXERAYFxERFxgQERcYEBEXGBARFxgQERcY"
        "EBAYFxEQGCgRFxgQEBgXEf6wEBAYFxERFwAABAAkAPABbAIwACMARwBrAHUAABMWFRQHIxYVFAcWFRQHFhUUByMmNTQ3JjU0NyY1"
        "NDcjJjU0NxYVFAcjFhUUBzMWFRQHFhUUByMmNTQ3JjU0NyY1NDcmNTQ3MxYVFAcWFRQHFhUUByMmNTQ3JjU0NzMmNTQ3IyY1NDcz"
        "FhUUBwY3MxYVFAcjJjWgBAQjBAQEBAQEMgQEBAQEBCMEBNYEHgQECgQEBAQyBAQEBAQEBARGcgQEBAQEMgQEBAQKBAQeBARGBARy"
        "BCgEBCgEAjAQGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQYBgX"
        "ERAYFxEQGBcRERcYEBEXGBARFxgQERcYEBAYFxEQEBAYFxERFwAAAgBWAUABOgKAACUANwAAAAcWFRQHIxYVFAcjJjU0NyMmNTQ3"
        "JjU0NzMmNTQ3MxYVFAczFhUGNTQ3JjU0NyMWFRQHFhUUBzMBOgQEBB4EBKAEBB4EBAQEHgQEoAQEHgREBAQEZAQEBARkAfEREBgX"
        "ERAYFxERFxgQERcYEBEXGBARFxgQEBgXERAYZxcYEBEXGBAQGBcREBgXEQAAAQCc/7AA9AKAAEkAABIVFAcWFRQHFhUUBxYVFAcW"
        "FRQHFhUUBxYVFAcWFRQHIyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NyY1NDcmNTQ3JjU0NzMWFRQH9AQEBAQEBAQEBAQEBAQEBFAE"
        "BAQEBAQEBAQEBAQEBAQEBARQBAQCIBgXERAYFxEQGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEX"
        "GBARFxgQERcYEBEXGBAQGBcRAAACAJz/sAD0AoAAIQBDAAASFRQHFhUUBxYVFAcjJjU0NyY1NDcmNTQ3JjU0NzMWFRQHEhUUBxYV"
        "FAcWFRQHFhUUByMmNTQ3JjU0NyY1NDcmNTQ3M/QEBAQEBFAEBAQEBAQEBFAEBAQEBAQEBAQEUAQEBAQEBAQEUAIgGBcREBgXERAY"
        "FxERFxgQERcYEBEXGBARFxgQEBgXEf6wGBcREBgXERAYFxEQGBcRERcYEBEXGBARFxgQERcYEAABACQA8AFsAjAAOwAAABUUByMm"
        "NTQ3IyY1NDcjFhUUByMWFRQHIyY1NDczJjU0NzMmNTQ3MyY1NDczFhUUBzMWFRQHMxYVFAczAWwEUAQEKAQEUAQEKAQEUAQEKAQE"
        "KAQEKAQEUAQEKAQEKAQEKAEwGBcRERcYEBEXGBAQGBcREBgXEREXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxEAAQAk/7ABbAKA"
        "AFkAAAAHIxYVFAcjFhUUByMWFRQHIxYVFAcjFhUUByMWFRQHIxYVFAcjFhUUByMmNTQ3MyY1NDczJjU0NzMmNTQ3MyY1NDczJjU0"
        "NzMmNTQ3MyY1NDczJjU0NzMWFQFsBB4EBB4EBB4EBB4EBB4EBB4EBB4EBB4EBFAEBB4EBB4EBB4EBB4EBB4EBB4EBB4EBB4EBFAE"
        "AkEREBgXERAYFxEQGBcREBgXERAYFxEQGBcREBgXERAYFxERFxgQERcYEBEXGBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGAAA"
        "A//8/2ABbAGQAD8AbQB3AAA2FRQHIxYVFAcWFRQHIxYVFAcjJjU0NzMmNTQ3JjU0NzMmNTQ3JjU0NzMmNTQ3JjU0NzMWFRQHFhUU"
        "ByMWFRQHNgcjFhUUBxYVFAczFhUUByMmNTQ3IyY1NDcmNTQ3MyY1NDcmNTQ3MxYVFAcWFQY3MxYVFAcjJjWaBB4EBAQEKAQEUAQE"
        "KAQEBAQeBAQEBB4EBAQEUAQEBAQeBATWBB4EBAQEHgQEUAQEHgQEBAQeBAQEBFAEBATaBGQEBGQEkBgXERAYFxEQGBcREBgXEREX"
        "GBARFxgQERcYEBEXGBARFxgQERcYEBEXGBAQGBcREBgXERAYFxFhERAYFxEQGBcREBgXEREXGBARFxgQERcYEBEXGBARFxgQEBgX"
        "ERAY2BAQGBcRERcAAv68AeD/tAIwAAkAEwAAAxYVFAcjJjU0NzMWFRQHIyY1NDfwBARQBATwBARQBAQCMBAYFxERFxgQEBgXEREX"
        "GBAAAf8MAeD/ZAIwAAkAAAMWFRQHIyY1NDegBARQBAQCMBAYFxERFxgQAAH+5AHg/2QCgAATAAACFRQHIyY1NDcjJjU0NzMWFRQH"
        "M5wEUAQEKAQEUAQEKAIgGBcRERcYEBEXGBAQGBcRAAAB/wwB4P+MAoAAEwAAAgcjFhUUByMmNTQ3MyY1NDczFhV0BCgEBFAEBCgE"
        "BFAEAkEREBgXEREXGBARFxgQEBgAAf7GAeD/qgKAAB0AAAIVFAcjJjU0NyMWFRQHIyY1NDczJjU0NzMWFRQHM1YEUAQEPAQEUAQE"
        "MgQEeAQEMgIgGBcRERcYEBAYFxERFxgQERcYEBAYFxEAAAL+xgHg/6oC0AAdACcAAAIHIxYVFAcjJjU0NyMmNTQ3MyY1NDczFhUU"
        "BzMWFQcmNTQ3IxYVFAdWBB4EBKAEBB4EBB4EBKAEBB4EQAQEZAQEAkEREBgXEREXGBARFxgQERcYEBAYFxEQGCgRFxgQEBgXEQAA"
        "A/6UAeD/3AKAABMAHQAnAAACBzMWFRQHIyY1NDcjJjU0NzMWFRYHIyY1NDczFhUENzMWFRQHIyY1sARQBAR4BARQBAR4BIwEPAQE"
        "PAT+uAQ8BAQ8BAJBERAYFxERFxgQERcYEBAYFxERFxgQEBg4EBAYFxERFwAAAf68AeD/tAIwAAkAAAIVFAcjJjU0NzNMBPAEBPAC"
        "IBgXEREXGBAAAAH/DAHg/2QCgAASAAACBxYVFAcjJjU0NyMmNTQ3MxYVnAQEBCgEBCgEBFAEAkEREBgXEREXGBARFxgQEBgAAf8M"
        "/2D/ZP+wAAkAAAcWFRQHIyY1NDegBARQBARQEBgXEREXGBAAAAH/Av9g/3gAAAATAAAGByMWFRQHIyY1NDczJjU0NzMWFYgEHgQE"
        "UAQEMgQEPAQ/ERAYFxERFxgQERcYEBAYAAABACQB4AB8AoAAEgAAEgcWFRQHIyY1NDcjJjU0NzMWFXwEBAQoBAQoBARQBAJBERAY"
        "FxERFxgQERcYEBAY//8AnAHgARwCgAADANoBkAAAAAD//wCS/2ABCAAAAAMA4QGQAAAAAP//AFYB4AE6AoAAAwDbAZAAAAAA//8A"
        "TAHgAUQCMAADANcBkAAAAAD//wB0AeAA9AKAAAMA2QGQAAAAAP//AEwB4AFEAjAAAwDeAZAAAAAA//8AVgHgAToC0AADANwBkAAA"
        "AAD//wAkAeABbAKAAAMA3QGQAAAAAAAAAAAACABmAAMAAQQJAAAAgADKAAMAAQQJAAEACgDAAAMAAQQJAAIADgCyAAMAAQQJAAMA"
        "MACCAAMAAQQJAAQAGgBoAAMAAQQJAAUAGgBOAAMAAQQJAAYAGgA0AAMAAQQJAA4ANAAAAGgAdAB0AHAAOgAvAC8AcwBjAHIAaQBw"
        "AHQAcwAuAHMAaQBsAC4AbwByAGcALwBPAEYATABWAFQAMwAyADMALQBSAGUAZwB1AGwAYQByAFYAZQByAHMAaQBvAG4AIAAyAC4A"
        "MAAwADAAVgBUADMAMgAzACAAUgBlAGcAdQBsAGEAcgAyAC4AMAAwADAAOwBVAEsAVwBOADsAVgBUADMAMgAzAC0AUgBlAGcAdQBs"
        "AGEAcgBSAGUAZwB1AGwAYQByAFYAVAAzADIAMwBDAG8AcAB5AHIAaQBnAGgAdAAgADIAMAAxADEALAAgAFQAaABlACAAVgBUADMA"
        "MgAzACAAUAByAG8AagBlAGMAdAAgAEEAdQB0AGgAbwByAHMAIAAoAHAAZQB0AGUAcgAuAGgAdQBsAGwAQABvAGkAawBvAGkALgBj"
        "AG8AbQApAAIAAAAAAAD/hAAyAAAAAQAAAAAAAAAAAAAAAAAAAAAA6wAAAQIAAgADACQAyQDHAGIArQBjAK4AkAAlACYAZAAnAOkA"
        "KABlAMgAygDLACkAKgArACwAzADNAM4AzwAtAC4ALwAwADEAZgAyANAA0QBnANMAkQCvALAAMwDtADQANQA2ADcAOADUANUAaADW"
        "ADkAOgA7ADwA6wA9AEQAaQBrAGwAagBuAG0AoABFAEYAbwBHAOoASABwAHIAcwBxAEkASgBLAEwA1wB0AHYAdwEDAHUATQEEAE4A"
        "TwBQAFEAeABSAHkAewB8AHoAoQB9ALEAUwDuAFQAVQBWAIkAVwBYAH4AgACBAH8AWQBaAFsAXADsALoAXQEFAMAAwQCdAJ4AEwAU"
        "ABUAFgAXABgAGQAaABsAHAEGAQcBCAC8APQA9QD2AA0APwDDAIcAHQAPAKsABACjAAYAEQAiAKIABQAKAB4AEgBCAQkAXgBgAD4A"
        "QAALAAwAswCyABABCgCpAKoAvgC/AMUAtAC1ALYAtwDEAQsAhAC9AAcBDACFAJYADgDvAPAAuAAgACEAHwCTAGEApAAIACMACQCI"
        "AIYAiwCKAIwAgwBfAOgAQQENAQ4BDwEQAREBEgETARQBFQEWARcBGAEZARoAjQDeANgAjgBDANoA3QDZBE5VTEwJaS5sb2NsVFJL"
        "B3VuaTAyMzcDZl9mB3VuaTAwQjkHdW5pMDBCMgd1bmkwMEIzFnBlcmlvZGNlbnRlcmVkLmxvY2xDQVQHdW5pMDBBRAd1bmkwMEEw"
        "BEV1cm8HdW5pMjIxNQd1bmkwMEI1B3VuaTAzMDgHdW5pMDMwNwlncmF2ZWNvbWIJYWN1dGVjb21iB3VuaTAzMDIHdW5pMDMwQQl0"
        "aWxkZWNvbWIHdW5pMDMwNA1ob29rYWJvdmVjb21iDGRvdGJlbG93Y29tYgd1bmkwMzI3B3VuaTAyQkMAAQAB//8ADwABAAAAJgAA"
        "AAAADAABANcACgACAAAAAgACAAAAAAACAAIAAgABAAIABwAEAHoAAQB7AH0AAgB+AH8AAQC5ANYAAQDXANcAAwDZANoAAwDdAOAA"
        "AwABAAAACgA0AFwAAkRGTFQAHGxhdG4ADgAEAAAAAP//AAIAAQADAAQAAAAA//8AAgAAAAIABG1hcmsAIm1hcmsAIm1rbWsAGm1r"
        "bWsAGgAAAAIAAQACAAAAAQAAAAMAwACMAAgABgIAAAEACAABAGwANAABAFIADAANACIAHAAcABwAIgAcApYClgLSApYC0gLAApYA"
        "Af84AoAAAf84AjAAAQANANcA2QDaAN0A3gDfAOMA5QDmAOcA6ADpAOoABgAAAuoAAALqAAAC6gAAAuoAAALqAAAC6gABAAYA1wDZ"
        "ANoA3QDeAN8ABgEAAAEACAABACYAGAABACAADAACAAYCKgAB/zj/YAABAAIA4ADkAAEAAAKSAAEAAQDgAAQAAAABAAgAAQKKAjIA"
        "AgJgAAwAcQIgAhoCFAIOAiACDgIUAggCFAIOAiACAgIgAg4CIAIaAiACGgIgAfwB9gH8AiACGgIgAhoCFAIOAiACDgIUAggCFAIO"
        "AiACGgHwAfwCIAIaAiACGgIUAg4CIAIOAhQCCAIUAg4CIAHqAiACGgHwAhoCIAIaAiACGgIgAg4CIAIaAhQCDgIgAg4CFAIIAhQC"
        "DgIgAhoCIAIOAiACGgIgAhoCIAIaAiACGgIgAhoCIAIaAiACGgIUAg4CIAIOAhQCCAIUAg4CIAIaAiACGgIgAhoCIAIaAhQCDgIg"
        "AhoCIAHkAhQB3gIgAd4CFAIaAhQB3gIgAggCIAHeAiAB5AIgAeQCIAHYAfYB2AIgAeQB8AHYAhQB0gHwAdICFAH8AhQB0gIgAeQC"
        "IAHYAiACGgIgAhQCIAHkAhQB3gIgAd4CFAIaAiACGgIUAd4CIAHkAiAB5AIgAhoCIAHkAiAB5AIgAd4CIAHkAhQB3gIgAd4CFAIa"
        "AhQB3gIUAeQCIAHeAiAB5AIgAeQCIAHkAcwB5AIgAeQB8AHkAiAB5AIUAd4CIAHeAhQCGgIUAd4CIAHkAiAB5AIgAeQBxgHkAhQB"
        "3gIUAhoCIAHkAAEBQAAAAAEAjAAAAAEA3AKAAAEA3AGQAAEAyAKAAAEAyAGQAAEA8AIwAAEA3AAAAAEAyP9gAAEA3AIwAAEAyANw"
        "AAEAyALQAAEAyAMgAAEAAAAAAAEAyAIwAAEAyAAAAAIABwAEAA8AAAARACwADAAuAEgAKABKAFgAQwBaAGgAUgBqAGwAYQBuAHoA"
        "ZAAHAAEAJAABACQAAQAkAAEAJAABACQAAQAkAAAAHgAB/zgAAAAB/zgBkAABAAcA1wDZANoA3QDeAN8A4AABAAAACgCwAZwAAkRG"
        "TFQAlmxhdG4ADgB8AAZBWkUgAG5DQVQgAGBDUlQgAFJLQVogAERUQVQgADZUUksgACgAAP//AAQABwAPABcAHQAA//8ABAAGAA4A"
        "FgAcAAD//wAEAAUADQAVABsAAP//AAQABAAMABQAGgAA//8ABAADAAsAEwAZAAD//wAEAAIACgASABgAAP//AAMAAQAJABEABAAA"
        "AAD//wADAAAACAAQAB5jY21wAOZjY21wAOZjY21wAOZjY21wAOZjY21wAOZjY21wAOZjY21wAOZjY21wAOZmcmFjAOBmcmFjAOBm"
        "cmFjAOBmcmFjAOBmcmFjAOBmcmFjAOBmcmFjAOBmcmFjAOBsaWdhANpsaWdhANpsaWdhANpsaWdhANpsaWdhANpsaWdhANpsaWdh"
        "ANpsaWdhANpsb2NsANRsb2NsAM5sb2NsAMhsb2NsAMJsb2NsALxsb2NsALYAAAABAAQAAAABAAMAAAABAAIAAAABAAUAAAABAAEA"
        "AAABAAYAAAABAAgAAAABAAcAAAABAAAACgEIAMQAsACwALAAsACwAHQARAAWAAEAAAABAAgAAgAUAAcAfgB/AH4AUwBaAH8AowAB"
        "AAcABAAkAD0AUgBZAGAAkwAEAAAAAQAIAAEAIgABAAgAAwAUAA4ACAB9AAIAXAB8AAIAUgB7AAIATwABAAEATwAEAAAAAQAIAAEA"
        "LAACABYACgABAAQAkAADAKEAhAACAA4ABgCPAAMAoQCEAI4AAwChAIIAAQACAIEAgwABAAAAAQAIAAEABgAFAAEAAQBSAAYAAAAC"
        "ACQACgADAAEAFAABAC4AAQAUAAEAAAAJAAEAAQAgAAMAAQAaAAEAFAABABoAAQAAAAkAAQABAJMAAQABAFwABgAAAAIAJAAKAAMA"
        "AAABADwAAgAUACwAAQAAAAkAAQABAOAAAwAAAAEAIgABABIAAQAAAAkAAQAGANcA2QDaAN0A3gDfAAEAAgBSAFkAAA=="),
}


def ask_credentials(root):
    """First-run dialog: each user enters their own free Blizzard API client."""
    root.withdraw()
    dlg = tk.Toplevel(root)
    dlg.title("Blizzard API setup")
    dlg.resizable(False, False)
    frm = ttk.Frame(dlg, padding=16)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, justify="left", wraplength=380, text=(
        "This app reads auction house prices from Blizzard's API, which needs a free "
        "API client.\n\n1. Sign in at develop.battle.net and create a client. Any name "
        "works. Leave Redirect URLs and Service URL empty (if the form insists, use "
        "http://localhost). For Intended Use, write something like \"Personal app to "
        "check auction house prices.\"\n"
        "2. Paste its Client ID and Client Secret below.")).grid(row=0, column=0, columnspan=2, sticky="w")
    url = "https://develop.battle.net/access/clients"
    ttk.Button(frm, text="Open develop.battle.net", command=lambda: webbrowser.open(url)).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(8, 12))
    cid, secret = tk.StringVar(), tk.StringVar()
    ttk.Label(frm, text="Client ID").grid(row=2, column=0, sticky="w")
    e1 = ttk.Entry(frm, textvariable=cid, width=44)
    e1.grid(row=2, column=1, pady=2)
    ttk.Label(frm, text="Client Secret").grid(row=3, column=0, sticky="w")
    ttk.Entry(frm, textvariable=secret, width=44, show="*").grid(row=3, column=1, pady=2)
    ok = {"v": False}

    def save():
        if not cid.get().strip() or not secret.get().strip():
            messagebox.showwarning("Blizzard API setup", "Enter both the Client ID and Secret.", parent=dlg)
            return
        wp.save_credentials(cid.get(), secret.get())
        ok["v"] = True
        dlg.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Quit", command=dlg.destroy).pack(side="right")
    ttk.Button(btns, text="Save", command=save).pack(side="right", padx=6)
    dlg.bind("<Return>", lambda e: save())
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    e1.focus_set()
    root.wait_window(dlg)
    root.deiconify()
    return ok["v"]


if __name__ == "__main__":
    register_fonts()
    root = tk.Tk()
    setup_theme(root)
    try:
        icon = os.path.join(wp.BUNDLE_DIR, "ah_coin_icon.ico")
        if os.path.exists(icon):
            root.iconbitmap(default=icon)
    except Exception:
        pass
    if not wp.has_credentials() and not ask_credentials(root):
        root.destroy()
        sys.exit(0)
    App(root)
    root.mainloop()
