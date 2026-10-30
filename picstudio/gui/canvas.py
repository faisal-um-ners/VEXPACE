"""Matplotlib canvas embedded in Qt."""
from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")
import contextlib  # noqa: E402

import matplotlib as mpl  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget  # noqa: E402


class ExportToolbar(NavigationToolbar2QT):
    """Every Matplotlib Save action opens the shared publication exporter."""
    def save_figure(self, *args):
        self.parent().export_figure()


class PlotWidget(QWidget):
    def __init__(self, parent=None, nrows=1, ncols=1, figsize=(6, 4), style=None):
        """style: a theme name ("dark"/"light") that this plot keeps whatever the application theme
        is (the live monitor stays dark); None follows the application theme."""
        super().__init__(parent)
        self._style = style
        with self.style_context():
            self.fig = Figure(figsize=figsize, layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumSize(120, 80)
        self.toolbar = ExportToolbar(self.canvas, self)
        self.toolbar.setObjectName("plotToolbar")
        from PySide6.QtCore import QSize
        self.toolbar.setIconSize(QSize(16, 16))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas, 1)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(150, 120)
        self.set_grid(nrows, ncols)

    def style_context(self):
        """Context in which artists of this plot are created (fixed style or the current theme)."""
        if not self._style:
            return contextlib.nullcontext()
        from .theme import matplotlib_rc
        return mpl.rc_context(matplotlib_rc(self._style))

    def set_grid(self, nrows, ncols):
        with self.style_context():
            self.fig.clear()
            self.fig.set_facecolor(mpl.rcParams["figure.facecolor"])
            self.axes = [self.fig.add_subplot(nrows, ncols, i + 1) for i in range(nrows * ncols)]
        self._cbars = {}
        return self.axes

    def colorbar(self, im, ax):
        if im is None:
            return
        cb = self._cbars.get(id(ax))
        if cb is not None:
            try:
                cb.remove()
            except Exception:  # noqa: BLE001
                pass
        with self.style_context():
            self._cbars[id(ax)] = self.fig.colorbar(im, ax=ax, shrink=0.85)

    def remove_colorbar(self, ax):
        cb = self._cbars.pop(id(ax), None)
        if cb is not None:
            try:
                cb.remove()
            except Exception:  # noqa: BLE001
                pass

    def draw(self):
        if self._style:
            # Tick and grid lines are created lazily at draw time, outside style_context(); give every
            # axes the same grid of this plot's own style (otherwise the app theme's grid shows).
            from .theme import matplotlib_rc
            rc = matplotlib_rc(self._style)
            for ax in self.fig.axes:
                ax.tick_params(which="both", grid_color=rc["grid.color"], grid_alpha=rc.get("grid.alpha", 1.0),
                               grid_linewidth=rc.get("grid.linewidth", 0.7),
                               color=rc.get("xtick.color", rc["text.color"]),
                               labelcolor=rc.get("xtick.labelcolor", rc.get("xtick.color", rc["text.color"])))
        self.canvas.draw_idle()

    def export_figure(self):
        from .figure_export.bridge import open_export
        return open_export(self)
