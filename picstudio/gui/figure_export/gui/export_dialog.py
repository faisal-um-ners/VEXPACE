"""Publication export with a live preview.

Every field starts from the plot on screen - labels, legend texts, curve colours and styles, axis scales,
the axis range currently shown and the tick positions - and can be edited: output format and size, font
(including LaTeX typesetting), titles, axis labels with $…$ math, linear/log axes, ranges and ticks, line
colour/style/width and markers, and the legend. The preview on the right is the exported figure itself.
"""
from __future__ import annotations

import copy
import io
import math
import re
import shutil
from dataclasses import dataclass, field

import matplotlib
import numpy as np
from matplotlib.figure import Figure
from PySide6.QtCore import QMimeData, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from . import theme as T
from .plotting import FigureSpec, render
from .widgets import label, push

FORMATS = [("PNG (raster)", "png"), ("PDF (vector)", "pdf"), ("SVG (vector)", "svg"), ("EPS (vector)", "eps"),
           ("TIFF (raster)", "tiff")]
STYLES = [("Publication – white", "publication"), ("Presentation – dark", "dark"), ("Same as screen", "screen")]
PRESETS = [("Single column (3.4 × 2.6 in)", 3.4, 2.6), ("Double column (7.0 × 3.6 in)", 7.0, 3.6),
           ("Slide (10 × 5.6 in)", 10.0, 5.6), ("Square (4 × 4 in)", 4.0, 4.0), ("Custom", None, None)]
FAMILIES = [("Sans-serif (Arial / Helvetica)", "sans"), ("Serif (Times)", "serif"),
            ("LaTeX look (Computer Modern)", "cm"), ("STIX (Times-like, rich math)", "stix"),
            ("DejaVu Sans (Matplotlib default)", "dejavu")]
LEGEND_POS = [("Automatic (best place)", "best", None), ("Upper right", "upper right", None),
              ("Upper left", "upper left", None), ("Lower right", "lower right", None),
              ("Lower left", "lower left", None), ("Center right", "center right", None),
              ("Center left", "center left", None), ("Upper center", "upper center", None),
              ("Lower center", "lower center", None), ("Center", "center", None),
              ("Outside, right of the plot", "center left", (1.02, 0.5)),
              ("Outside, above the plot", "lower center", (0.5, 1.02))]
SCALES = [("Linear", "linear"), ("Logarithmic", "log")]
LINE_STYLES = [("Solid", "-"), ("Dashed", "--"), ("Dotted", ":"), ("Dash-dot", "-."), ("No line", "none")]
MARKERS = [("None", "none"), ("● Circle", "o"), ("■ Square", "s"), ("▲ Triangle", "^"), ("▼ Triangle down", "v"),
           ("◆ Diamond", "D"), ("✕ Cross", "x"), ("+ Plus", "+"), ("· Point", ".")]
CMAPS = ["inferno", "viridis", "magma", "plasma", "cividis", "turbo", "RdBu_r", "coolwarm", "gray", "Greys"]
PALETTES = {
    "Publication": ["#1f4e9c", "#d1495b", "#2a9d8f", "#e9a03b", "#6a4c93", "#3d5a80", "#8d6e63", "#111111"],
    "Colour-blind safe (Okabe–Ito)": ["#0072B2", "#D55E00", "#009E73", "#E69F00", "#CC79A7", "#56B4E9",
                                      "#000000", "#F0E442"],
    "Matplotlib (tab10)": ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f"],
    "Viridis": "viridis",
    "Black & white (line styles)": "bw",
}
MATH_HINT = ("Labels accept LaTeX math between dollar signs, e.g. <code>$V_\\mathrm{gap}$ (kV)</code>, "
             "<code>$n_e$ [m$^{-3}$]</code>, <code>$E/N$ (Td)</code>.")


# ---------------------------------------------------------------------------
# options
@dataclass
class CurveOpts:
    label: str = ""
    color: str = "#1f4e9c"
    style: str = "-"
    width: float = 0.0            # 0 = the default line width (Text tab)
    marker: str = "none"
    msize: float = 4.0


@dataclass
class PanelOpts:
    title: str = ""
    title_hint: str = ""
    xlabel: str = ""
    ylabel: str = ""
    ylabel2: str | None = None
    xscale: str = "linear"
    yscale: str = "linear"
    xlim: tuple = (None, None)
    ylim: tuple = (None, None)
    xticks: str = ""
    yticks: str = ""
    xticks_auto: bool = True
    yticks_auto: bool = True
    legend: bool = True
    curves: list = field(default_factory=list)
    clabel: str | None = None
    cmap: str | None = None


@dataclass
class ExportOptions:
    fmt: str = "png"
    style: str = "publication"
    w: float = 3.4
    h: float = 2.6
    dpi: int = 600
    font_size: float = 9.0
    family: str = "sans"
    usetex: bool = False
    line_width: float = 1.5
    ticks: str = "in"
    minor_ticks: bool = True
    grid: bool = False
    suptitle: str = ""
    markers_per_curve: int = 12
    legend_pos: int = 0
    legend_ncol: int = 1
    legend_frame: bool = False
    legend_scale: float = 0.85
    legend_handle: float = 2.0         # length of the line sample, in font sizes
    legend_gap: float = 0.8            # gap between line sample and text, in font sizes
    legend_rows: float = 0.5           # vertical space between entries, in font sizes
    wspace: float = -1.0               # gap between panel columns, fraction of the figure width (<0: auto)
    hspace: float = -1.0               # gap between panel rows, fraction of the figure height (<0: auto)
    panels: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# text helpers
_SUP = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
        "⁻": "-", "⁺": "+"}
_SUB = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
        "ₑ": "e", "ᵢ": "i", "ₐ": "a", "ₒ": "o", "ₓ": "x", "ₙ": "n", "ₘ": "m", "ₚ": "p", "ₛ": "s", "ₜ": "t",
        "ₖ": "k", "ₗ": "l", "ₕ": "h", "₊": "+", "₋": "-"}
_GREEK = {"α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\varepsilon", "ζ": r"\zeta",
          "η": r"\eta", "θ": r"\theta", "κ": r"\kappa", "λ": r"\lambda", "μ": r"\mu", "µ": r"\mu", "ν": r"\nu",
          "ξ": r"\xi", "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "φ": r"\varphi", "χ": r"\chi",
          "ψ": r"\psi", "ω": r"\omega", "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
          "Σ": r"\Sigma", "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega"}
_SYMBOLS = {"·": r"\cdot", "×": r"\times", "≈": r"\approx", "→": r"\rightarrow", "≤": r"\leq", "≥": r"\geq",
            "°": r"^\circ", "−": "-"}
_LETTER = "A-Za-z" + "".join(k for k in _GREEK if len(k) == 1)


def to_mathtext(s: str) -> str:
    """Turn the plot's plain labels into LaTeX-style math so they typeset well and are easy to edit:
    ``V_gap`` → ``$V_\\mathrm{gap}$``, ``nₑ`` → ``$n_\\mathrm{e}$``, ``m⁻³`` → ``m$^{-3}$``."""
    if not s or "$" in s:
        return s or ""
    s = re.sub("[" + "".join(_SUP) + "]+", lambda m: "$^{" + "".join(_SUP[c] for c in m.group()) + "}$", s)
    s = re.sub(f"([{_LETTER}])([" + "".join(_SUB) + "]+)",
               lambda m: f"${m.group(1)}_\\mathrm{{{''.join(_SUB[c] for c in m.group(2))}}}$", s)
    s = re.sub(rf"(?<![\w$\\])([{_LETTER}])_([A-Za-z0-9]+)(?![\w])",
               lambda m: f"${m.group(1)}_\\mathrm{{{m.group(2)}}}$", s)
    return s.replace("$$", "")            # merge neighbouring math pieces


def tex_safe(s: str) -> str:
    """Make a label valid for real LaTeX (text.usetex): escape special characters outside math and
    replace Unicode Greek letters/symbols with LaTeX commands."""
    if not s:
        return s
    parts = s.split("$")
    if len(parts) % 2 == 0:                    # unbalanced $: leave it, the preview shows the error
        return s
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 0:
            p = re.sub(r"(?<!\\)([_%&#])", r"\\\1", p)
            for ch, cmd in {**_GREEK, **_SYMBOLS}.items():
                if ch in p:
                    p = p.replace(ch, f"${cmd}$" if ch != "−" else "-")
            p = p.replace("–", "--").replace("—", "---")
        else:
            for ch, cmd in {**_GREEK, **_SYMBOLS}.items():
                p = p.replace(ch, cmd + " " if cmd.startswith("\\") else cmd)
        out.append(p)
    return "$".join(out).replace("$$", "")      # merge neighbouring math pieces ($$ would be display math)


def math_safe(s: str) -> str:
    """For math fonts without Unicode Greek (Computer Modern): write Greek letters and symbols that appear in a
    label containing $…$ math as math commands, so they are typeset instead of drawn as empty boxes."""
    if not s or "$" not in s or s.count("$") % 2:
        return s
    parts = s.split("$")
    for i, p in enumerate(parts):
        table = {**_GREEK, **_SYMBOLS}
        for ch, cmd in table.items():
            if ch in p:
                if i % 2 == 0:
                    p = p.replace(ch, f"${cmd}$" if ch != "−" else "-")
                else:
                    p = p.replace(ch, cmd + " " if cmd.startswith("\\") else cmd)
        parts[i] = p
    return "$".join(parts).replace("$$", "")


def latex_available() -> bool:
    return bool(shutil.which("latex") and shutil.which("dvipng"))


def fmt_number(v: float) -> str:
    if v == 0:
        return "0"
    s = f"{v:.6g}"
    return s.replace("e+0", "e").replace("e+", "e").replace("e-0", "e-")


def parse_ticks(text: str):
    """'0, 5, 10' or '1e18 1e19' → list of floats; '' → None (automatic); invalid → raises ValueError."""
    t = text.strip().replace("−", "-")
    if not t:
        return None
    return [float(x) for x in re.split(r"[,;\s]+", t) if x]


def palette_colors(name: str, n: int) -> tuple[list[str], list[str] | None]:
    """Colours (and, for black & white, line styles) for n curves."""
    p = PALETTES[name]
    if p == "bw":
        return ["#000000"] * n, [["-", "--", ":", "-."][i % 4] for i in range(n)]
    if p == "viridis":
        cmap = matplotlib.colormaps["viridis"]
        return [matplotlib.colors.to_hex(cmap(0.05 + 0.85 * i / max(1, n - 1))) for i in range(n)], None
    return [p[i % len(p)] for i in range(n)], None


# ---------------------------------------------------------------------------
# rendering
def _series_of(a):
    return list(a.series) + (list(a.twin.series) if a.twin is not None else [])


def defaults_from_spec(spec: FigureSpec, view=None) -> list[PanelOpts]:
    """Panel options pre-filled from the plot on screen (labels, legend texts, colours and styles, scales,
    the visible range)."""
    screen = T.c("series")
    panels = []
    for i, a in enumerate(spec.axes):
        curves = []
        for k, s in enumerate(_series_of(a)):
            curves.append(CurveOpts(label=to_mathtext(s.label), color=s.color or screen[k % len(screen)],
                                    style=s.style if s.style in ("-", "--", ":", "-.") else "-",
                                    width=float(s.width or 0.0), marker=s.marker or "none",
                                    msize=float(s.markersize or 4.0)))
            if hasattr(spec, "_figure_snapshot") and str(s.style).lower() in ("none", "", " "):
                curves[-1].style = "none"
        p = PanelOpts(title="", title_hint=a.title, xlabel=to_mathtext(a.xlabel), ylabel=to_mathtext(a.ylabel),
                      ylabel2=to_mathtext(a.twin.ylabel) if a.twin is not None else None,
                      xscale=a.xscale if a.xscale in ("linear", "log") else "linear",
                      yscale=a.yscale if a.yscale in ("linear", "log") else "linear",
                      legend=a.legend, curves=curves,
                      clabel=to_mathtext(a.image.clabel) if a.image is not None else None,
                      cmap=a.image.cmap if a.image is not None else None)
        if view is not None and i < len(view) and view[i] is not None:
            (x0, x1), (y0, y1) = view[i]
            p.xlim = (float(f"{x0:.4g}"), float(f"{x1:.4g}"))
            if a.image is None or True:
                p.ylim = (float(f"{y0:.4g}"), float(f"{y1:.4g}"))
        panels.append(p)
    return panels


def build_spec(spec: FigureSpec, opts: ExportOptions) -> FigureSpec:
    s = copy.deepcopy(spec)
    s.suptitle = opts.suptitle.strip()
    for a, p in zip(s.axes, opts.panels):
        a.title = p.title.strip()                         # empty → no title and no space for it
        a.xlabel, a.ylabel = p.xlabel, p.ylabel
        if a.twin is not None and p.ylabel2 is not None:
            a.twin.ylabel = p.ylabel2
        a.xscale, a.yscale = p.xscale, p.yscale
        a.xlim = tuple(p.xlim) if any(v is not None for v in p.xlim) else None
        a.ylim = tuple(p.ylim) if any(v is not None for v in p.ylim) else None
        for axis in ("x", "y"):
            ticks = None
            if not getattr(p, f"{axis}ticks_auto"):
                try:
                    ticks = parse_ticks(getattr(p, f"{axis}ticks"))
                except ValueError:
                    ticks = None
            setattr(a, f"{axis}ticks", ticks)
        a.legend = p.legend
        for se, c in zip(_series_of(a), p.curves):
            se.label, se.color, se.style = c.label, c.color, c.style
            se.width = c.width or None
            se.marker = None if c.marker == "none" else c.marker
            se.markersize = c.msize
            n = len(np.asarray(se.x))
            se.markevery = max(1, n // max(1, opts.markers_per_curve)) if se.marker else None
            if c.style == "none" and not se.marker:
                se.marker, se.markersize, se.markevery = "o", c.msize, max(1, n // max(1, opts.markers_per_curve))
        if a.image is not None:
            if p.clabel is not None:
                a.image.clabel = p.clabel
            if p.cmap:
                a.image.cmap = p.cmap
    if opts.family == "cm" and not opts.usetex:
        s.suptitle = math_safe(s.suptitle)
        for a in s.axes:
            for obj in [a] + ([a.twin] if a.twin is not None else []):
                obj.title, obj.xlabel, obj.ylabel = math_safe(obj.title), math_safe(obj.xlabel), math_safe(obj.ylabel)
                for se in obj.series:
                    se.label = math_safe(se.label)
            if a.image is not None:
                a.image.clabel = math_safe(a.image.clabel)
    if opts.usetex:
        s.suptitle = tex_safe(s.suptitle)
        for a in s.axes:
            for obj in [a] + ([a.twin] if a.twin is not None else []):
                obj.title, obj.xlabel, obj.ylabel = tex_safe(obj.title), tex_safe(obj.xlabel), tex_safe(obj.ylabel)
                for se in obj.series:
                    se.label = tex_safe(se.label)
            for m in a.marks:
                m.text = tex_safe(m.text)
            if a.image is not None:
                a.image.clabel = tex_safe(a.image.clabel)
    return s


def _family_rc(key: str, usetex: bool) -> dict:
    if usetex:
        return {"text.usetex": True, "font.family": "sans-serif" if key in ("sans", "dejavu") else "serif",
                "text.latex.preamble": r"\usepackage{amsmath}"}
    if key == "sans":
        fam = T.mpl_font_family(("Arial", "Helvetica", "Liberation Sans", "Nimbus Sans", "DejaVu Sans"))
        return {"font.family": fam, "mathtext.fontset": "custom", "mathtext.rm": fam[0],
                "mathtext.it": f"{fam[0]}:italic", "mathtext.bf": f"{fam[0]}:bold", "mathtext.sf": fam[0],
                "mathtext.cal": fam[0], "mathtext.fallback": "stixsans"}
    if key == "serif":
        fam = T.mpl_font_family(("Times New Roman", "Times", "Nimbus Roman", "TeX Gyre Termes", "Liberation Serif",
                                 "DejaVu Serif"))
        return {"font.family": fam, "mathtext.fontset": "stix"}
    if key == "cm":
        return {"font.family": ["cmr10", "DejaVu Serif"], "mathtext.fontset": "cm", "axes.formatter.use_mathtext": True}
    if key == "stix":
        return {"font.family": ["STIXGeneral", "DejaVu Serif"], "mathtext.fontset": "stix"}
    return {"font.family": ["DejaVu Sans"], "mathtext.fontset": "dejavusans"}


def export_rc(opts: ExportOptions) -> dict:
    rc = {} if opts.style == "screen" else T.publication_rc(opts.font_size, dark=(opts.style == "dark"))
    fs = opts.font_size
    rc.update({"font.size": fs, "axes.labelsize": fs, "axes.titlesize": fs, "figure.titlesize": fs * 1.1,
               "xtick.labelsize": fs * 0.9, "ytick.labelsize": fs * 0.9, "legend.fontsize": fs * opts.legend_scale,
               "legend.frameon": opts.legend_frame, "lines.linewidth": opts.line_width,
               "xtick.direction": opts.ticks, "ytick.direction": opts.ticks, "axes.grid": opts.grid,
               "xtick.minor.visible": opts.minor_ticks, "ytick.minor.visible": opts.minor_ticks,
               "grid.alpha": 0.35, "grid.linewidth": 0.6})
    rc.update(_family_rc(opts.family, opts.usetex))
    return rc


def _legend_opts(opts: ExportOptions) -> dict:
    _, loc, bbox = LEGEND_POS[max(0, min(opts.legend_pos, len(LEGEND_POS) - 1))]
    lo = {"loc": loc, "ncol": opts.legend_ncol, "frameon": opts.legend_frame, "handlelength": opts.legend_handle,
          "handletextpad": opts.legend_gap, "labelspacing": opts.legend_rows, "columnspacing": 1.2}
    if bbox is not None:
        lo["bbox"] = bbox
    return lo


def apply_spacing(fig, opts: ExportOptions):
    """Gaps between panels of a multi-panel figure (wspace/hspace as fractions of the figure
    width/height, the meaning used by Matplotlib's constrained layout).  Negative = automatic."""
    ws = opts.wspace if opts.wspace is not None and opts.wspace >= 0 else None
    hs = opts.hspace if opts.hspace is not None and opts.hspace >= 0 else None
    if ws is None and hs is None:
        return
    from matplotlib.layout_engine import ConstrainedLayoutEngine
    eng = fig.get_layout_engine()
    if isinstance(eng, ConstrainedLayoutEngine):
        kw = {}
        if ws is not None:
            kw["wspace"] = ws
        if hs is not None:
            kw["hspace"] = hs
        eng.set(**kw)
        return
    # tight / no layout: convert the figure fraction to subplots_adjust (fraction of a panel size)
    gs = next((a.get_subplotspec().get_gridspec() for a in fig.axes if a.get_subplotspec() is not None), None)
    if gs is None:
        return
    nr, nc = gs.get_geometry()
    sp = fig.subplotpars
    kw = {}
    if ws is not None and nc > 1:
        aw = (sp.right - sp.left - (nc - 1) * ws) / nc
        kw["wspace"] = ws / max(aw, 1e-3)
    if hs is not None and nr > 1:
        ah = (sp.top - sp.bottom - (nr - 1) * hs) / nr
        kw["hspace"] = hs / max(ah, 1e-3)
    if kw:
        fig.set_layout_engine(None)
        fig.subplots_adjust(**kw)


def _draw(spec: FigureSpec, opts: ExportOptions, dpi: float, sink):
    spec2 = build_spec(spec, opts)
    with matplotlib.rc_context(export_rc(opts)):
        if hasattr(spec2, "_figure_snapshot"):
            from ..bridge import render_snapshot
            fig, axes = render_snapshot(spec2, opts, dpi)
            apply_spacing(fig, opts)
            return sink(fig, axes)
        fig = Figure(figsize=(opts.w, opts.h), dpi=dpi)
        if opts.style == "screen":
            axes, _ = render(fig, spec2, publication=False, colors=T.c("series"), legend_opts=_legend_opts(opts))
        else:
            axes, _ = render(fig, spec2, publication=True,
                             colors=matplotlib.rcParams["axes.prop_cycle"].by_key()["color"],
                             legend_opts=_legend_opts(opts))
        apply_spacing(fig, opts)
        return sink(fig, axes)


def _save_kw(opts: ExportOptions, fig, dpi) -> dict:
    kw = {"dpi": dpi, "bbox_inches": "tight", "pad_inches": 0.03}
    if opts.style == "screen":
        kw["facecolor"] = fig.get_facecolor()
    return kw


def export_figure(spec: FigureSpec, opts: ExportOptions, path: str) -> str:
    def save(fig, _axes):
        fig.savefig(path, **_save_kw(opts, fig, opts.dpi))
        return path
    return _draw(spec, opts, opts.dpi, save)


def _visible_ticks(ax, axis: str) -> list[float]:
    lo, hi = sorted(ax.get_xlim() if axis == "x" else ax.get_ylim())
    ticks = ax.get_xticks() if axis == "x" else ax.get_yticks()
    tol = 1e-9 * max(abs(lo), abs(hi), 1e-300)
    scale = getattr(ax, "_export_unit_scales", (1.0, 1.0))[0 if axis == "x" else 1]
    return [float(t / scale) for t in ticks if lo - tol <= t <= hi + tol]


def preview_png(spec: FigureSpec, opts: ExportOptions, dpi: float, with_ticks: bool = False):
    """PNG bytes of the export at the given dpi (and, if asked, the tick positions matplotlib chose)."""
    def save(fig, axes):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", **_save_kw(opts, fig, dpi))
        if with_ticks:
            return buf.getvalue(), [(_visible_ticks(ax, "x"), _visible_ticks(ax, "y")) for ax in axes]
        return buf.getvalue()
    return _draw(spec, opts, dpi, save)


# ---------------------------------------------------------------------------
# small widgets
def _fmt_lim(v) -> str:
    return "" if v is None else fmt_number(v)


class _LimitEdit(QLineEdit):
    """Axis limit: a number, or empty for automatic."""

    def __init__(self, placeholder: str = "auto"):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.textChanged.connect(self._validate)

    def value(self):
        t = self.text().strip().replace("−", "-")
        if not t:
            return None
        try:
            v = float(t)
            return v if math.isfinite(v) else None
        except ValueError:
            return None

    def ok(self) -> bool:
        return not self.text().strip() or self.value() is not None

    def _validate(self):
        _mark(self, not self.ok())


def _mark(w, bad: bool):
    w.setProperty("invalid", bad)
    w.style().unpolish(w)
    w.style().polish(w)


class ColorButton(QToolButton):
    """Swatch; a click opens the system colour picker (on macOS the Colors panel). The 'pick a colour from
    the screen' eyedropper is removed: picking outside the app could leave the app unresponsive."""

    def __init__(self, color: str, on_change):
        super().__init__()
        self._on_change = on_change
        self.setFixedSize(30, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Line colour – click to choose")
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, c: str):
        self.color = QColor(c).name()
        self.setStyleSheet(f"QToolButton {{ background: {self.color}; border: 1px solid {T.c('border2')}; "
                           f"border-radius: 5px; }}")

    def _pick(self):
        from .mac_colorpanel import hide_eyedropper
        opts = QColorDialog.ColorDialogOptions()
        no_dropper = getattr(QColorDialog.ColorDialogOption, "NoEyeDropperButton", None)   # Qt >= 6.6
        if no_dropper is not None:
            opts |= no_dropper                       # Windows / Linux: no "Pick Screen Color" button
        hide_eyedropper()                            # macOS Colors panel: hide the eyedropper button
        QTimer.singleShot(0, hide_eyedropper)        # and again once the panel is on screen
        QTimer.singleShot(200, hide_eyedropper)
        c = QColorDialog.getColor(QColor(self.color), self, "Line colour", opts)
        if c.isValid() and c.name() != self.color:
            self.set_color(c.name())
            self._on_change()


def _section(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("sectionTitle")
    lab.setContentsMargins(0, 8, 0, 0)
    return lab


# ---------------------------------------------------------------------------
class ExportDialog(QDialog):
    """Export settings (left) with a live preview of the exported figure (right)."""

    def __init__(self, parent, spec: FigureSpec, view=None, default_name: str = "figure", state: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export figure")
        self.spec = spec
        self.default_name = default_name
        self.defaults = defaults_from_spec(spec, view)
        self.panels = copy.deepcopy(state["panels"]) if state else copy.deepcopy(self.defaults)
        self.suptitle_default = state.get("suptitle", "") if state else ""
        self.spacing_default = (state.get("wspace", -1.0), state.get("hspace", -1.0)) if state else (-1.0, -1.0)
        self.cur = 0
        self._loading = False
        self.settings = QSettings()
        self.resize(1180, 720)
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        # ---------------- settings ----------------
        left = QWidget()
        left.setFixedWidth(450)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        lv.addWidget(label("Export figure", "h3"))
        lv.addWidget(label("Every field starts from the plot on screen and can be edited.", "muted", wrap=True))
        prow = QHBoxLayout()
        self.panel_lab = label("Panel", "muted")
        self.panel_combo = QComboBox()
        for i, a in enumerate(spec.axes):
            self.panel_combo.addItem(f"{i + 1} · {a.title or a.ylabel or 'Panel'}")
        prow.addWidget(self.panel_lab)
        prow.addWidget(self.panel_combo, 1)
        lv.addLayout(prow)
        many = len(spec.axes) > 1
        self.panel_lab.setVisible(many)
        self.panel_combo.setVisible(many)
        self.tabs = QTabWidget()
        lv.addWidget(self.tabs, 1)
        self.tabs.addTab(self._output_tab(), "Output")
        self.tabs.addTab(self._text_tab(), "Text")
        self.tabs.addTab(self._axes_tab(), "Axes")
        self.tabs.addTab(self._lines_tab(), "Lines")
        self.tabs.addTab(self._legend_tab(), "Legend")
        brow = QHBoxLayout()
        self.b_reset = push("Reset to plot", icon_name="reset")
        self.b_reset.setToolTip("Restore titles, labels, colours, styles, scales, ranges and ticks from the plot")
        self.b_reset.clicked.connect(self._reset_all)
        brow.addWidget(self.b_reset)
        self.b_copy = push("Copy", icon_name="copy")
        self.b_copy.setToolTip("Copy the exported figure (PNG at the chosen resolution) to the clipboard")
        self.b_copy.clicked.connect(self._copy)
        brow.addWidget(self.b_copy)
        brow.addStretch()
        cancel = push("Cancel")
        cancel.clicked.connect(self.reject)
        self.b_save = push("Save…", "primary", icon_name="download")
        self.b_save.clicked.connect(self._accept)
        self.b_save.setDefault(True)
        brow.addWidget(cancel)
        brow.addWidget(self.b_save)
        lv.addLayout(brow)
        root.addWidget(left)

        # ---------------- preview ----------------
        right = QFrame()
        right.setObjectName("pane")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(14, 12, 14, 12)
        rv.setSpacing(6)
        hdr = QHBoxLayout()
        hdr.addWidget(label("Preview", "paneTitle"))
        hdr.addStretch()
        self.size_lab = label("", "hint")
        hdr.addWidget(self.size_lab)
        rv.addLayout(hdr)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview.setMinimumSize(300, 240)
        self.preview.setStyleSheet(f"background: {T.c('surface2')}; border-radius: 8px;")
        rv.addWidget(self.preview, 1)
        self.err = label("", "hint", wrap=True)
        self.err.setStyleSheet(f"color: {T.c('danger')};")
        self.err.setVisible(False)
        rv.addWidget(self.err)
        rv.addWidget(label("This is the exported figure, scaled to fit. Fonts and line widths keep their true "
                           "proportion to the page size.", "hint", wrap=True))
        root.addWidget(right, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_preview)
        self.panel_combo.currentIndexChanged.connect(self._switch_panel)
        self._restore_settings()
        self.suptitle.setText(self.suptitle_default)
        self.wspace.setValue(self.spacing_default[0] if self.spacing_default[0] >= 0 else -0.01)
        self.hspace.setValue(self.spacing_default[1] if self.spacing_default[1] >= 0 else -0.01)
        self._load_panel(0)
        self._schedule()

    # -- tab construction -----------------------------------------------------------
    @staticmethod
    def _form():
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(12, 12, 12, 12)
        f.setVerticalSpacing(8)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        return w, f

    @staticmethod
    def _scroll(w):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(w)
        return sc

    def _output_tab(self):
        w, f = self._form()
        self.fmt = QComboBox()
        for t, _ in FORMATS:
            self.fmt.addItem(t)
        self.style_c = QComboBox()
        for t, _ in STYLES:
            self.style_c.addItem(t)
        self.preset = QComboBox()
        for t, _, _ in PRESETS:
            self.preset.addItem(t)
        self.w = QDoubleSpinBox()
        self.h = QDoubleSpinBox()
        for sb in (self.w, self.h):
            sb.setRange(1.0, 30.0)
            sb.setDecimals(2)
            sb.setSingleStep(0.1)
            sb.setSuffix(" in")
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 2400)
        self.dpi.setSingleStep(50)
        self.dpi.setSuffix(" dpi")
        f.addRow("Format", self.fmt)
        f.addRow("Style", self.style_c)
        f.addRow("Size preset", self.preset)
        f.addRow("Width", self.w)
        f.addRow("Height", self.h)
        f.addRow("Resolution", self.dpi)
        f.addRow("", label("Resolution applies to PNG/TIFF and to images inside vector files.", "hint", wrap=True))
        self.preset.currentIndexChanged.connect(self._preset)
        for wd in (self.fmt, self.style_c):
            wd.currentIndexChanged.connect(self._schedule)
        for wd in (self.w, self.h):
            wd.valueChanged.connect(self._size_edited)
        self.dpi.valueChanged.connect(self._schedule)
        return self._scroll(w)

    def _text_tab(self):
        w, f = self._form()
        self.family = QComboBox()
        for t, _ in FAMILIES:
            self.family.addItem(t)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(5, 36)
        self.font_size.setDecimals(1)
        self.font_size.setSingleStep(0.5)
        self.font_size.setSuffix(" pt")
        self.line_w = QDoubleSpinBox()
        self.line_w.setRange(0.3, 6.0)
        self.line_w.setDecimals(2)
        self.line_w.setSingleStep(0.25)
        self.line_w.setSuffix(" pt")
        self.ticks = QComboBox()
        self.ticks.addItems(["Inside", "Outside"])
        self.minor = QCheckBox("Minor tick marks")
        self.grid = QCheckBox("Grid lines")
        self.usetex = QCheckBox("Typeset all text with LaTeX")
        ok = latex_available()
        self.usetex.setEnabled(ok)
        self.usetex.setToolTip("Uses your LaTeX installation (latex + dvipng) for every label, exactly like a "
                               "LaTeX document." if ok else
                               "No LaTeX installation (latex + dvipng) was found. $…$ math in labels is still "
                               "typeset by Matplotlib's built-in math renderer.")
        f.addRow("Font", self.family)
        f.addRow("Font size", self.font_size)
        f.addRow("Line width", self.line_w)
        f.addRow("Tick marks", self.ticks)
        f.addRow("", self.minor)
        f.addRow("", self.grid)
        f.addRow("", self.usetex)
        hint = label(MATH_HINT + ("" if ok else " (No LaTeX installation was found, so Matplotlib's built-in "
                                              "math renderer is used.)"), "hint", wrap=True)
        hint.setTextFormat(Qt.RichText)
        f.addRow("", hint)
        self.family.currentIndexChanged.connect(self._schedule)
        self.ticks.currentIndexChanged.connect(self._schedule)
        for wd in (self.font_size, self.line_w):
            wd.valueChanged.connect(self._schedule)
        for wd in (self.minor, self.grid, self.usetex):
            wd.toggled.connect(self._schedule)
        return self._scroll(w)

    def _axes_tab(self):
        w, f = self._form()
        self.suptitle = QLineEdit()
        self.suptitle.setPlaceholderText("none" + (f" – e.g. {self.spec.suptitle}" if self.spec.suptitle else ""))
        self.suptitle_lab = QLabel("Figure title")
        f.addRow(self.suptitle_lab, self.suptitle)
        show_sup = len(self.spec.axes) > 1 or bool(self.spec.suptitle)
        self.suptitle.setVisible(show_sup)
        self.suptitle_lab.setVisible(show_sup)
        self.wspace, self.hspace = QDoubleSpinBox(), QDoubleSpinBox()
        multi = len(self.spec.axes) > 1
        for sb, txt, tip in ((self.wspace, "Gap between columns (wspace)", "width"),
                             (self.hspace, "Gap between rows (hspace)", "height")):
            sb.setRange(-0.01, 0.5)
            sb.setDecimals(3)
            sb.setSingleStep(0.01)
            sb.setSpecialValueText("auto")
            sb.setValue(-0.01)
            sb.setToolTip(f"Space between panels as a fraction of the figure {tip}; 'auto' keeps the automatic layout.")
            lab = QLabel(txt)
            f.addRow(lab, sb)
            sb.setVisible(multi)
            lab.setVisible(multi)
            sb.valueChanged.connect(self._schedule)
        self.p_title = QLineEdit()
        self.p_x = QLineEdit()
        self.p_y = QLineEdit()
        self.p_y2 = QLineEdit()
        self.p_y2_lab = QLabel("Right y label")
        self.p_clab = QLineEdit()
        self.p_clab_lab = QLabel("Colour-bar label")
        self.p_cmap = QComboBox()
        self.p_cmap.addItems(CMAPS)
        self.p_cmap_lab = QLabel("Colour map")
        f.addRow("Panel title", self.p_title)
        f.addRow("x label", self.p_x)
        f.addRow("y label", self.p_y)
        f.addRow(self.p_y2_lab, self.p_y2)
        f.addRow(self.p_clab_lab, self.p_clab)
        f.addRow(self.p_cmap_lab, self.p_cmap)
        self.ax_w = {}
        for axis in ("x", "y"):
            f.addRow(_section(f"{axis} axis"))
            sc = QComboBox()
            for t, _ in SCALES:
                sc.addItem(t)
            lo, hi = _LimitEdit(), _LimitEdit()
            rng = QWidget()
            h = QHBoxLayout(rng)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            h.addWidget(lo, 1)
            h.addWidget(QLabel("to"))
            h.addWidget(hi, 1)
            b_auto = QPushButton("Auto")
            b_auto.setToolTip("Fit this axis to the data")
            h.addWidget(b_auto)
            ticks = QLineEdit()
            ticks.setPlaceholderText("automatic")
            ticks.setToolTip("Tick positions, separated by commas (e.g. 0, 50, 100, 150 or 1e18, 1e19, 1e20).\n"
                             "Grey text = chosen automatically; type to set your own, Auto to go back.")
            trow = QWidget()
            th = QHBoxLayout(trow)
            th.setContentsMargins(0, 0, 0, 0)
            th.setSpacing(6)
            th.addWidget(ticks, 1)
            t_auto = QPushButton("Auto")
            t_auto.setToolTip("Let the ticks follow the range and scale automatically")
            th.addWidget(t_auto)
            f.addRow("Scale", sc)
            f.addRow("Range", rng)
            f.addRow("Ticks", trow)
            self.ax_w[axis] = dict(scale=sc, lo=lo, hi=hi, ticks=ticks)
            sc.currentIndexChanged.connect(lambda _=None, a=axis: self._scale_changed(a))
            for e in (lo, hi):
                e.textChanged.connect(self._panel_edited)
            b_auto.clicked.connect(lambda _=None, a=lo, b=hi: (a.clear(), b.clear()))
            ticks.textEdited.connect(lambda _=None, a=axis: self._ticks_typed(a))
            t_auto.clicked.connect(lambda _=None, a=axis: self._ticks_auto(a))
        b = QPushButton("Reset this panel to the plot")
        b.setObjectName("ghost")
        b.clicked.connect(self._reset_panel)
        f.addRow("", b)
        f.addRow("", label("Titles appear only when you type one. Ranges start at the limits shown on screen; "
                           "ticks follow the range and scale until you type your own.", "hint", wrap=True))
        for e in (self.p_title, self.p_x, self.p_y, self.p_y2, self.p_clab):
            e.textChanged.connect(self._panel_edited)
        self.p_cmap.currentIndexChanged.connect(self._panel_edited)
        self.suptitle.textChanged.connect(self._schedule)
        return self._scroll(w)

    def _lines_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        f = QFormLayout()
        f.setVerticalSpacing(8)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.scheme = QComboBox()
        self.scheme.addItem("Choose a colour scheme…")
        self.scheme.addItem("As on screen")
        for name in PALETTES:
            self.scheme.addItem(name)
        self.scheme_all = QCheckBox("Apply to all panels")
        self.scheme_all.setChecked(True)
        self.n_markers = QSpinBox()
        self.n_markers.setRange(2, 200)
        self.n_markers.setSuffix(" per curve")
        self.n_markers.setToolTip("Markers are spread evenly along each curve (simulation curves have thousands "
                                  "of points)")
        f.addRow("Colours", self.scheme)
        f.addRow("", self.scheme_all)
        f.addRow("Markers", self.n_markers)
        v.addLayout(f)
        v.addWidget(_section("Curves"))
        v.addWidget(label("Legend text, colour, line and marker of each curve. Clear the text to leave a curve "
                          "out of the legend.", "hint", wrap=True))
        self.curves_box = QWidget()
        self.curves_lay = QVBoxLayout(self.curves_box)
        self.curves_lay.setContentsMargins(0, 0, 0, 0)
        self.curves_lay.setSpacing(8)
        v.addWidget(self.curves_box)
        v.addStretch()
        self.curve_w: list[dict] = []
        self.scheme.activated.connect(self._apply_scheme)
        self.n_markers.valueChanged.connect(self._schedule)
        return self._scroll(w)

    def _legend_tab(self):
        w, f = self._form()
        self.lg_show = QCheckBox("Show the legend in this panel")
        self.lg_pos = QComboBox()
        for t, _, _ in LEGEND_POS:
            self.lg_pos.addItem(t)
        self.lg_ncol = QSpinBox()
        self.lg_ncol.setRange(1, 6)
        self.lg_scale = QSpinBox()
        self.lg_scale.setRange(50, 150)
        self.lg_scale.setSingleStep(5)
        self.lg_scale.setSuffix(" % of font size")
        self.lg_frame = QCheckBox("Frame around the legend")

        def em_spin(lo, hi, step, tip):
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi)
            sb.setDecimals(1)
            sb.setSingleStep(step)
            sb.setSuffix(" × font size")
            sb.setToolTip(tip)
            return sb
        self.lg_handle = em_spin(0.0, 6.0, 0.25, "Length of the line sample in front of each entry – shorten it "
                                                 "to make the legend narrower")
        self.lg_gap = em_spin(0.0, 3.0, 0.1, "Space between the line sample and its text")
        self.lg_rows = em_spin(0.0, 3.0, 0.1, "Vertical space between legend entries")
        f.addRow("", self.lg_show)
        f.addRow("Position", self.lg_pos)
        f.addRow("Columns", self.lg_ncol)
        f.addRow("Text size", self.lg_scale)
        f.addRow("Line length", self.lg_handle)
        f.addRow("Gap to text", self.lg_gap)
        f.addRow("Row spacing", self.lg_rows)
        f.addRow("", self.lg_frame)
        f.addRow("", label("The text of each entry, its colour and line style are set in the Lines tab.", "hint",
                           wrap=True))
        self.lg_show.toggled.connect(self._panel_edited)
        self.lg_pos.currentIndexChanged.connect(self._schedule)
        self.lg_ncol.valueChanged.connect(self._schedule)
        self.lg_scale.valueChanged.connect(self._schedule)
        self.lg_frame.toggled.connect(self._schedule)
        for sb in (self.lg_handle, self.lg_gap, self.lg_rows):
            sb.valueChanged.connect(self._schedule)
        return self._scroll(w)

    # -- curves ------------------------------------------------------------------------------
    def _build_curves(self, p: PanelOpts):
        while self.curves_lay.count():
            wd = self.curves_lay.takeAt(0).widget()
            if wd is not None:
                wd.hide()
                wd.setParent(None)
                wd.deleteLater()
        self.curve_w = []
        if not p.curves:
            self.curves_lay.addWidget(label("This panel has no curves (e.g. a colour map).", "hint"))
            return
        for c in p.curves:
            card = QFrame()
            card.setObjectName("cardFlat")
            g = QGridLayout(card)
            g.setContentsMargins(10, 8, 10, 8)
            g.setHorizontalSpacing(6)
            g.setVerticalSpacing(6)
            col = ColorButton(c.color, self._curves_edited)
            text = QLineEdit(c.label)
            text.setPlaceholderText("(not in legend)")
            style = QComboBox()
            for t, _ in LINE_STYLES:
                style.addItem(t)
            style.setCurrentIndex(max(0, [s for _, s in LINE_STYLES].index(c.style)
                                      if c.style in [s for _, s in LINE_STYLES] else 0))
            width = QDoubleSpinBox()
            width.setRange(0.0, 8.0)
            width.setDecimals(2)
            width.setSingleStep(0.25)
            width.setSpecialValueText("default")
            width.setSuffix(" pt")
            width.setValue(c.width)
            marker = QComboBox()
            for t, _ in MARKERS:
                marker.addItem(t)
            mk = [m for _, m in MARKERS]
            marker.setCurrentIndex(mk.index(c.marker) if c.marker in mk else 0)
            msize = QDoubleSpinBox()
            msize.setRange(1.0, 20.0)
            msize.setDecimals(1)
            msize.setSuffix(" pt")
            msize.setValue(c.msize)
            msize.setToolTip("Marker size")
            g.addWidget(col, 0, 0)
            g.addWidget(text, 0, 1, 1, 3)
            g.addWidget(QLabel("Line"), 1, 0)
            g.addWidget(style, 1, 1)
            g.addWidget(width, 1, 2, 1, 2)
            g.addWidget(QLabel("Marker"), 2, 0)
            g.addWidget(marker, 2, 1)
            g.addWidget(msize, 2, 2, 1, 2)
            g.setColumnStretch(1, 1)
            g.setColumnStretch(2, 1)
            text.textChanged.connect(self._curves_edited)
            style.currentIndexChanged.connect(self._curves_edited)
            width.valueChanged.connect(self._curves_edited)
            marker.currentIndexChanged.connect(self._curves_edited)
            msize.valueChanged.connect(self._curves_edited)
            self.curves_lay.addWidget(card)
            self.curve_w.append(dict(color=col, text=text, style=style, width=width, marker=marker, msize=msize))

    def _curves_edited(self, *_):
        if self._loading:
            return
        self._store_panel()
        self._schedule()

    def _apply_scheme(self, idx: int):
        if idx <= 0:
            return
        name = self.scheme.itemText(idx)
        self._store_panel()
        targets = range(len(self.panels)) if self.scheme_all.isChecked() else [self.cur]
        for i in targets:
            p = self.panels[i]
            if name == "As on screen":
                for c, d in zip(p.curves, self.defaults[i].curves):
                    c.color, c.style = d.color, d.style
                continue
            cols, styles = palette_colors(name, len(p.curves))
            for k, c in enumerate(p.curves):
                c.color = cols[k]
                if styles is not None:
                    c.style = styles[k]
        self.scheme.setCurrentIndex(0)
        self._load_panel(self.cur)
        self._schedule()

    # -- panel state ---------------------------------------------------------------------------
    def _load_panel(self, i: int):
        self._loading = True
        self.cur = i
        p = self.panels[i]
        a = self.spec.axes[i]
        self.p_title.setText(p.title)
        self.p_title.setPlaceholderText("none" + (f" – e.g. {p.title_hint}" if p.title_hint else ""))
        self.p_x.setText(p.xlabel)
        self.p_y.setText(p.ylabel)
        has2 = p.ylabel2 is not None
        self.p_y2.setText(p.ylabel2 or "")
        for wd in (self.p_y2, self.p_y2_lab):
            wd.setVisible(has2)
        img = a.image is not None
        for wd in (self.p_clab, self.p_clab_lab, self.p_cmap, self.p_cmap_lab):
            wd.setVisible(img)
        self.p_clab.setText(p.clabel or "")
        if p.cmap in CMAPS:
            self.p_cmap.setCurrentIndex(CMAPS.index(p.cmap))
        elif p.cmap:
            self.p_cmap.addItem(p.cmap)
            self.p_cmap.setCurrentIndex(self.p_cmap.count() - 1)
        for axis in ("x", "y"):
            wd = self.ax_w[axis]
            wd["scale"].setCurrentIndex([s for _, s in SCALES].index(getattr(p, f"{axis}scale")))
            lo, hi = getattr(p, f"{axis}lim")
            wd["lo"].setText(_fmt_lim(lo))
            wd["hi"].setText(_fmt_lim(hi))
            self._show_ticks(axis, getattr(p, f"{axis}ticks"), getattr(p, f"{axis}ticks_auto"))
        self.ax_w["y"]["scale"].setEnabled(not img)
        self._build_curves(p)
        self.lg_show.setChecked(p.legend)
        self.lg_show.setEnabled(bool(p.curves))
        self._loading = False

    def _show_ticks(self, axis: str, text: str, auto: bool):
        e = self.ax_w[axis]["ticks"]
        e.blockSignals(True)
        e.setText(text)
        e.blockSignals(False)
        e.setStyleSheet(f"color: {T.c('text3')};" if auto else "")
        bad = False
        if not auto:
            try:
                parse_ticks(text)
            except ValueError:
                bad = True
        _mark(e, bad)

    def _store_panel(self):
        p = self.panels[self.cur]
        p.title = self.p_title.text()
        p.xlabel = self.p_x.text()
        p.ylabel = self.p_y.text()
        if p.ylabel2 is not None:
            p.ylabel2 = self.p_y2.text()
        if p.clabel is not None:
            p.clabel = self.p_clab.text()
        if p.cmap is not None:
            p.cmap = self.p_cmap.currentText()
        for axis in ("x", "y"):
            wd = self.ax_w[axis]
            setattr(p, f"{axis}scale", SCALES[wd["scale"].currentIndex()][1])
            setattr(p, f"{axis}lim", (wd["lo"].value(), wd["hi"].value()))
            if not getattr(p, f"{axis}ticks_auto"):
                setattr(p, f"{axis}ticks", wd["ticks"].text())
        p.legend = self.lg_show.isChecked()
        for c, wd in zip(p.curves, self.curve_w):
            c.label = wd["text"].text()
            c.color = wd["color"].color
            c.style = LINE_STYLES[wd["style"].currentIndex()][1]
            c.width = wd["width"].value()
            c.marker = MARKERS[wd["marker"].currentIndex()][1]
            c.msize = wd["msize"].value()

    def _switch_panel(self, i):
        if i < 0:
            return
        self._store_panel()
        self._load_panel(i)
        self._schedule()

    def _panel_edited(self, *_):
        if self._loading:
            return
        self._store_panel()
        self._schedule()

    def _ticks_typed(self, axis: str):
        p = self.panels[self.cur]
        setattr(p, f"{axis}ticks_auto", False)
        self._show_ticks(axis, self.ax_w[axis]["ticks"].text(), False)
        self._panel_edited()

    def _ticks_auto(self, axis: str):
        setattr(self.panels[self.cur], f"{axis}ticks_auto", True)
        self._show_ticks(axis, self.ax_w[axis]["ticks"].text(), True)
        self._panel_edited()

    def _scale_changed(self, axis: str):
        if self._loading:
            return
        wd = self.ax_w[axis]
        if wd["scale"].currentIndex() == 1:
            lo, hi = self._log_range(axis)
            if lo is not None:
                wd["lo"].setText(fmt_number(lo))
                wd["hi"].setText(fmt_number(hi))
            else:                                      # a log axis cannot reach zero or below
                for e in (wd["lo"], wd["hi"]):
                    v = e.value()
                    if v is not None and v <= 0:
                        e.clear()
        else:                                          # back to linear: fit the data again
            wd["lo"].clear()
            wd["hi"].clear()
        setattr(self.panels[self.cur], f"{axis}ticks_auto", True)   # ticks of the other scale make no sense
        self._show_ticks(axis, wd["ticks"].text(), True)
        self._panel_edited()

    def _log_range(self, axis: str):
        """Sensible log range for the curves of this panel: whole decades, at most six decades below the
        largest value (simulation data often contain tiny values near zero)."""
        a = self.spec.axes[self.cur]
        vals = []
        for se in a.series:
            v = np.asarray(se.x if axis == "x" else se.y, dtype=float)
            v = v[np.isfinite(v) & (v > 0)]
            if v.size:
                vals.append((float(v.min()), float(v.max())))
        if not vals:
            return None, None
        vmin, vmax = min(v[0] for v in vals), max(v[1] for v in vals)
        hi = 10 ** math.ceil(math.log10(vmax))
        lo = 10 ** math.floor(math.log10(max(vmin, vmax * 1e-6)))
        if lo >= hi:
            lo = hi / 10
        return lo, hi

    def _reset_panel(self):
        self.panels[self.cur] = copy.deepcopy(self.defaults[self.cur])
        self._load_panel(self.cur)
        self._schedule()

    def _reset_all(self):
        self.panels = copy.deepcopy(self.defaults)
        self.suptitle.clear()
        self.wspace.setValue(-0.01)
        self.hspace.setValue(-0.01)
        self._load_panel(self.cur)
        self._schedule()

    def _preset(self, i):
        _, w, h = PRESETS[i]
        if w is not None:
            for sb, val in ((self.w, w), (self.h, h)):
                sb.blockSignals(True)
                sb.setValue(val)
                sb.blockSignals(False)
            self._schedule()

    def _size_edited(self, *_):
        cur = (round(self.w.value(), 2), round(self.h.value(), 2))
        idx = next((k for k, (_, w, h) in enumerate(PRESETS) if w is not None and (w, h) == cur), len(PRESETS) - 1)
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(idx)
        self.preset.blockSignals(False)
        self._schedule()

    # -- options -----------------------------------------------------------------------------
    def options(self) -> ExportOptions:
        self._store_panel()
        return ExportOptions(
            fmt=FORMATS[self.fmt.currentIndex()][1], style=STYLES[self.style_c.currentIndex()][1],
            w=self.w.value(), h=self.h.value(), dpi=self.dpi.value(), font_size=self.font_size.value(),
            family=FAMILIES[self.family.currentIndex()][1], usetex=self.usetex.isChecked() and self.usetex.isEnabled(),
            line_width=self.line_w.value(), ticks="in" if self.ticks.currentIndex() == 0 else "out",
            minor_ticks=self.minor.isChecked(), grid=self.grid.isChecked(), suptitle=self.suptitle.text(),
            markers_per_curve=self.n_markers.value(), legend_pos=self.lg_pos.currentIndex(),
            legend_ncol=self.lg_ncol.value(), legend_frame=self.lg_frame.isChecked(),
            legend_scale=self.lg_scale.value() / 100.0, legend_handle=self.lg_handle.value(),
            legend_gap=self.lg_gap.value(), legend_rows=self.lg_rows.value(), panels=copy.deepcopy(self.panels),
            wspace=self._gap(self.wspace), hspace=self._gap(self.hspace))

    @staticmethod
    def _gap(sb):
        return sb.value() if sb.value() >= 0 else -1.0

    def state(self) -> dict:
        """Plot-specific edits, so reopening the dialog for the same plot keeps them."""
        self._store_panel()
        return {"panels": copy.deepcopy(self.panels), "suptitle": self.suptitle.text(),
                "wspace": self._gap(self.wspace), "hspace": self._gap(self.hspace)}

    def ext(self) -> str:
        return FORMATS[self.fmt.currentIndex()][1]

    _SETTINGS = (("fmt", 0, int), ("style", 0, int), ("preset", 0, int), ("w", 3.4, float), ("h", 2.6, float),
                 ("dpi", 600, int), ("family", 0, int), ("font", 9.0, float), ("line_width", 1.5, float),
                 ("ticks", 0, int), ("minor", True, "bool"), ("grid", False, "bool"), ("usetex", False, "bool"),
                 ("legend_pos", 0, int), ("legend_ncol", 1, int), ("legend_scale", 85, int),
                 ("legend_frame", False, "bool"), ("markers", 12, int), ("legend_handle", 2.0, float),
                 ("legend_gap", 0.8, float), ("legend_rows", 0.5, float))

    def _widgets_for_settings(self):
        return {"fmt": self.fmt, "style": self.style_c, "preset": self.preset, "w": self.w, "h": self.h,
                "dpi": self.dpi, "family": self.family, "font": self.font_size, "line_width": self.line_w,
                "ticks": self.ticks, "minor": self.minor, "grid": self.grid, "usetex": self.usetex,
                "legend_pos": self.lg_pos, "legend_ncol": self.lg_ncol, "legend_scale": self.lg_scale,
                "legend_frame": self.lg_frame, "markers": self.n_markers, "legend_handle": self.lg_handle,
                "legend_gap": self.lg_gap, "legend_rows": self.lg_rows}

    def _restore_settings(self):
        wmap = self._widgets_for_settings()
        for wd in wmap.values():
            wd.blockSignals(True)
        for key, default, cast in self._SETTINGS:
            raw = self.settings.value(f"export/{key}", default)
            try:
                if cast == "bool":
                    val = raw if isinstance(raw, bool) else str(raw).lower() == "true"
                else:
                    val = cast(raw)
            except (TypeError, ValueError):
                val = default
            wd = wmap[key]
            if isinstance(wd, QComboBox):
                wd.setCurrentIndex(max(0, min(int(val), wd.count() - 1)))
            elif isinstance(wd, QCheckBox):
                wd.setChecked(bool(val) and wd.isEnabled())
            else:
                wd.setValue(val)
        for wd in wmap.values():
            wd.blockSignals(False)

    def _save_settings(self):
        for key, wd in self._widgets_for_settings().items():
            if isinstance(wd, QComboBox):
                val = wd.currentIndex()
            elif isinstance(wd, QCheckBox):
                val = wd.isChecked()
            else:
                val = wd.value()
            self.settings.setValue(f"export/{key}", val)

    def _invalid_fields(self):
        bad = [e for axis in ("x", "y") for e in (self.ax_w[axis]["lo"], self.ax_w[axis]["hi"]) if not e.ok()]
        for axis in ("x", "y"):
            if not getattr(self.panels[self.cur], f"{axis}ticks_auto"):
                try:
                    parse_ticks(self.ax_w[axis]["ticks"].text())
                except ValueError:
                    bad.append(self.ax_w[axis]["ticks"])
        return bad

    def _accept(self):
        bad = self._invalid_fields()
        if bad:
            self.tabs.setCurrentIndex(2)
            bad[0].setFocus()
            return
        self._save_settings()
        self.accept()

    def _copy(self):
        opts = self.options()
        try:
            data = preview_png(self.spec, opts, min(opts.dpi, 600))
        except Exception as exc:  # pragma: no cover - same errors as the preview
            self.err.setText(f"Cannot copy: {exc}")
            self.err.setVisible(True)
            return
        img = QImage.fromData(data, "PNG")
        md = QMimeData()
        md.setImageData(img)
        QGuiApplication.clipboard().setMimeData(md)
        self.size_lab.setText("Copied to the clipboard")
        QTimer.singleShot(1500, self._schedule)

    # -- preview -----------------------------------------------------------------------------
    def _schedule(self, *_):
        if not self._loading:
            self._timer.start()

    def _update_preview(self):
        opts = self.options()
        dpr = self.devicePixelRatioF() or 1.0
        aw, ah = max(200, self.preview.width() - 24), max(160, self.preview.height() - 24)
        pdpi = max(30.0, min(aw / opts.w, ah / opts.h, 220.0))
        px = (round(opts.w * opts.dpi), round(opts.h * opts.dpi))
        fmt = FORMATS[self.fmt.currentIndex()][0].split(" ")[0]
        self.size_lab.setText(f"{opts.w:g} × {opts.h:g} in  ·  {fmt}" +
                              (f"  ·  {px[0]} × {px[1]} px" if opts.fmt in ("png", "tiff") else "  ·  vector"))
        try:
            data, ticks = preview_png(self.spec, opts, pdpi * dpr, with_ticks=True)
        except Exception as exc:  # invalid LaTeX, impossible limits …
            msg = (str(exc).strip().splitlines() or [type(exc).__name__])
            math_err = "Parse" in type(exc).__name__ or "Expected" in msg[0] or "Unknown symbol" in msg[0]
            self.err.setText(("A label has invalid math between $…$ – check braces and commands. " + msg[0])
                             if math_err else "Cannot draw the figure with these settings: " + msg[-1])
            self.err.setVisible(True)
            self.b_save.setEnabled(False)
            self.b_copy.setEnabled(False)
            return
        # automatic ticks: show what matplotlib chose for this page size, range and scale
        for i, (xt, yt) in enumerate(ticks[:len(self.panels)]):
            p = self.panels[i]
            for axis, vals in (("x", xt), ("y", yt)):
                if getattr(p, f"{axis}ticks_auto"):
                    txt = ", ".join(fmt_number(v) for v in vals)
                    setattr(p, f"{axis}ticks", txt)
                    if i == self.cur:
                        self._show_ticks(axis, txt, True)
        pm = QPixmap()
        pm.loadFromData(data, "PNG")
        pm.setDevicePixelRatio(dpr)
        self.preview.setPixmap(pm)
        self.err.setVisible(False)
        self.b_save.setEnabled(not self._invalid_fields())
        self.b_copy.setEnabled(True)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._schedule()

