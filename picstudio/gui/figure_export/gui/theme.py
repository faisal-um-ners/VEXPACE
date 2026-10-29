"""Visual design system: colour tokens, Qt style sheet and matching Matplotlib style."""
from __future__ import annotations

import matplotlib as mpl

# Colour-blind-safe categorical series (blue, orange, green, magenta, teal, gold, violet, red)
SERIES_LIGHT = ["#2563eb", "#ea580c", "#059669", "#c026d3", "#0891b2", "#ca8a04", "#7c3aed", "#dc2626"]
SERIES_DARK = ["#60a5fa", "#fb923c", "#34d399", "#e879f9", "#22d3ee", "#facc15", "#a78bfa", "#f87171"]

# Physical roles keep the same colour everywhere in the app
ROLE_LIGHT = {"electron": "#2563eb", "ion": "#ea580c", "potential": "#7c3aed", "field": "#059669",
              "voltage": "#7c3aed", "gap": "#2563eb", "current": "#dc2626", "app": "#64748b"}
ROLE_DARK = {"electron": "#60a5fa", "ion": "#fb923c", "potential": "#a78bfa", "field": "#34d399",
             "voltage": "#a78bfa", "gap": "#60a5fa", "current": "#f87171", "app": "#94a3b8"}

THEMES = {
    "light": dict(
        name="light",
        bg="#f3f5f8", surface="#ffffff", surface2="#f8fafc", surface3="#eef2f7", border="#e2e8f0",
        border2="#cbd5e1", text="#0f172a", text2="#475569", text3="#94a3b8",
        accent="#2563eb", accent_hover="#1d4ed8", accent_soft="#e8effe", accent_text="#ffffff",
        success="#16a34a", success_soft="#dcfce7", warning="#d97706", warning_soft="#fef3c7",
        danger="#dc2626", danger_soft="#fee2e2", info="#0891b2", info_soft="#cffafe",
        rail="#0f172a", rail2="#1e293b", rail_text="#94a3b8", rail_active="#ffffff",
        input="#ffffff", focus="#93c5fd", selection="#dbeafe", selection_text="#0f172a",
        plot_bg="#ffffff", plot_fg="#1e293b", plot_fg2="#64748b", grid="#e2e8f0",
        series=SERIES_LIGHT, role=ROLE_LIGHT, console_bg="#0f172a", console_fg="#e2e8f0",
        shadow="rgba(15,23,42,0.08)", hero1="#1e3a8a", hero2="#6d28d9",
    ),
    "dark": dict(
        name="dark",
        bg="#0b0f14", surface="#121821", surface2="#161d27", surface3="#1c2531", border="#243041",
        border2="#334155", text="#e5e9f0", text2="#a3afc0", text3="#64748b",
        accent="#4f8cff", accent_hover="#6b9fff", accent_soft="#17233a", accent_text="#ffffff",
        success="#22c55e", success_soft="#0f2a1a", warning="#f59e0b", warning_soft="#2c2109",
        danger="#f87171", danger_soft="#2f1414", info="#22d3ee", info_soft="#0c2a31",
        rail="#06090d", rail2="#121821", rail_text="#7d8aa0", rail_active="#ffffff",
        input="#0e141c", focus="#2b5cb8", selection="#1e3a66", selection_text="#e5e9f0",
        plot_bg="#121821", plot_fg="#e5e9f0", plot_fg2="#94a3b8", grid="#243041",
        series=SERIES_DARK, role=ROLE_DARK, console_bg="#06090d", console_fg="#d6dde8",
        shadow="rgba(0,0,0,0.4)", hero1="#1e3a8a", hero2="#6d28d9",
    ),
}

_current = {"name": "light"}


def current() -> dict:
    return THEMES[_current["name"]]


def set_current(name: str) -> dict:
    _current["name"] = name if name in THEMES else "light"
    return current()


def c(key: str) -> str:
    return current()[key]


def stylesheet(name: str = "light", base_pt: float = 10.0) -> str:
    t = THEMES[name]
    fs = base_pt
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t['text']}; font-size: {fs}pt; }}
QMainWindow, QDialog, #pageRoot {{ background: {t['bg']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border2']};
           padding: 6px 8px; border-radius: 6px; }}

/* ---------- navigation rail ---------- */
#navRail {{ background: {t['rail']}; border: none; }}
#navRail QToolButton {{ background: transparent; color: {t['rail_text']}; border: none; border-radius: 10px;
           padding: 7px 2px 6px 2px; font-size: {fs - 1.5}pt; font-weight: 600; }}
#navRail QToolButton:hover {{ background: {t['rail2']}; color: {t['rail_active']}; }}
#navRail QToolButton:checked {{ background: {t['rail2']}; color: {t['rail_active']}; }}
#navBrand {{ background: transparent; }}

/* ---------- header ---------- */
#headerBar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
#headerTitle {{ font-size: {fs + 3.5}pt; font-weight: 700; color: {t['text']}; background: transparent; }}
#headerSub {{ color: {t['text2']}; background: transparent; }}
#crumb {{ color: {t['text3']}; background: transparent; font-weight: 600; }}

/* ---------- surfaces ---------- */
#card, QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
#cardFlat {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 10px; }}
#cardHover {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
#cardHover:hover {{ border: 1px solid {t['accent']}; background: {t['surface']}; }}
#pane {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
#paneHeader {{ background: transparent; border-bottom: 1px solid {t['border']}; }}
#paneTitle {{ font-weight: 700; font-size: {fs + 0.5}pt; background: transparent; }}
#sectionTitle {{ color: {t['text2']}; font-weight: 700; font-size: {fs - 1}pt; letter-spacing: 0.6px;
           background: transparent; padding-top: 6px; }}
#h1 {{ font-size: {fs + 12}pt; font-weight: 800; background: transparent; }}
#h2 {{ font-size: {fs + 5}pt; font-weight: 700; background: transparent; }}
#h3 {{ font-size: {fs + 2}pt; font-weight: 700; background: transparent; }}
#muted {{ color: {t['text2']}; background: transparent; }}
#faint {{ color: {t['text3']}; background: transparent; }}
#hint {{ color: {t['text3']}; background: transparent; font-size: {fs - 1}pt; }}
#derived {{ color: {t['accent']}; background: transparent; font-size: {fs - 1}pt; }}
#mono {{ font-family: "JetBrains Mono", "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace; }}
#statValue {{ font-size: {fs + 7}pt; font-weight: 700; background: transparent; }}
#statValueSmall {{ font-size: {fs + 3}pt; font-weight: 700; background: transparent; }}
#statLabel {{ color: {t['text2']}; background: transparent; font-size: {fs - 1}pt; }}
#hero {{ border-radius: 16px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
           stop:0 {t['hero1']}, stop:0.55 #3730a3, stop:1 {t['hero2']}); }}
#hero QLabel {{ color: #ffffff; background: transparent; }}
#heroSub {{ color: rgba(255,255,255,0.82); font-size: {fs + 1.5}pt; }}

/* ---------- chips / badges ---------- */
#chip {{ background: {t['surface3']}; color: {t['text2']}; border-radius: 9px; padding: 2px 8px;
           font-size: {fs - 1.5}pt; font-weight: 600; }}
#chipAccent {{ background: {t['accent_soft']}; color: {t['accent']}; border-radius: 9px; padding: 2px 8px;
           font-size: {fs - 1.5}pt; font-weight: 600; }}
#badge_ok, #badge_finished {{ background: {t['success_soft']}; color: {t['success']}; border-radius: 9px;
           padding: 2px 9px; font-weight: 700; font-size: {fs - 1.5}pt; }}
#badge_running, #badge_starting, #badge_queued {{ background: {t['accent_soft']}; color: {t['accent']};
           border-radius: 9px; padding: 2px 9px; font-weight: 700; font-size: {fs - 1.5}pt; }}
#badge_paused, #badge_stopped, #badge_warning, #badge_interrupted {{ background: {t['warning_soft']};
           color: {t['warning']}; border-radius: 9px; padding: 2px 9px; font-weight: 700; font-size: {fs - 1.5}pt; }}
#badge_failed, #badge_aborted, #badge_error {{ background: {t['danger_soft']}; color: {t['danger']};
           border-radius: 9px; padding: 2px 9px; font-weight: 700; font-size: {fs - 1.5}pt; }}
#badge_incomplete, #badge_info {{ background: {t['surface3']}; color: {t['text2']}; border-radius: 9px;
           padding: 2px 9px; font-weight: 700; font-size: {fs - 1.5}pt; }}

/* ---------- buttons ---------- */
QPushButton, QToolButton#btn {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border2']};
           border-radius: 8px; padding: 6px 14px; font-weight: 600; }}
QPushButton:hover, QToolButton#btn:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
QPushButton:pressed {{ background: {t['accent_soft']}; }}
QPushButton:disabled {{ color: {t['text3']}; border-color: {t['border']}; background: {t['surface2']}; }}
QPushButton#primary {{ background: {t['accent']}; color: {t['accent_text']}; border: 1px solid {t['accent']}; }}
QPushButton#primary:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; color: #ffffff; }}
QPushButton#primary:disabled {{ background: {t['border2']}; border-color: {t['border2']}; color: {t['surface']}; }}
QPushButton#run {{ background: {t['success']}; color: #ffffff; border: 1px solid {t['success']}; padding: 6px 18px; }}
QPushButton#run:hover {{ background: #15803d; border-color: #15803d; color: #ffffff; }}
QPushButton#danger {{ color: {t['danger']}; border-color: {t['border2']}; }}
QPushButton#danger:hover {{ background: {t['danger_soft']}; border-color: {t['danger']}; color: {t['danger']}; }}
QPushButton#ghost, QToolButton#ghost {{ background: transparent; border: 1px solid transparent; color: {t['text2']};
           padding: 4px 8px; border-radius: 7px; font-weight: 600; }}
QPushButton#ghost:hover, QToolButton#ghost:hover {{ background: {t['surface3']}; color: {t['text']}; }}
QToolButton#ghost:checked {{ background: {t['accent_soft']}; color: {t['accent']}; }}
QPushButton#heroPrimary {{ background: #ffffff; color: #1e3a8a; border: none; padding: 9px 18px; border-radius: 9px; }}
QPushButton#heroPrimary:hover {{ background: #eef2ff; }}
QPushButton#heroGhost {{ background: rgba(255,255,255,0.12); color: #ffffff; border: 1px solid rgba(255,255,255,0.35);
           padding: 9px 18px; border-radius: 9px; }}
QPushButton#heroGhost:hover {{ background: rgba(255,255,255,0.22); }}
QPushButton#fix {{ background: {t['accent_soft']}; color: {t['accent']}; border: none; padding: 3px 10px;
           border-radius: 6px; font-size: {fs - 1}pt; }}
QPushButton#fix:hover {{ background: {t['accent']}; color: #ffffff; }}
QToolButton#reset {{ background: transparent; border: none; border-radius: 6px; padding: 2px; }}
QPushButton#run[split="true"] {{ border-top-right-radius: 0px; border-bottom-right-radius: 0px; padding-right: 14px; }}
QPushButton#runMore {{ background: {t['success']}; border: 1px solid {t['success']};
           border-left: 1px solid rgba(255,255,255,0.45); border-top-left-radius: 0px;
           border-bottom-left-radius: 0px; padding: 6px 7px; }}
QPushButton#runMore:hover {{ background: #15803d; border-color: #15803d; }}
#segmented {{ background: {t['surface3']}; border-radius: 9px; border: none; }}
QPushButton#segment {{ background: transparent; border: 1px solid transparent; border-radius: 7px;
           color: {t['text2']}; font-weight: 600; padding: 4px 8px; }}
QPushButton#segment:hover {{ color: {t['text']}; }}
QPushButton#segment:checked {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; }}
QPushButton#link {{ background: transparent; border: none; color: {t['accent']}; padding: 2px 4px;
           font-weight: 600; text-align: left; }}
QPushButton#link:hover {{ color: {t['accent_hover']}; text-decoration: underline; }}
#childLabel {{ color: {t['text2']}; background: transparent; }}
#childLabel:disabled {{ color: {t['text3']}; }}
#rowCard {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
#rowCard:hover {{ border: 1px solid {t['accent']}; background: {t['surface2']}; }}
#stepNum {{ background: {t['accent_soft']}; color: {t['accent']}; border-radius: 11px; font-weight: 700; }}
#checkStrip {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
#checkStrip[state="error"] {{ border: 1px solid {t['danger']}; }}
#checkStrip[state="warning"] {{ border: 1px solid {t['warning']}; }}
QToolButton#reset:hover {{ background: {t['surface3']}; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit#input, QDateTimeEdit {{
           background: {t['input']}; border: 1px solid {t['border2']}; border-radius: 7px;
           padding: 4px 8px; min-height: 22px; selection-background-color: {t['selection']};
           selection-color: {t['selection_text']}; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {t['text3']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit#input:focus {{ border: 1px solid {t['accent']}; }}
QLineEdit:disabled, QComboBox:disabled {{ background: {t['surface2']}; color: {t['text3']}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {t['danger']}; background: {t['danger_soft']}; }}
QLineEdit[modified="true"], QComboBox[modified="true"] {{ border-left: 3px solid {t['accent']}; }}
QComboBox::drop-down {{ border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url(:/chev_down); width: 12px; height: 12px; }}
QComboBox::down-arrow:on {{ image: url(:/chev_up); }}
QSpinBox, QDoubleSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
           width: 20px; border: none; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
           width: 20px; border: none; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url(:/chev_up); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url(:/chev_down); width: 10px; height: 10px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover,
QDoubleSpinBox::down-button:hover {{ background: {t['surface3']}; border-radius: 4px; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 8px; border: 1px solid {t['border2']};
           background: {t['input']}; }}
QRadioButton::indicator:checked {{ border: 1px solid {t['accent']}; background: {t['input']}; image: url(:/radio); }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border2']}; border-radius: 8px;
           selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; padding: 4px; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {t['border2']};
           background: {t['input']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; image: url(:/chk); }}
QRadioButton {{ background: transparent; spacing: 8px; }}
QSlider::groove:horizontal {{ height: 4px; background: {t['border']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t['surface']}; border: 2px solid {t['accent']}; width: 14px; height: 14px;
           margin: -6px 0; border-radius: 8px; }}

/* ---------- lists / trees / tables ---------- */
QTreeWidget, QListWidget, QTableWidget, QTreeView, QListView, QTableView {{ background: {t['surface']};
           border: none; alternate-background-color: {t['surface2']}; }}
QTreeWidget::item, QListWidget::item {{ padding: 5px 4px; border-radius: 7px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {t['surface3']}; }}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {{
           background: {t['accent_soft']}; color: {t['text']}; }}
QHeaderView::section {{ background: {t['surface2']}; color: {t['text2']}; border: none;
           border-bottom: 1px solid {t['border']}; padding: 6px 8px; font-weight: 700; font-size: {fs - 1}pt; }}
QTableWidget {{ gridline-color: {t['border']}; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: none; background: transparent; top: 0px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {t['text2']}; padding: 8px 14px; margin-right: 2px;
           border: none; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {t['accent']}; border-bottom: 2px solid {t['accent']}; }}

/* ---------- misc ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollArea#codeBlock {{ background: {t['surface3']}; border: 1px solid {t['border']}; border-radius: 6px; }}
QScrollArea#codeBlock > QWidget {{ background: transparent; }}
#codeText {{ color: {t['text']}; background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border2']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['text3']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border2']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0;
           background: none; }}
QProgressBar {{ background: {t['surface3']}; border: none; border-radius: 5px; height: 10px; text-align: center;
           color: transparent; }}
QProgressBar::chunk {{ border-radius: 5px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
           stop:0 {t['accent']}, stop:1 #7c3aed); }}
QProgressBar#thin {{ max-height: 6px; min-height: 6px; }}
QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; color: {t['text2']}; }}
QStatusBar QLabel {{ background: transparent; color: {t['text2']}; padding: 0 6px; }}
QMenuBar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {t['surface3']}; }}
QMenu {{ background: {t['surface']}; border: 1px solid {t['border2']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QMenu::item:disabled {{ color: {t['text3']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 8px; }}
QPlainTextEdit#console {{ background: {t['console_bg']}; color: {t['console_fg']}; border: none;
           border-radius: 10px; padding: 8px; font-family: "JetBrains Mono", "SF Mono", Menlo, Consolas,
           "DejaVu Sans Mono", monospace; font-size: {fs - 1}pt; }}
QTextBrowser {{ background: {t['surface']}; border: none; }}
QGroupBox {{ border: 1px solid {t['border']}; border-radius: 10px; margin-top: 16px; padding: 10px 8px 8px 8px;
           background: {t['surface']}; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {t['text2']}; }}
"""


_FONT_CACHE: dict = {}


def mpl_font_family(prefs=("Inter", "SF Pro Text", "Helvetica Neue", "Segoe UI", "Arial", "Helvetica",
                           "Noto Sans", "DejaVu Sans")) -> list[str]:
    key = tuple(prefs)
    if key not in _FONT_CACHE:
        from matplotlib import font_manager
        have = {f.name for f in font_manager.fontManager.ttflist}
        fams = [f for f in prefs if f in have] or ["DejaVu Sans"]
        _FONT_CACHE[key] = list(dict.fromkeys(fams[:1] + ["DejaVu Sans"]))
    return _FONT_CACHE[key]


def apply_matplotlib(name: str = "light") -> None:
    t = THEMES[name]
    mpl.rcParams.update({
        "figure.facecolor": t["surface"], "axes.facecolor": t["plot_bg"], "savefig.facecolor": t["plot_bg"],
        "axes.edgecolor": t["border2"], "axes.labelcolor": t["plot_fg2"], "axes.titlecolor": t["plot_fg"],
        "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 8,
        "axes.labelsize": 9, "axes.grid": True, "axes.axisbelow": True,
        "grid.color": t["grid"], "grid.linewidth": 0.7, "grid.alpha": 1.0,
        "xtick.color": t["plot_fg2"], "ytick.color": t["plot_fg2"], "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5, "legend.fontsize": 8.5, "legend.frameon": False,
        "legend.labelcolor": t["plot_fg"], "lines.linewidth": 1.7, "axes.prop_cycle": mpl.cycler(color=t["series"]),
        "font.family": mpl_font_family(),
        "axes.spines.top": False, "axes.spines.right": False, "image.cmap": "inferno",
        "text.color": t["plot_fg"], "axes.formatter.use_mathtext": True, "axes.formatter.limits": (-3, 4),
    })


def publication_rc(font_size: float = 10.0, dark: bool = False) -> dict:
    """Matplotlib rc for exported figures (white paper or dark slides)."""
    fg = "#f0f0f0" if dark else "#111111"
    bg = "#111418" if dark else "#ffffff"
    return {
        "figure.facecolor": bg, "axes.facecolor": bg, "savefig.facecolor": bg, "savefig.edgecolor": bg,
        "axes.edgecolor": fg, "axes.labelcolor": fg, "axes.titlecolor": fg, "text.color": fg,
        "xtick.color": fg, "ytick.color": fg, "font.size": font_size, "axes.labelsize": font_size,
        "axes.titlesize": font_size, "axes.titleweight": "normal", "axes.titlelocation": "center",
        "xtick.labelsize": font_size * 0.9, "ytick.labelsize": font_size * 0.9,
        "legend.fontsize": font_size * 0.85, "legend.frameon": False, "legend.labelcolor": fg,
        "lines.linewidth": 1.5, "axes.linewidth": 0.9, "xtick.direction": "in", "ytick.direction": "in",
        "xtick.top": True, "ytick.right": True, "xtick.major.size": 4, "ytick.major.size": 4,
        "xtick.minor.visible": True, "ytick.minor.visible": True, "axes.spines.top": True,
        "axes.spines.right": True, "axes.grid": False, "font.family": mpl_font_family(("Arial", "Helvetica", "Liberation Sans", "DejaVu Sans")),
        "mathtext.fontset": "dejavusans", "axes.prop_cycle": mpl.cycler(color=[
            "#1f4e9c", "#d1495b", "#2a9d8f", "#e9a03b", "#6a4c93", "#3d5a80", "#8d6e63", "#111111"]),
        "savefig.bbox": "tight", "savefig.pad_inches": 0.03,
    }

