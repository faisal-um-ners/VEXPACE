"""Guided, optional source editors. Opening/cancelling never changes the model."""
from __future__ import annotations

import copy
import ast
import csv
import io
from pathlib import Path

import numpy as np
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
                               QHeaderView, QVBoxLayout, QWidget, QApplication)

from .. import constants as C
from ..expr import Evaluator
from ..particles.species import Species
from ..sources.distributions import (DEFAULT_PDF, component_points, read_points,
                                      validate_distribution)
from ..sources.pulses import build_pulse
from .canvas import PlotWidget

VELOCITY_LABELS = {
    "default": "Existing law (unchanged)",
    "cold": "Cold (no random spread)",
    "maxwellian": "Maxwellian / Gaussian",
    "waterbag": "Waterbag (uniform)",
    "trapezoid": "Trapezoid (tapered edges)",
    "arbitrary": "Custom points / CSV",
}
VELOCITY_HELP = {
    "default": "Keeps the current behavior. Temperature sets the random thermal spread; zero means cold.",
    "cold": "All particles have the same initial drift or beam speed. The random spread is zero.",
    "maxwellian": "Most particles are near the mean, with fewer in the tails. Each component is Gaussian; temperature controls its standard deviation.",
    "waterbag": "Every offset from minus the half-width to plus the half-width is equally likely. A zero half-width keeps that component cold.",
    "trapezoid": "Offsets in the middle are equally likely; their probability falls linearly to zero at the edges. A plateau fraction of 0 is triangular; 1 is a waterbag.",
    "arbitrary": "Enter increasing speed offsets and relative heights for each component. The line between points defines the probability density. VEXPACE normalizes its area automatically.",
}


class PointTable(QWidget):
    changed = Signal()

    def __init__(self, text, headers, ev, parent=None):
        super().__init__(parent)
        self.ev = ev
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(170)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        for label, action in (("Add point", self.add_point), ("Remove point", self.remove_point),
                              ("Import CSV…", self.import_csv)):
            b = QPushButton(label)
            b.clicked.connect(action)
            row.addWidget(b)
        layout.addLayout(row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.set_text(text)
        self.table.itemChanged.connect(lambda *_: self.changed.emit())

    def set_text(self, text):
        self.table.blockSignals(True)
        rows = list(csv.reader(io.StringIO(text)))
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j in range(2):
                self.table.setItem(i, j, QTableWidgetItem(row[j].strip() if j < len(row) else ""))
        self.table.blockSignals(False)

    def text(self):
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator="\n")
        for i in range(self.table.rowCount()):
            writer.writerow([self.table.item(i, j).text() if self.table.item(i, j) else ""
                             for j in range(2)])
        return stream.getvalue().strip()

    def add_point(self):
        i = self.table.currentRow()
        i = i + 1 if i >= 0 else self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(i)
        for j in range(2):
            self.table.setItem(i, j, QTableWidgetItem(""))
        self.table.blockSignals(False)
        self.table.setCurrentCell(i, 0)
        self.table.editItem(self.table.item(i, 0))
        self.changed.emit()

    def remove_point(self):
        rows = sorted({x.row() for x in self.table.selectedIndexes()}, reverse=True)
        self.table.blockSignals(True)
        for r in rows:
            self.table.removeRow(r)
        self.table.blockSignals(False)
        self.changed.emit()

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import two-column points", "", "Data (*.csv *.txt *.tsv);;All files (*)")
        if not path:
            return
        try:
            if Path(path).stat().st_size > 1_000_000:
                raise ValueError("Use a point table smaller than 1 MB.")
            p = read_points(Path(path).read_text(encoding="utf-8-sig"), self.ev)
            self.set_text("\n".join(f"{x:.17g}, {y:.17g}" for x, y in p))
            self.message.clear()
            self.changed.emit()
        except Exception as exc:
            self.message.setText(str(exc))


class DesignerDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(940, 680)
        outer = QVBoxLayout(self)
        self.heading = QLabel(f"<b>{title}</b>")
        outer.addWidget(self.heading)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setMinimumWidth(0)
        outer.addWidget(self.help)
        body = QHBoxLayout()
        outer.addLayout(body, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(340)
        controls = QWidget()
        self.controls = QVBoxLayout(controls)
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.form.setLabelAlignment(Qt.AlignRight)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.entry_sources = {}
        self.controls.addLayout(self.form)
        scroll.setWidget(controls)
        body.addWidget(scroll, 1)
        preview = QWidget()
        pv = QVBoxLayout(preview)
        self.plot = PlotWidget(figsize=(4, 3))
        pv.addWidget(self.plot, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pv.addWidget(self.summary)
        body.addWidget(preview, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Apply to model")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

    def entry(self, label, value):
        source = str(value)
        try:
            display = f"{self.ev.num(value):.12g}"
        except Exception:
            display = source
        w = QLineEdit(display)
        self.entry_sources[w] = (source, display)
        if source != display:
            w.setToolTip(f"Value from: {source}. Editing this number replaces that expression.")
        w.setPlaceholderText("number or parameter expression")
        self.form.addRow(label, w)
        w.textChanged.connect(self.refresh)
        return w

    def entry_text(self, widget):
        source, displayed = self.entry_sources.get(widget, (widget.text(), widget.text()))
        return source if widget.text() == displayed else widget.text()

    def visible(self, widget, state):
        self.form.setRowVisible(widget, state)

    def failed(self, exc):
        self.error.setText("Please check: " + str(exc))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.plot.axes[0].clear()
        self.plot.draw()
        self.summary.clear()

    def valid(self):
        self.error.clear()
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)

    def accept(self):
        focus = QApplication.focusWidget()
        if focus is not None and self.isAncestorOf(focus):
            focus.clearFocus()
        self.refresh()
        if self.buttons.button(QDialogButtonBox.Ok).isEnabled():
            super().accept()


class VelocityDialog(DesignerDialog):
    def __init__(self, spec, context, beam=False, parent=None):
        super().__init__("Velocity distribution", parent)
        self.spec = copy.deepcopy(spec)
        self.ev = Evaluator(context.get("parameters", {}))
        self.beam = beam
        self.geometry = context.get("geometry", "2D-ZY")
        self.components = ("Normal to emitter", "Along emitter", "Out of plane") if beam else tuple(context.get("components", ("z", "y", "x")))
        species = next((s for s in context.get("species_specs", []) if s["name"] == spec.get("species")),
                       {"name": "electrons", "preset": "electron"})
        self.mass = Species(species, self.ev).m
        self.kind = QComboBox()
        for key, label in VELOCITY_LABELS.items():
            self.kind.addItem(label, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec.get("velocity_distribution", "default"))))
        self.form.addRow("1. Choose a shape", self.kind)
        self.temperature = self.entry("Temperature kT [eV]", spec.get("temperature", "0"))
        width_names = ("Normal", "Along surface", "Out of plane") if beam else self.components
        self.widths = [self.entry(f"{c} half-width [m/s]", spec.get("velocity_width", ["1e5"]*3)[i])
                       for i, c in enumerate(width_names)]
        self.plateau = self.entry("Plateau fraction [0–1]", spec.get("velocity_plateau", ".5"))
        self.component = QComboBox()
        self.component.addItems(self.components)
        self.form.addRow("2. View component", self.component)
        self.tables = []
        for c in range(3):
            t = PointTable(spec.get(f"velocity_pdf_{c}", DEFAULT_PDF),
                           ("Offset [m/s]", "Relative height"), self.ev)
            t.changed.connect(self.refresh)
            self.controls.addWidget(t)
            self.tables.append(t)
        self.copy_points = QPushButton("Use these points for all components")
        self.copy_points.clicked.connect(self.copy_component_points)
        self.controls.addWidget(self.copy_points)
        note = QLabel("Offsets are added to the drift (Particle Loading) or beam speed from energy (Emission). "
                      "Components are sampled independently. The plot shows the spread before any motion constraint.")
        note.setWordWrap(True)
        self.controls.addWidget(note)
        details = QGroupBox("Coordinate convention")
        dv = QVBoxLayout(details)
        detail_body = QWidget()
        detail_layout = QVBoxLayout(detail_body)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        details.setCheckable(True)
        details.setChecked(False)
        detail_body.hide()
        details.toggled.connect(detail_body.setVisible)
        dv.addWidget(detail_body)
        msg = "The engine stores u = γv in m/s; at low speeds u ≈ v. These PDFs describe u offsets. "
        if beam and self.geometry == "1D-Z":
            msg += "In 1D emission the along-emitter component is set to zero by the existing emitter. "
        msg += "Custom shapes do not change the beam energy, drift, pusher, or field solver."
        label = QLabel(msg); label.setWordWrap(True); detail_layout.addWidget(label)
        self.controls.addWidget(details)
        self.controls.addStretch()
        self.kind.currentIndexChanged.connect(self.refresh)
        self.component.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def copy_component_points(self):
        text = self.tables[self.component.currentIndex()].text()
        for table in self.tables:
            table.set_text(text)
        self.refresh()

    def result_spec(self):
        d = copy.deepcopy(self.spec)
        d.update(velocity_distribution=self.kind.currentData(),
                 velocity_width=[self.entry_text(w) for w in self.widths],
                 velocity_plateau=self.entry_text(self.plateau))
        if self.kind.currentData() in ("default", "maxwellian"):
            d["temperature"] = self.entry_text(self.temperature)
        for i, t in enumerate(self.tables):
            d[f"velocity_pdf_{i}"] = t.text()
        return d

    def refresh(self, *_):
        if not hasattr(self, "tables"):
            return
        kind = self.kind.currentData()
        c = self.component.currentIndex()
        self.help.setText(VELOCITY_HELP[kind])
        self.visible(self.temperature, kind in ("default", "maxwellian"))
        for w in self.widths:
            self.visible(w, kind in ("waterbag", "trapezoid"))
        self.visible(self.plateau, kind == "trapezoid")
        for i, t in enumerate(self.tables):
            t.setVisible(kind == "arbitrary" and i == c)
        self.copy_points.setVisible(kind == "arbitrary")
        try:
            d = self.result_spec()
            validate_distribution(d, self.ev)
            ax = self.plot.axes[0]
            ax.clear()
            cold = kind == "cold"
            if kind in ("default", "maxwellian"):
                temperature = self.ev.num(self.entry_text(self.temperature))
                if not np.isfinite(temperature) or temperature < 0:
                    raise ValueError("Temperature must be finite and at least zero.")
                sigma = np.sqrt(temperature * C.e / self.mass)
                cold = sigma == 0
                if not cold:
                    x = np.linspace(-4.5*sigma, 4.5*sigma, 601)
                    y = np.exp(-.5*(x/sigma)**2) / (np.sqrt(2*np.pi)*sigma)
            elif not cold:
                p = component_points(d, self.ev, c)
                cold = p is None
                if not cold:
                    x = p[:, 0]
                    y = p[:, 1] / p[:, 1].max()
                    y /= np.sum(np.diff(x)*(y[1:]+y[:-1])/2)
            if cold:
                ax.axvline(0, color="C0", linewidth=2)
                ax.set_xlim(-1, 1)
                ax.set_yticks([])
                self.summary.setText("No random spread: all offsets are zero.")
            else:
                ax.plot(x, y, color="C0", linewidth=2)
                ax.fill_between(x, 0, y, color="C0", alpha=.16)
                if kind in ("waterbag", "trapezoid", "arbitrary"):
                    ax.vlines([x[0], x[-1]], 0, [y[0], y[-1]], color="C0")
                    ax.margins(x=.08)
                self.summary.setText("Normalized probability density · area = 1\n" +
                                     (f"Standard deviation = {sigma:.5g} m/s" if kind in ("default", "maxwellian") else
                                      f"Offset range = {x[0]:.5g} to {x[-1]:.5g} m/s"))
            ax.set_xlabel("Offset Δu [m/s]")
            ax.set_ylabel("Probability density [s/m]" if not cold else "Cold distribution")
            ax.set_title(self.components[c])
            ax.grid(alpha=.2)
            self.plot.draw()
            self.valid()
        except Exception as exc:
            self.failed(exc)


class PulseDialog(DesignerDialog):
    def __init__(self, spec, context, parent=None):
        super().__init__("Current pulse", parent)
        self.spec = copy.deepcopy(spec)
        self.context = context
        self.ev = Evaluator(context.get("parameters", {}))
        p = copy.deepcopy(spec.get("pulse_builder", {}))
        # An edited raw expression is authoritative; do not silently regenerate it.
        if p.get("generated_expression") != str(spec.get("current_density", "0")):
            p["shape"] = "existing"
        self.kind = QComboBox()
        for value, label in (("existing", "Keep current expression"), ("square", "Square — constant while on"),
                             ("trapezoid", "Trapezoid — rise, hold, fall"),
                             ("gaussian", "Gaussian — smooth bell pulse"),
                             ("arbitrary", "Custom — draw with points / import CSV")):
            self.kind.addItem(label, value)
        self.kind.setCurrentIndex(max(0, self.kind.findData(p.get("shape", "existing"))))
        self.form.addRow("1. Choose a shape", self.kind)
        # Recover useful scales from existing short-pulse examples without altering them.
        params = self.ev.params
        default_duration = repr(float(params.get("support", 1e-9)))
        default_amount = "Jamp" if "Jamp" in params else "1e4"
        self.time_scale = 1e-9
        self.time_unit = QComboBox()
        for label, scale in (("ps", 1e-12), ("ns", 1e-9), ("µs", 1e-6), ("s", 1.0)):
            self.time_unit.addItem(label, scale)
        self.time_unit.setCurrentIndex(1)
        self.form.addRow("Time unit", self.time_unit)
        self.time_sources = {}
        self.start = self.time_entry("Start time [ns]", p.get("start", "0"))
        self.duration = self.time_entry("Full duration [ns]", p.get("duration", default_duration))
        self.normalization = QComboBox()
        self.normalization.addItem("Set the peak current density", "peak")
        self.normalization.addItem("Set total charge per area", "charge")
        self.normalization.setCurrentIndex(max(0, self.normalization.findData(p.get("normalization", "peak"))))
        self.form.addRow("2. Set strength using", self.normalization)
        self.amount = self.entry("Peak J [A/m²]", p.get("amount", default_amount))
        default_rise = repr(float(default_duration) * .15)
        self.rise = self.time_entry("Each rise / fall time [ns]", p.get("rise", default_rise))
        self.cutoff = self.entry("Gaussian cutoff [σ]", p.get("cutoff", "3"))
        self.table = PointTable(p.get("points", "0,0\n0.3,1\n0.7,0.5\n1,0"),
                                ("Position [0–1]", "Relative height"), self.ev)
        self.table.changed.connect(self.refresh)
        self.controls.addWidget(self.table)
        self.advanced = QGroupBox("Advanced: evaluation and expression")
        av = QVBoxLayout(self.advanced)
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        advanced_body = QWidget()
        advanced_layout = QVBoxLayout(advanced_body)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_body.hide()
        self.advanced.toggled.connect(advanced_body.setVisible)
        av.addWidget(advanced_body)
        sub = QFormLayout()
        self.shift = QLineEdit(p.get("sample_shift", "sample_dt/2" if "sample_dt/2" in str(spec.get("current_density", "")) else "0"))
        self.shift.textChanged.connect(self.refresh)
        sub.addRow("Evaluate at t + offset [s]", self.shift)
        advanced_layout.addLayout(sub)
        self.expression = QPlainTextEdit()
        self.expression.setReadOnly(True)
        self.expression.setMaximumHeight(110)
        advanced_layout.addWidget(self.expression)
        self.controls.addWidget(self.advanced)
        self.controls.addStretch()
        self.kind.currentIndexChanged.connect(self.refresh)
        self.normalization.currentIndexChanged.connect(self.strength_changed)
        self.time_unit.currentIndexChanged.connect(self.unit_changed)
        self.refresh()

    def canonical_seconds(self, source):
        source = str(source).strip()
        # Fold numeric unit conversions from older files, but retain references
        # to global parameters so a later parameter edit still updates J(t).
        try:
            names = {n.id for n in ast.walk(ast.parse(source, mode="eval")) if isinstance(n, ast.Name)}
            if not names.intersection(self.ev.params):
                value = self.ev.num(source)
                if np.isfinite(value):
                    return repr(value)
        except Exception:
            pass
        return source

    def time_entry(self, label, seconds):
        source = self.canonical_seconds(seconds)
        try:
            display = f"{self.ev.num(source) / self.time_scale:.12g}"
        except Exception:
            display = f"({source})/({self.time_scale!r})"
        widget = self.entry(label, display)
        self.time_sources[widget] = (source, widget.text())
        widget.setToolTip(f"Stored value in seconds: {source}. Enter a value in the selected time unit.")
        return widget

    def seconds_text(self, edit):
        source, displayed = self.time_sources[edit]
        if edit.text() == displayed:
            return source
        return self.canonical_seconds(f"({edit.text()})*({self.time_scale!r})")

    def unit_changed(self, *_):
        values = [self.seconds_text(w) for w in (self.start, self.duration, self.rise)]
        self.time_scale = self.time_unit.currentData()
        for w, source, label in zip((self.start, self.duration, self.rise), values,
                                   ("Start time", "Full duration", "Each rise / fall time")):
            try:
                value = f"{self.ev.num(source) / self.time_scale:.12g}"
            except Exception:
                value = f"({source})/({self.time_scale!r})"
            self.time_sources[w] = (source, value)
            self.entry_sources[w] = (value, value)
            w.blockSignals(True)
            w.setText(value)
            w.blockSignals(False)
            self.form.labelForField(w).setText(f"{label} [{self.time_unit.currentText()}]")
        self.refresh()

    def strength_changed(self, *_):
        # Keep the same pulse when switching between peak and total-charge entry.
        if hasattr(self, "compiled") and self.compiled:
            value = self.compiled["peak"] if self.normalization.currentData() == "peak" else self.compiled["charge"]
            self.amount.setText(repr(value))
        self.refresh()

    def settings(self):
        return dict(shape=self.kind.currentData(), start=self.seconds_text(self.start), duration=self.seconds_text(self.duration),
                    normalization=self.normalization.currentData(), amount=self.entry_text(self.amount),
                    rise=self.seconds_text(self.rise), cutoff=self.entry_text(self.cutoff), points=self.table.text(),
                    sample_shift=self.shift.text())

    def result_spec(self):
        d = copy.deepcopy(self.spec)
        if self.kind.currentData() != "existing":
            p = build_pulse(self.settings(), self.ev)
            d.update(current_density=p["expression"], t_start=p["t_start"], t_stop=p["t_stop"])
            d["pulse_builder"] = dict(self.settings(), generated_expression=p["expression"])
        return d

    def refresh(self, *_):
        if not hasattr(self, "table"):
            return
        kind = self.kind.currentData()
        existing = kind == "existing"
        self.visible(self.normalization, not existing)
        self.visible(self.amount, not existing)
        self.visible(self.rise, kind == "trapezoid")
        self.visible(self.cutoff, kind == "gaussian")
        self.table.setVisible(kind == "arbitrary")
        self.shift.setEnabled(not existing)
        label = "Peak J [A/m²]" if self.normalization.currentData() == "peak" else "Charge / area [C/m²]"
        self.form.labelForField(self.amount).setText(label)
        hints = {
            "existing": "This is the current J(t). Set the preview time window below, or choose a preset to create a new pulse. Applying keeps the current expression unchanged.",
            "square": "The current turns on, stays constant, then turns off. Start time and full duration define its time window.",
            "trapezoid": "The current rises linearly, stays at its peak, then falls linearly. Rise and fall times are equal.",
            "gaussian": "A bell-shaped pulse cut off at its edges. Full duration is the entire on-window; its width at half-height is shown below the plot.",
            "arbitrary": "Add points from position 0 (start) to 1 (end). Heights are joined by straight lines and scaled so the highest point matches your chosen peak.",
        }
        self.help.setText(hints[kind])
        self.compiled = None
        try:
            ax = self.plot.axes[0]
            ax.clear()
            if existing:
                start = self.ev.num(self.seconds_text(self.start))
                duration = self.ev.num(self.seconds_text(self.duration))
                if not np.isfinite(start) or not np.isfinite(duration) or duration <= 0:
                    raise ValueError("Preview start must be finite and duration must be positive.")
                times = np.linspace(start, start+duration, 1001)
                fun = self.ev.func_t(self.spec.get("current_density", "0"))
                j = np.array([fun(t) if self.ev.num(self.spec.get("t_start", 0)) <= t <= self.ev.num(self.spec.get("t_stop", 1e9)) else 0 for t in times])
                if not np.isfinite(j).all():
                    raise ValueError("The current expression produced non-finite values.")
                self.expression.setPlainText(str(self.spec.get("current_density", "0")))
                self.summary.setText(f"Current expression · peak in preview {j.max():.5g} A/m²\nPreview window: {start:.5g} to {start+duration:.5g} s")
            else:
                p = self.compiled = build_pulse(self.settings(), self.ev)
                x = np.unique(np.r_[np.linspace(-.06, 1.06, 1001), 0, 1,
                                        p["points"][:,0] if p["points"] is not None else []])
                j = p["peak"] * np.where((x >= 0)&(x <= 1), p["fraction"](x), 0)
                times = p["start"] + x * p["duration"]
                self.expression.setPlainText(p["expression"])
                text = f"Peak J = {p['peak']:.5g} A/m²\nCharge / area = {p['charge']:.5g} C/m²\nFull duration = {p['duration']:.5g} s"
                if kind == "gaussian":
                    fwhm = p["duration"] * np.sqrt(2*np.log(2)) / self.ev.num(self.entry_text(self.cutoff))
                    text += f" · FWHM = {fwhm:.5g} s"
                if p["sample_shift"]:
                    text += f"\nSampling offset = {p['sample_shift']:.5g} s; plot shows requested physical pulse."
                try:
                    dt = self.ev.num(self.context.get("simulation_dt", ""))
                    if dt > 0:
                        n = p["duration"] / dt
                        text += f"\nPulse spans {n:.3g} timesteps."
                        if n < 20:
                            text += " Choose a smaller timestep to resolve its shape."
                except Exception:
                    pass
                try:
                    end = self.ev.num(self.context.get("simulation_end", ""))
                    if end < p["start"] + p["duration"]:
                        text += "\nThe pulse ends after the current simulation end time."
                except Exception:
                    pass
                self.summary.setText(text + "\nCharge shown for spatial profile = 1; the simulation timestep is unchanged.")
            ax.plot(times / self.time_scale, j, color="C0", linewidth=2)
            ax.fill_between(times / self.time_scale, 0, j, color="C0", alpha=.16)
            ax.set_xlabel(f"Time [{self.time_unit.currentText()}]")
            ax.set_ylabel("Current density J [A/m²]")
            ax.set_title("Current pulse")
            ax.grid(alpha=.2)
            self.plot.draw()
            self.valid()
        except Exception as exc:
            self.failed(exc)
