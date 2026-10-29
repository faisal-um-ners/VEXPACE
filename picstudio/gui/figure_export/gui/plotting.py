"""Interactive Matplotlib canvas driven by a declarative plot specification.

The same ``FigureSpec`` is drawn on screen (theme style, live updates that keep
the user's zoom) and re-drawn for export with a clean publication style, so
exported figures are real vector/raster renders - not screenshots.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field

import matplotlib
matplotlib.use("QtAgg")
import numpy as np  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT  # noqa: E402
from matplotlib.colors import LogNorm, Normalize, SymLogNorm  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtCore import Qt, Signal  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QMenu, QSizePolicy, QToolButton,  # noqa: E402
                               QVBoxLayout, QWidget)

from . import theme as T  # noqa: E402
from .widgets import icon_button, label  # noqa: E402


# ---------------------------------------------------------------------------
@dataclass
class Series:
    x: np.ndarray
    y: np.ndarray
    label: str = ""
    color: str | None = None
    style: str = "-"
    width: float | None = None
    marker: str | None = None
    alpha: float = 1.0
    fill: bool = False
    step: bool = False
    markersize: float | None = None
    markevery: int | None = None


@dataclass
class ImageSpec:
    data: np.ndarray                 # (ny, nx)
    extent: tuple                    # (x0, x1, y0, y1)
    log: bool = False
    cmap: str = "inferno"
    clabel: str = ""
    vmin: float | None = None
    vmax: float | None = None
    symlog: bool = False


@dataclass
class Mark:
    kind: str                        # vline | hline | point | text | vspan
    x: float | None = None
    y: float | None = None
    x2: float | None = None
    text: str = ""
    color: str | None = None
    style: str = "--"


@dataclass
class AxesSpec:
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    xscale: str = "linear"
    yscale: str = "linear"
    series: list[Series] = field(default_factory=list)
    image: ImageSpec | None = None
    marks: list[Mark] = field(default_factory=list)
    legend: bool = True
    xlim: tuple | None = None
    ylim: tuple | None = None
    twin: "AxesSpec | None" = None
    empty_text: str = ""
    xticks: list | None = None
    yticks: list | None = None


@dataclass
class FigureSpec:
    axes: list[AxesSpec]
    rows: int = 1
    cols: int = 1
    sharex: bool = False
    suptitle: str = ""

    def signature(self):
        sig = []
        for a in self.axes:
            sig.append((len(a.series), a.image is not None, a.twin is not None and len(a.twin.series),
                        a.xscale, a.yscale, tuple(s.label for s in a.series), len(a.marks)))
        return (self.rows, self.cols, tuple(sig))


# ---------------------------------------------------------------------------
def _draw_axes(ax, spec: AxesSpec, fig, publication: bool, colors: list[str], legend_opts: dict | None = None):
    ax.set_title(spec.title)
    ax.set_xlabel(spec.xlabel)
    ax.set_ylabel(spec.ylabel)
    artists = {"lines": [], "image": None, "cbar": None}
    has_data = False
    if spec.image is not None and spec.image.data.size:
        im = spec.image
        norm = _norm_for(im)
        h = ax.imshow(im.data, origin="lower", aspect="auto", extent=im.extent, cmap=im.cmap, norm=norm,
                      interpolation="nearest")
        cb = fig.colorbar(h, ax=ax, pad=0.015, fraction=0.05)
        cb.set_label(im.clabel)
        cb.outline.set_visible(False)
        artists["image"], artists["cbar"] = h, cb
        has_data = True
        ax.grid(False)
    for i, s in enumerate(spec.series):
        col = s.color or colors[i % len(colors)]
        x = np.asarray(s.x, dtype=float)
        y = np.asarray(s.y, dtype=float)
        if spec.yscale == "log":
            y = np.where(y > 0, y, np.nan)
        kw = _line_kw(s, col)
        if s.step:
            (ln,) = ax.step(x, y, where="post", **kw)
        else:
            (ln,) = ax.plot(x, y, **kw)
        if s.fill and x.size:
            ax.fill_between(x, np.nan_to_num(y), alpha=0.12, color=col, linewidth=0)
        artists["lines"].append(ln)
        has_data = has_data or bool(x.size)
    for m in spec.marks:
        col = m.color or ("#888888" if publication else T.c("text3"))
        if m.kind == "vline" and m.x is not None:
            ax.axvline(m.x, color=col, linestyle=m.style, linewidth=1.0)
            if m.text:
                # label on the side of the line with more room, so it is never cut off at the axes edge
                xs = [np.asarray(s_.x, float) for s_ in spec.series if getattr(s_, "x", None) is not None]
                xs = np.concatenate([a[np.isfinite(a)] for a in xs]) if xs else np.array([])
                right_half = False
                if xs.size:
                    lo, hi = float(np.min(xs)), float(np.max(xs))
                    if spec.xscale == "log" and lo > 0 and m.x > 0:
                        lo, hi, xm = math.log10(lo), math.log10(hi), math.log10(m.x)
                    else:
                        xm = m.x
                    right_half = hi > lo and (xm - lo) / (hi - lo) > 0.6
                ax.annotate(m.text, (m.x, 1.0), xycoords=("data", "axes fraction"),
                            xytext=(-3 if right_half else 3, -12), ha="right" if right_half else "left",
                            textcoords="offset points", fontsize=8, color=col)
        elif m.kind == "hline" and m.y is not None:
            ax.axhline(m.y, color=col, linestyle=m.style, linewidth=1.0)
            if m.text:
                ax.annotate(m.text, (0.0, m.y), xycoords=("axes fraction", "data"), xytext=(4, 3),
                            textcoords="offset points", fontsize=8, color=col)
        elif m.kind == "vspan" and m.x is not None and m.x2 is not None:
            ax.axvspan(m.x, m.x2, color=col, alpha=0.08, linewidth=0)
        elif m.kind == "point" and m.x is not None and m.y is not None:
            ax.plot([m.x], [m.y], marker="o", markersize=8, color=col, markeredgecolor="white", zorder=5)
            if m.text:
                ax.annotate(m.text, (m.x, m.y), xytext=(8, 6), textcoords="offset points", fontsize=8.5,
                            color=col, fontweight="bold")
        elif m.kind == "text":
            xx = m.x if m.x is not None else 0.02
            ax.text(xx, m.y if m.y is not None else 0.95, m.text, transform=ax.transAxes, fontsize=8.5,
                    color=col, va="top" if (m.y or 0.95) > 0.5 else "bottom", ha="right" if xx > 0.5 else "left")
    if spec.xscale != "linear":
        ax.set_xscale(spec.xscale)
    if spec.yscale != "linear":
        try:
            ax.set_yscale(spec.yscale)
        except ValueError:
            pass
    if spec.xlim:
        ax.set_xlim(*spec.xlim)
    if spec.ylim:
        ax.set_ylim(*spec.ylim)
    _apply_ticks(ax, spec)
    if spec.twin is not None:
        ax2 = ax.twinx()
        ax2.set_ylabel(spec.twin.ylabel)
        if not publication:
            ax2.spines["right"].set_visible(True)
            ax2.grid(False)
        for i, s in enumerate(spec.twin.series):
            col = s.color or colors[(i + len(spec.series)) % len(colors)]
            (ln,) = ax2.plot(s.x, s.y, **_line_kw(s, col))
            artists["lines"].append(ln)
        if spec.twin.yscale != "linear":
            ax2.set_yscale(spec.twin.yscale)
        if spec.twin.ylim:
            ax2.set_ylim(*spec.twin.ylim)
        artists["twin"] = ax2
        ax2.yaxis.label.set_color(spec.twin.series[0].color if spec.twin.series and spec.twin.series[0].color
                                  else ax2.yaxis.label.get_color())
    if spec.legend:
        handles, labels = ax.get_legend_handles_labels()
        if spec.twin is not None and "twin" in artists:
            h2, l2 = artists["twin"].get_legend_handles_labels()
            handles += h2
            labels += l2
        if labels:
            lo = legend_opts or {}
            kw = {"loc": lo.get("loc", "best")}
            if lo.get("bbox") is not None:
                kw["bbox_to_anchor"] = lo["bbox"]
                kw["borderaxespad"] = 0.0
            for k in ("ncol", "frameon", "fontsize", "handlelength", "handletextpad", "labelspacing", "columnspacing"):
                if k in lo:
                    kw[k] = lo[k]
            ax.legend(handles, labels, **kw)
    if not has_data and spec.empty_text:
        ax.text(0.5, 0.5, spec.empty_text, transform=ax.transAxes, ha="center", va="center",
                color=("#888888" if publication else T.c("text3")), fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
    return artists


def _line_kw(s: Series, col: str) -> dict:
    style = s.style if s.style not in ("none", "None", "") else "None"
    kw = dict(color=col, linestyle=style, alpha=s.alpha, label=s.label or None)
    if s.width:
        kw["linewidth"] = s.width
    if s.marker and s.marker not in ("none", "None"):
        kw["marker"] = s.marker
        kw["markersize"] = s.markersize or 4
        if s.markevery and s.markevery > 1:
            kw["markevery"] = s.markevery
    return kw


def _apply_ticks(ax, spec: AxesSpec):
    """Explicit tick positions (export dialog). Requested limits are kept; with automatic limits the axis
    may grow to show every tick."""
    for axis, ticks, lim, scale in (("x", spec.xticks, spec.xlim, spec.xscale), ("y", spec.yticks, spec.ylim,
                                                                                 spec.yscale)):
        if ticks is None:
            continue
        vals = [float(t) for t in ticks if math.isfinite(float(t)) and (scale != "log" or float(t) > 0)]
        (ax.set_xticks if axis == "x" else ax.set_yticks)(vals)
        if lim:                                   # requested limits win over tick positions
            (ax.set_xlim if axis == "x" else ax.set_ylim)(*lim)


def _norm_for(im: ImageSpec):
    d = im.data[np.isfinite(im.data)]
    if im.log:
        pos = d[d > 0]
        if pos.size == 0:
            return Normalize()
        vmax = im.vmax or float(np.nanmax(pos))
        vmin = im.vmin or max(float(np.nanmin(pos)), vmax * 1e-6)
        return LogNorm(vmin=vmin, vmax=vmax)
    if im.symlog and d.size:
        m = float(np.nanmax(np.abs(d))) or 1.0
        return SymLogNorm(linthresh=m * 1e-3, vmin=-m, vmax=m)
    if d.size == 0:
        return Normalize()
    return Normalize(vmin=im.vmin if im.vmin is not None else float(np.nanmin(d)),
                     vmax=im.vmax if im.vmax is not None else float(np.nanmax(d)))


def render(fig: Figure, spec: FigureSpec, publication: bool = False, colors: list[str] | None = None,
           legend_opts: dict | None = None):
    fig.clear()
    colors = colors or (list(matplotlib.rcParams["axes.prop_cycle"].by_key().get("color", [])) or T.c("series"))
    axes, arts = [], []
    first = None
    for i, a in enumerate(spec.axes):
        ax = fig.add_subplot(spec.rows, spec.cols, i + 1, sharex=first if spec.sharex else None)
        first = first or ax
        arts.append(_draw_axes(ax, a, fig, publication, colors, legend_opts))
        axes.append(ax)
    if spec.suptitle:
        fig.suptitle(spec.suptitle, fontweight="bold")
    try:
        fig.tight_layout(pad=0.6 if not publication else 0.3)
    except Exception:
        pass
    return axes, arts


# ---------------------------------------------------------------------------
class PlotCanvas(QWidget):
    """Matplotlib canvas with a compact toolbar, hover read-out and export."""

    clicked = Signal(float, float)     # data coordinates of a left click on the first axes

    def __init__(self, title: str = "", parent=None, toolbar: bool = True, height: int | None = None,
                 log_toggle: bool = True, export_name: str = "figure"):
        super().__init__(parent)
        self.export_name = export_name
        self._spec: FigureSpec | None = None
        self._axes = []
        self._arts = []
        self._user_view = False
        self._force_log: bool | None = None
        self.fig = Figure(figsize=(5, 3), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas.setMinimumHeight(height or 160)
        self._nav = NavigationToolbar2QT(self.canvas, self)
        self._nav.hide()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self.bar = QWidget()
        hb = QHBoxLayout(self.bar)
        hb.setContentsMargins(2, 0, 2, 0)
        hb.setSpacing(1)
        self.title_lab = label(title, "paneTitle")
        hb.addWidget(self.title_lab)
        hb.addStretch()
        self.readout = label("", "hint")
        hb.addWidget(self.readout)
        hb.addSpacing(6)
        self.b_home = icon_button("fit", "Reset view (double-click the plot)", size=16)
        self.b_pan = icon_button("pan", "Pan (drag)", size=16, checkable=True)
        self.b_zoom = icon_button("zoom", "Zoom to rectangle", size=16, checkable=True)
        self.b_log = icon_button("log", "Logarithmic y-axis", size=16, checkable=True)
        self.b_exp = icon_button("image", "Export figure (PNG / PDF / SVG)…", size=16)
        self.b_csv = icon_button("csv", "Export plotted data as CSV…", size=16)
        self.b_copy = icon_button("copy", "Copy image to clipboard", size=16)
        # in narrow panels the three export buttons fold into one menu button
        self.b_more = icon_button("export", "Export or copy this plot", size=16)
        more = QMenu(self.b_more)
        more.addAction("Export figure (PNG / PDF / SVG)…", self.export_dialog)
        more.addAction("Export plotted data as CSV…", self.export_csv)
        more.addAction("Copy image to clipboard", self.copy_image)
        self.b_more.setMenu(more)
        self.b_more.setPopupMode(QToolButton.InstantPopup)
        self.b_more.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.b_more.setVisible(False)
        # plot tools appear when the pointer is over the plot (progressive disclosure: a page with four plots
        # no longer shows 24+ icons at rest); right-click offers the same actions
        self.tools = QWidget()
        tl = QHBoxLayout(self.tools)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(1)
        for b in (self.b_home, self.b_pan, self.b_zoom, self.b_log, self.b_exp, self.b_csv, self.b_copy, self.b_more):
            tl.addWidget(b)
        sp = self.tools.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.tools.setSizePolicy(sp)
        self.tools.setVisible(False)
        hb.addWidget(self.tools)
        self.b_log.setVisible(log_toggle)
        self.b_home.clicked.connect(self.reset_view)
        self.b_pan.clicked.connect(self._pan)
        self.b_zoom.clicked.connect(self._zoom)
        self.b_log.toggled.connect(self._toggle_log)
        self.b_exp.clicked.connect(self.export_dialog)
        self.b_csv.clicked.connect(self.export_csv)
        self.b_copy.clicked.connect(self.copy_image)
        self.bar.setVisible(toolbar)
        v.addWidget(self.bar)
        v.addWidget(self.canvas, 1)
        self.canvas.mpl_connect("motion_notify_event", self._on_move)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", lambda e: self._mark_user_view())
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def enterEvent(self, e):  # noqa: N802
        self.tools.setVisible(True)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        # keep the tools visible while a mode is active, so the state stays visible
        if not (self.b_pan.isChecked() or self.b_zoom.isChecked() or self.b_log.isChecked()):
            self.tools.setVisible(False)
        super().leaveEvent(e)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        compact = self.width() < 540
        if self.b_more.isVisible() != compact:
            for b in (self.b_exp, self.b_csv, self.b_copy):
                b.setVisible(not compact)
            self.b_more.setVisible(compact)

    # -- API ------------------------------------------------------------------
    def set_title(self, t: str):
        self.title_lab.setText(t)

    def set_spec(self, spec: FigureSpec, keep_view: bool = True):
        spec = self._apply_log(spec)
        if (keep_view and self._spec is not None and self._axes and
                spec.signature() == self._spec.signature() and self._update_in_place(spec)):
            self._spec = spec
            return
        self._spec = spec
        views = [(ax.get_xlim(), ax.get_ylim()) for ax in self._axes] if (keep_view and self._user_view) else None
        self._axes, self._arts = render(self.fig, spec, colors=T.c("series"))
        if views and len(views) == len(self._axes):
            for ax, (xl, yl) in zip(self._axes, views):
                ax.set_xlim(xl)
                ax.set_ylim(yl)
        else:
            self._user_view = False
        self.canvas.draw_idle()

    def spec(self) -> FigureSpec | None:
        return self._spec

    def clear(self, text: str = ""):
        self._spec = None
        self._axes, self._arts = [], []
        self.fig.clear()
        if text:
            self.fig.text(0.5, 0.5, text, ha="center", va="center", color=T.c("text3"), fontsize=10)
        self.canvas.draw_idle()

    def reset_view(self):
        self._user_view = False
        if self._spec is not None:
            sp = self._spec
            self._spec = None
            self.set_spec(sp, keep_view=False)
        self._nav.mode = ""
        self.b_pan.setChecked(False)
        self.b_zoom.setChecked(False)

    def restyle(self):
        if self._spec is not None:
            sp = self._spec
            self._spec = None
            self.fig.set_facecolor(T.c("surface"))
            self.set_spec(sp, keep_view=False)
        else:
            self.fig.set_facecolor(T.c("surface"))
            self.canvas.draw_idle()

    # -- internals ------------------------------------------------------------------
    def _apply_log(self, spec: FigureSpec) -> FigureSpec:
        if self._force_log is None:
            return spec
        for a in spec.axes:
            if a.image is None:
                a.yscale = "log" if self._force_log else ("linear" if a.yscale == "log" else a.yscale)
        return spec

    def _toggle_log(self, on: bool):
        self._force_log = on
        if self._spec is not None:
            sp = self._spec
            self._spec = None
            self.set_spec(sp, keep_view=False)

    def _update_in_place(self, spec: FigureSpec) -> bool:
        try:
            for ax, art, a in zip(self._axes, self._arts, spec.axes):
                lines = art["lines"]
                all_series = list(a.series) + (list(a.twin.series) if a.twin is not None else [])
                if len(lines) != len(all_series):
                    return False
                for ln, s in zip(lines, all_series):
                    y = np.asarray(s.y, dtype=float)
                    if a.yscale == "log":
                        y = np.where(y > 0, y, np.nan)
                    ln.set_data(np.asarray(s.x, dtype=float), y)
                if a.image is not None and art["image"] is not None:
                    art["image"].set_data(a.image.data)
                    art["image"].set_extent(a.image.extent)
                    art["image"].set_norm(_norm_for(a.image))
                ax.set_title(a.title)
                ax.set_xlabel(a.xlabel)
                ax.set_ylabel(a.ylabel)
                if a.twin is not None and "twin" in art:
                    art["twin"].set_ylabel(a.twin.ylabel)
                if not self._user_view:
                    ax.relim()
                    ax.autoscale_view()
                    if a.xlim:
                        ax.set_xlim(*a.xlim)
                    if a.ylim:
                        ax.set_ylim(*a.ylim)
                    if "twin" in art:
                        art["twin"].relim()
                        art["twin"].autoscale_view()
            self.canvas.draw_idle()
            return True
        except Exception:
            return False

    def _mark_user_view(self):
        if self._nav.mode:
            self._user_view = True

    def _pan(self):
        self.b_zoom.setChecked(False)
        self._nav.pan()
        self._user_view = True

    def _zoom(self):
        self.b_pan.setChecked(False)
        self._nav.zoom()

    def _on_press(self, e):
        if e.dblclick:
            self.reset_view()
            return
        if e.button == 1 and e.inaxes is not None and not self._nav.mode and e.xdata is not None:
            self.clicked.emit(float(e.xdata), float(e.ydata))

    def _on_scroll(self, e):
        ax = e.inaxes
        if ax is None or e.xdata is None:
            return
        f = 0.8 if e.button == "up" else 1.25
        for which, center in (("x", e.xdata), ("y", e.ydata)):
            get = ax.get_xlim if which == "x" else ax.get_ylim
            setf = ax.set_xlim if which == "x" else ax.set_ylim
            scale = ax.get_xscale() if which == "x" else ax.get_yscale()
            lo, hi = get()
            if scale == "log" and lo > 0 and hi > 0 and center > 0:
                lc, llo, lhi = math.log10(center), math.log10(lo), math.log10(hi)
                setf(10 ** (lc - (lc - llo) * f), 10 ** (lc + (lhi - lc) * f))
            else:
                setf(center - (center - lo) * f, center + (hi - center) * f)
        self._user_view = True
        self.canvas.draw_idle()

    def _on_move(self, e):
        if e.inaxes is None or e.xdata is None:
            self.readout.setText("")
            return
        ax = e.inaxes
        xl = ax.get_xlabel().split("[")[-1].rstrip("]") if "[" in ax.get_xlabel() else ""
        yl = ax.get_ylabel().split("[")[-1].rstrip("]") if "[" in ax.get_ylabel() else ""
        self.readout.setText(f"x = {e.xdata:.5g} {xl}   y = {e.ydata:.5g} {yl}")

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("Reset view", self.reset_view)
        a = m.addAction("Logarithmic y-axis")
        a.setCheckable(True)
        a.setChecked(self.b_log.isChecked())
        a.toggled.connect(self.b_log.setChecked)
        m.addSeparator()
        m.addAction("Export figure…", self.export_dialog)
        m.addAction("Export data (CSV)…", self.export_csv)
        m.addAction("Copy image", self.copy_image)
        m.exec(self.mapToGlobal(pos))

    # -- export ------------------------------------------------------------------
    def current_view(self):
        """Axis limits currently shown on screen, one (xlim, ylim) per panel."""
        try:
            return [(tuple(ax.get_xlim()), tuple(ax.get_ylim())) for ax in self._axes]
        except Exception:
            return None

    def export_dialog(self):
        if self._spec is None:
            return
        from .export_dialog import ExportDialog, export_figure
        key = self._spec.signature()
        if not hasattr(self, "_export_state"):
            self._export_state = {}
        dlg = ExportDialog(self, self._spec, self.current_view(), self.export_name, state=self._export_state.get(key))
        ok = dlg.exec() == QDialog.Accepted
        self._export_state[key] = dlg.state()          # reopening the dialog for this plot keeps the edits
        if not ok:
            return
        opts = dlg.options()
        ext = opts.fmt
        path, _ = QFileDialog.getSaveFileName(self, "Export figure", f"{self.export_name}.{ext}",
                                              f"{ext.upper()} (*.{ext})")
        if not path:
            return
        if not path.lower().endswith("." + ext):
            path += "." + ext
        try:
            export_figure(self._spec, opts, path)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export failed", f"The figure could not be written:\n{exc}")

    def export_to(self, path: str, w: float, h: float, dpi: int, font: float, style: str = "publication",
                  titles: bool = False):
        """Non-interactive export with the default options (labels etc. as on screen)."""
        from .export_dialog import ExportOptions, defaults_from_spec, export_figure
        opts = ExportOptions(fmt=path.rsplit(".", 1)[-1].lower(), style=style, w=w, h=h, dpi=dpi, font_size=font,
                             titles=titles, panels=defaults_from_spec(self._spec, self.current_view()))
        return export_figure(self._spec, opts, path)

    def export_csv(self):
        if self._spec is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export data", f"{self.export_name}.csv", "CSV (*.csv)")
        if not path:
            return
        self.write_csv(path)

    def write_csv(self, path: str):
        cols, names = [], []
        for a in self._spec.axes:
            for s in list(a.series) + (list(a.twin.series) if a.twin else []):
                nm = s.label or a.ylabel or "y"
                cols += [np.asarray(s.x), np.asarray(s.y)]
                on_main = any(s is t for t in a.series)          # identity: Series hold arrays
                names += [f"{nm} | x: {a.xlabel}", f"{nm} | y: {a.ylabel if on_main else a.twin.ylabel}"]
        n = max((len(c) for c in cols), default=0)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(names)
            for i in range(n):
                w.writerow([f"{c[i]:.9g}" if i < len(c) else "" for c in cols])

    def copy_image(self):
        buf = io.BytesIO()
        self.fig.savefig(buf, format="png", dpi=200, facecolor=self.fig.get_facecolor())
        img = QImage.fromData(buf.getvalue(), "PNG")
        QGuiApplication.clipboard().setImage(img)

