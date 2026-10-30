"""Adapt existing VEXPACE Matplotlib artists to the PASCHEN export window.

The complete figure is copied, including meshes, scatter, colour bars, patches
and inset axes. Metadata drives the original export controls; rendering edits
the independent copy instead of rebuilding and losing unsupported artists.
"""
from __future__ import annotations

import copy
import sys
import numpy as np
import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import PathCollection, PolyCollection
from matplotlib.colors import to_hex
from matplotlib.markers import MarkerStyle
from matplotlib.ticker import AutoMinorLocator, FixedLocator, FuncFormatter, MaxNLocator
from PySide6.QtGui import QFont, QColor, QPalette
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from .gui import theme as T
from .gui import icons
from .gui.plotting import AxesSpec, FigureSpec, ImageSpec, Series
from .gui.export_dialog import ExportDialog, export_figure


def _all_axes(fig):
    axes, seen = [], set()
    def add(ax):
        if id(ax) in seen:
            return
        seen.add(id(ax)); axes.append(ax)
        for child in ax.child_axes:
            add(child)
    for ax in fig.axes:
        add(ax)
    return axes


def _unit_scale(axis):
    from ...post.ticks import UnitFormatter
    formatter = axis.get_major_formatter()
    return 10.0**formatter.exp if isinstance(formatter, UnitFormatter) else 1.0


def _hex(value, fallback="C0"):
    try:
        return to_hex(value)
    except (ValueError, TypeError):
        return to_hex(fallback)


def _label(artist):
    text = artist.get_label() or ""
    return "" if str(text).startswith("_") else str(text)


def _capture_axes(ax):
    xs, ys = _unit_scale(ax.xaxis), _unit_scale(ax.yaxis)
    spec = AxesSpec(title=ax.get_title(), xlabel=ax.get_xlabel(), ylabel=ax.get_ylabel(),
                    xscale=ax.get_xscale(), yscale=ax.get_yscale(), legend=ax.get_legend() is not None)
    bindings = []
    legend = ax.get_legend()
    legend_labels = {}
    if legend is not None:
        for handle, text in zip(getattr(legend, "legend_handles", getattr(legend, "legendHandles", [])), legend.get_texts()):
            if hasattr(handle, "get_color"):
                legend_labels.setdefault(_hex(handle.get_color()), text.get_text())
    for i, line in enumerate(ax.lines):
        color = _hex(line.get_color())
        spec.series.append(Series(np.asarray(line.get_xdata(), float)/xs,
                                  np.asarray(line.get_ydata(), float)/ys,
                                  label=_label(line) or legend_labels.get(color, ""), color=color,
                                  style=line.get_linestyle(), width=line.get_linewidth(),
                                  marker=line.get_marker(), alpha=line.get_alpha() or 1,
                                  markersize=line.get_markersize(), markevery=line.get_markevery()))
        bindings.append(("line", i))
    for i, collection in enumerate(ax.collections):
        if isinstance(collection, PathCollection):
            offsets = np.asanyarray(collection.get_offsets())
            if offsets.ndim != 2 or not len(offsets):
                continue
            face = collection.get_facecolors()
            sizes = collection.get_sizes()
            spec.series.append(Series(np.asarray(offsets[:, 0], float)/xs, np.asarray(offsets[:, 1], float)/ys,
                                      label=_label(collection), color=_hex(face[0] if len(face) else "C0"),
                                      style="none", marker="o", markersize=float(np.sqrt(np.median(sizes))) if len(sizes) else 4))
            bindings.append(("scatter", i))
    mappables = list(ax.images) + [c for c in ax.collections
                                 if not isinstance(c, PathCollection) and c.get_array() is not None]
    if mappables:
        im = mappables[0]
        data = np.asanyarray(im.get_array())
        cb = getattr(im, "colorbar", None)
        spec.image = ImageSpec(data=data if data.ndim == 2 else data.reshape(1, -1),
                              extent=(*ax.get_xlim(), *ax.get_ylim()), cmap=im.get_cmap().name,
                              clabel=cb.ax.get_ylabel() if cb is not None else "",
                              vmin=im.norm.vmin, vmax=im.norm.vmax)
    spec._artist_bindings = bindings
    spec._source_series = copy.deepcopy(spec.series)
    spec._unit_scales = (xs, ys)
    spec._image_bindings = [("image", list(ax.images).index(im), _unit_scale(im.colorbar.ax.yaxis) if getattr(im,"colorbar",None) else 1)
                            if im in ax.images else
                            ("collection", list(ax.collections).index(im), _unit_scale(im.colorbar.ax.yaxis) if getattr(im,"colorbar",None) else 1)
                            for im in mappables]
    return spec


def snapshot_spec(fig):
    fig.canvas.draw()
    snapshot = copy.deepcopy(fig)
    axes = _all_axes(snapshot)
    panel_axes = [(i, ax) for i, ax in enumerate(axes) if getattr(ax, "_colorbar", None) is None and ax.get_visible()]
    panels, view = [], []
    for i, ax in panel_axes:
        panel = _capture_axes(ax)
        panel._axis_index = i
        panels.append(panel)
        xs, ys = panel._unit_scales
        view.append((tuple(v/xs for v in ax.get_xlim()), tuple(v/ys for v in ax.get_ylim())))
    spec = FigureSpec(panels, suptitle=fig._suptitle.get_text() if fig._suptitle is not None else "")
    spec._figure_snapshot = snapshot
    return spec, view


def _font(text, size, color):
    text.set_fontfamily(matplotlib.rcParams["font.family"])
    text.set_fontsize(size)
    text.set_color(color)
    text.set_usetex(matplotlib.rcParams["text.usetex"])
    text.set_math_fontfamily(matplotlib.rcParams["mathtext.fontset"])


def _format_unit(axis, scale):
    if scale != 1:
        axis.set_major_formatter(FuncFormatter(lambda v, pos: f"{v/scale:g}"))
    else:
        from ...post.ticks import UnitFormatter
        if isinstance(axis.get_major_formatter(), UnitFormatter):
            axis.set_major_formatter(FuncFormatter(lambda v, pos: f"{v:g}"))


def render_snapshot(spec, opts, dpi):
    # build_spec already copied the full snapshot together with panel metadata.
    fig = spec._figure_snapshot
    FigureCanvasAgg(fig)
    fig.set_size_inches(opts.w, opts.h, forward=False)
    fig.set_dpi(dpi)
    rc = matplotlib.rcParams
    fig.set_facecolor(rc["figure.facecolor"])
    fig.set_edgecolor(rc["figure.edgecolor"])
    all_axes = _all_axes(fig)
    drawn_axes = []
    for ax in all_axes:
        ax.set_facecolor(rc["axes.facecolor"])
        for text in ax.texts:
            _font(text, opts.font_size, rc["text.color"])
        for side, spine in ax.spines.items():
            spine.set_color(rc["axes.edgecolor"])
            spine.set_linewidth(rc["axes.linewidth"])
            spine.set_visible(rc.get("axes.spines."+side, spine.get_visible()))
        ax.tick_params(which="both", labelsize=opts.font_size*.9,
                       colors=rc["xtick.color"], direction=opts.ticks,
                       top=rc["xtick.top"], right=rc["ytick.right"])
        _font(ax.title, opts.font_size, rc["text.color"])
        _font(ax.xaxis.label, opts.font_size, rc["axes.labelcolor"])
        _font(ax.yaxis.label, opts.font_size, rc["axes.labelcolor"])
        _font(ax.xaxis.offsetText, opts.font_size*.9, rc["xtick.color"])
        _font(ax.yaxis.offsetText, opts.font_size*.9, rc["ytick.color"])
        for label in ax.get_xticklabels()+ax.get_yticklabels():
            _font(label, opts.font_size*.9, rc["xtick.color"])
    for meta in spec.axes:
        ax = all_axes[meta._axis_index]
        drawn_axes.append(ax)
        xs, ys = meta._unit_scales
        ax._export_unit_scales = (xs, ys)
        ax.set_title(meta.title)
        ax.set_xlabel(meta.xlabel); ax.set_ylabel(meta.ylabel)
        ax.set_xscale(meta.xscale); ax.set_yscale(meta.yscale)
        ax.autoscale(enable=True, axis="both")
        for name, scale in (("x", xs), ("y", ys)):
            lim = getattr(meta, name+"lim")
            if lim is not None:
                getattr(ax, "set_"+name+"lim")(*(None if v is None else v*scale for v in lim))
            axis = getattr(ax, name+"axis")
            ticks = getattr(meta, name+"ticks")
            if ticks is not None:
                axis.set_major_locator(FixedLocator(np.asarray(ticks)*scale))
            elif getattr(meta, name+"scale") == "linear":
                axis.set_major_locator(MaxNLocator(nbins=6))
            if opts.minor_ticks and getattr(meta, name+"scale") == "linear":
                axis.set_minor_locator(AutoMinorLocator())
            elif not opts.minor_ticks:
                getattr(ax, "tick_params")(axis=name, which="minor", bottom=False, top=False, left=False, right=False)
            _format_unit(axis, scale)
        if opts.grid:
            ax.grid(True, alpha=.35, linewidth=.6)
        else:
            ax.grid(False)
        for se, old, (kind, index) in zip(meta.series, meta._source_series, meta._artist_bindings):
            if kind == "line":
                line = ax.lines[index]
                original_color = _hex(line.get_color())
                line.set_label(se.label if se.label else "_nolegend_")
                line.set_color(se.color)
                line.set_linestyle(se.style)
                line.set_linewidth(se.width or opts.line_width)
                line.set_marker(se.marker or "None")
                line.set_markersize(se.markersize or 4)
                line.set_markevery(se.markevery)
                for collection in ax.collections:
                    if isinstance(collection, PolyCollection) and collection.get_array() is None:
                        face = collection.get_facecolors()
                        if len(face) and _hex(face[0]) == original_color:
                            collection.set_facecolor(se.color)
            else:
                points = ax.collections[index]
                points.set_label(se.label if se.label else "_nolegend_")
                if se.color != old.color:
                    points.set_array(None); points.set_facecolor(se.color); points.set_edgecolor(se.color)
                if se.markersize != old.markersize:
                    points.set_sizes([se.markersize**2])
                if se.marker and se.marker != old.marker:
                    marker = MarkerStyle(se.marker)
                    points.set_paths([marker.get_path().transformed(marker.get_transform())])
                if se.marker is None:
                    points.set_visible(False)
                    points.set_label("_nolegend_")
                if se.style.lower() not in ("none", "", " "):
                    # The original Lines controls also allow a connecting line
                    # for a series originally drawn as particles/points.
                    ax.plot(np.asarray(se.x)*xs, np.asarray(se.y)*ys,
                            color=se.color, linestyle=se.style,
                            linewidth=se.width or opts.line_width,
                            label=se.label if se.marker is None else "_nolegend_")
        if meta.image is not None:
            for kind, index, scale in meta._image_bindings:
                im = ax.images[index] if kind == "image" else ax.collections[index]
                im.set_cmap(meta.image.cmap)
                cb = getattr(im, "colorbar", None)
                if cb is not None:
                    cb.set_label(meta.image.clabel or "", fontsize=opts.font_size)
                    _format_unit(cb.ax.yaxis, scale)
                    cb.formatter = cb.ax.yaxis.get_major_formatter()
                    cb.update_ticks()
        legend = ax.get_legend()
        if legend is not None:
            old_handles = getattr(legend, "legend_handles", getattr(legend, "legendHandles", []))
            old_text = [t.get_text() for t in legend.get_texts()]
            legend.remove()
        else:
            old_handles, old_text = [], []
        handles, labels = ax.get_legend_handles_labels()
        if not handles and old_handles:
            handles, labels = old_handles, old_text
        if meta.legend and handles:
            from .gui.export_dialog import _legend_opts
            lo = _legend_opts(opts)
            bbox = lo.pop("bbox", None)
            if bbox is not None:
                lo["bbox_to_anchor"] = bbox
            legend = ax.legend(handles, labels, fontsize=opts.font_size*opts.legend_scale, **lo)
            for text in legend.get_texts():
                _font(text, opts.font_size*opts.legend_scale, rc["text.color"])
    if fig._suptitle is not None:
        fig._suptitle.set_text(spec.suptitle)
        _font(fig._suptitle, opts.font_size*1.1, rc["text.color"])
    elif spec.suptitle:
        fig.suptitle(spec.suptitle, fontsize=opts.font_size*1.1)
    return fig, drawn_axes


def _style_dialog(dialog, name):
    t = T.set_current(name)
    families = ["Inter", "SF Pro Text", ".AppleSystemUIFont", "Segoe UI", "Helvetica Neue", "Noto Sans",
                "Ubuntu", "Cantarell", "DejaVu Sans", "Arial"]
    font = QFont(); font.setFamilies(families)
    base = 13.0 if sys.platform == "darwin" else 10.0
    font.setPointSizeF(base); dialog.setFont(font)
    palette = dialog.palette()
    for role, key in ((QPalette.Window,"bg"),(QPalette.WindowText,"text"),(QPalette.Base,"surface"),
                      (QPalette.Text,"text"),(QPalette.Button,"surface"),(QPalette.ButtonText,"text"),
                      (QPalette.Highlight,"accent"),(QPalette.HighlightedText,"accent_text")):
        palette.setColor(role, QColor(t[key]))
    dialog.setPalette(palette)
    qss = (T.stylesheet(name, base).replace("url(:/chk)", f'url("{icons.check_icon_file()}")')
           .replace("url(:/chev_down)", f'url("{icons.ui_asset_file("chev_down",t["text2"])}")')
           .replace("url(:/chev_up)", f'url("{icons.ui_asset_file("chev_up",t["text2"])}")')
           .replace("url(:/radio)", f'url("{icons.ui_asset_file("radio_dot",t["accent"])}")'))
    dialog.setStyleSheet(qss)


def open_export(plot):
    spec, view = snapshot_spec(plot.fig)
    if not spec.axes:
        return
    name = "light"            # the export dialog is always light (also for the dark live monitor)
    T.set_current(name)
    key = (spec.signature(), tuple((a.title,a.xlabel,a.ylabel) for a in spec.axes))
    if not hasattr(plot, "_export_state"):
        plot._export_state = {}
    default_name = getattr(plot, "export_name", "figure")
    dialog = ExportDialog(plot, spec, view, default_name, state=plot._export_state.get(key))
    _style_dialog(dialog, name)
    accepted = dialog.exec() == QDialog.Accepted
    plot._export_state[key] = dialog.state()
    if not accepted:
        return
    opts = dialog.options(); ext = opts.fmt
    path, _ = QFileDialog.getSaveFileName(plot, "Export figure", f"{default_name}.{ext}", f"{ext.upper()} (*.{ext})")
    if not path:
        return
    if not path.lower().endswith("."+ext):
        path += "."+ext
    try:
        export_figure(spec, opts, path)
    except Exception as exc:
        QMessageBox.warning(plot, "Export failed", f"The figure could not be written:\n{exc}")
