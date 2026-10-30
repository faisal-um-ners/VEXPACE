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
from ..expr import energy_eV
from ..sources import distributions as D
from ..sources.distributions import (DEFAULT_PDF, component_points, point_rows, read_points,
                                      validate_distribution)
from ..sources.pulses import DEFAULT_TABLE, build_pulse, normalized_settings
from .canvas import PlotWidget

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


LOADER_LABELS = {
    "default": "Existing law (temperature, drift)",
    "cold": "Cold (no random spread)",
    "maxwellian": "Maxwellian (Gaussian in each component)",
    "waterbag": "Waterbag (uniform offsets)",
    "trapezoid": "Trapezoid (tapered edges)",
    "arbitrary": "Custom points / CSV",
}
EMISSION_LABELS = {
    "default": "Existing law (beam energy + thermal spread)",
    "cold": "Cold beam (single speed)",
    "maxwellian": "Maxwellian - thermal current flux",
    "gaussian": "Gaussian - truncated at v = 0",
    "waterbag": "Waterbag - uniform current flux",
    "waterbag_phase": "Waterbag - uniform phase density",
    "trapezoid": "Trapezoid - plateau with linear edges",
    "arbitrary": "Custom speed table / CSV",
}
# Kept for older imports: labels shown in the form summary
VELOCITY_LABELS = {**LOADER_LABELS, **EMISSION_LABELS}
TRANSVERSE_LABELS = {
    "thermal": "Thermal - Gaussian, σ = √(kT/m)",
    "cold": "Cold - no transverse velocity",
    "gaussian": "Gaussian - your σ",
    "waterbag": "Waterbag - uniform in ±w",
    "trapezoid": "Trapezoid - plateau in ±w",
    "arbitrary": "Custom offset tables",
}
EMISSION_HELP = {
    "default": "Older models: every particle starts with the speed of the beam energy plus an isotropic "
               "Gaussian of σ = √(kT/m) in each component.  A large temperature can launch part of the beam "
               "back into the surface - prefer one of the current-flux laws below.",
    "cold": "P(vₙ) = δ(vₙ − v_b), v_b = speed of the beam energy E (relativistic: v_b = c√(1 − 1/γ²), "
            "γ = 1 + eE/mc²).",
    "maxwellian": "Thermal emission from a surface at kT:  P(vₙ) = (m/kT) vₙ exp(−m vₙ²/2kT),  vₙ ≥ 0  "
                  "(the flux-weighted half-Maxwellian).  Mean vₙ = √(πkT/2m).  A beam energy E adds eE to the "
                  "normal energy (acceleration): vₙ → √(vₙ² + 2eE/m).  Transmission over a barrier of depth bV: "
                  "T = exp(−ebV/kT).",
    "gaussian": "P(vₙ) = exp(−(vₙ − μ)²/2σ²) / [√(2π) σ Φ(μ/σ)],  vₙ ≥ 0  (truncated Gaussian of the current "
                "flux; Φ = standard normal CDF).  μ blank = speed of the beam energy.  "
                "T = [1 − Φ((v_c − μ)/σ)] / Φ(μ/σ),  v_c = √(2ebV/m).",
    "waterbag": "Uniform current flux:  P(vₙ) = 1/(v₊ − v₋)  for v₋ ≤ vₙ ≤ v₊.  "
                "T = clip((v₊ − v_c)/(v₊ − v₋), 0, 1).",
    "waterbag_phase": "Uniform phase-space density (constant Vlasov waterbag, e.g. Ignatov 2025):  "
                      "f = const, so P(vₙ) = 2vₙ/(v₊² − v₋²)  for v₋ ≤ vₙ ≤ v₊.",
    "trapezoid": "P(vₙ) rises linearly from 0 at v₋ to a flat plateau and falls linearly to 0 at v₊; the "
                 "plateau is the central fraction p of [v₋, v₊] (p = 0 triangle, p = 1 uniform waterbag).",
    "arbitrary": "Enter increasing speeds vₙ ≥ 0 [m/s] and weights.  Straight lines join the points; VEXPACE "
                 "normalises the area.  The weight is either the current flux P(vₙ) or the phase density "
                 "f(vₙ) (then P = vₙ f).  Expressions such as speed_eV(10, me) are allowed.",
}
LOADER_HELP = {
    "default": "Keeps the loader's law: Gaussian of σ = √(kT/m) in each component about the drift; zero means cold.",
    "cold": "All particles have the drift velocity.",
    "maxwellian": "f(v) ∝ exp(−m(v − v_d)²/2kT): a Gaussian of σ = √(kT/m) in each component about the drift.",
    "waterbag": "Offsets from −w to +w are equally likely in each component (f uniform).  w = 0 keeps that component cold.",
    "trapezoid": "Offsets on the central plateau are equally likely; the density falls linearly to zero at ±w.  "
                 "Plateau 0 is a triangle, 1 a waterbag.",
    "arbitrary": "Enter increasing offsets [m/s] and relative heights for each component; VEXPACE normalises the area.",
}


def _speed_label(v):
    return f"{v / 1e3:.4g} km/s"


class VelocityDialog(DesignerDialog):
    """Particle Loading: drift + offsets of f(v).  Beam emission: current-flux distribution P(v_n)
    of the normal speed (v_n >= 0) and independent transverse spreads, all in SI units."""

    def __init__(self, spec, context, beam=False, parent=None):
        super().__init__("Velocity distribution", parent)
        self.spec = copy.deepcopy(spec)
        self.ev = Evaluator(context.get("parameters", {}))
        self.beam = beam
        self.geometry = context.get("geometry", "2D-ZY")
        species = next((s for s in context.get("species_specs", []) if s["name"] == spec.get("species")),
                       {"name": "electrons", "preset": "electron"})
        self.mass = Species(species, self.ev).m
        self.kind = QComboBox()
        labels = EMISSION_LABELS if beam else LOADER_LABELS
        for key, label in labels.items():
            self.kind.addItem(label, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec.get("velocity_distribution", "default"))))
        if beam:
            self._build_emission(spec)
        else:
            self._build_loader(spec, context)
        self.controls.addStretch()
        self.kind.currentIndexChanged.connect(self.refresh)
        self.view.currentIndexChanged.connect(self.refresh)
        self.refresh()

    # -- emission -----------------------------------------------------------------------------
    def _build_emission(self, spec):
        self.form.addRow("<b>Normal velocity</b> (leaves the surface, vₙ ≥ 0)", QLabel(""))
        self.form.addRow("Current-flux law P(vₙ)", self.kind)
        self.energy = self.entry("Beam energy E [eV]", spec.get("energy", "0"))
        self.temperature = self.entry("Temperature kT [eV]", spec.get("temperature", "0"))
        self.mean = self.entry("Mean speed μ [m/s] (blank: beam speed)", spec.get("velocity_mean", ""))
        self.spread = self.entry("Speed spread σ [m/s]", spec.get("velocity_spread", "1e5"))
        self.vmin = self.entry("Lowest speed v₋ [m/s]", spec.get("velocity_min", "0"))
        self.vmax = self.entry("Highest speed v₊ [m/s]", spec.get("velocity_max", "2e5"))
        self.plateau = self.entry("Plateau fraction p [0–1]", spec.get("velocity_plateau", "0.5"))
        self.table_kind = QComboBox()
        self.table_kind.addItem("Weight is the current flux P(vₙ)", "flux")
        self.table_kind.addItem("Weight is the phase density f(vₙ)", "phase_density")
        self.table_kind.setCurrentIndex(max(0, self.table_kind.findData(spec.get("velocity_table_kind", "flux"))))
        self.form.addRow("Table meaning", self.table_kind)
        self.table_kind.currentIndexChanged.connect(self.refresh)
        self.form.addRow("<b>Transverse velocity</b> (along the surface, out of plane)", QLabel(""))
        self.transverse = QComboBox()
        for key, label in TRANSVERSE_LABELS.items():
            self.transverse.addItem(label, key)
        self.transverse.setCurrentIndex(max(0, self.transverse.findData(spec.get("transverse_distribution", "thermal"))))
        self.form.addRow("Transverse law", self.transverse)
        self.transverse.currentIndexChanged.connect(self.refresh)
        tw = list(spec.get("transverse_width", ["0", "0"])) + ["0", "0"]
        self.tw = [self.entry("Along-surface σ or w [m/s]", tw[0]), self.entry("Out-of-plane σ or w [m/s]", tw[1])]
        self.barrier = self.entry("Show transmission over a potential dip of depth [V]", "0")
        self.view = QComboBox()
        self.view.addItems(("Normal speed vₙ", "Along surface", "Out of plane"))
        self.form.addRow("Plot", self.view)
        self.tables = []
        headers = [("Speed vₙ [m/s]", "Weight"), ("Offset [m/s]", "Relative height"), ("Offset [m/s]", "Relative height")]
        defaults = [D.DEFAULT_SPEED_PDF, DEFAULT_PDF, DEFAULT_PDF]
        for c in range(3):
            t = PointTable(spec.get(f"velocity_pdf_{c}", defaults[c]), headers[c], self.ev)
            t.changed.connect(self.refresh)
            self.controls.addWidget(t)
            self.tables.append(t)
        self.copy_points = QPushButton("Use the along-surface table for out of plane too")
        self.copy_points.clicked.connect(lambda: (self.tables[2].set_text(self.tables[1].text()), self.refresh()))
        self.controls.addWidget(self.copy_points)
        msg = ("All speeds are real velocities v in m/s (SI); VEXPACE converts the sampled velocity to "
               "u = γv.  P(vₙ) is the distribution of the particles crossing the surface per unit time "
               "(the injected current), as needed for Poisson/Child-Langmuir theory: J_tr = J T(b).")
        if self.geometry == "1D-Z":
            msg += "  In 1D the along-surface component is not used."
        note = QLabel(msg)
        note.setWordWrap(True)
        self.controls.addWidget(note)

    # -- loading ------------------------------------------------------------------------------
    def _build_loader(self, spec, context):
        self.components = tuple(context.get("components", ("z", "y", "x")))
        self.form.addRow("1. Choose a shape", self.kind)
        self.temperature = self.entry("Temperature kT [eV]", spec.get("temperature", "0"))
        self.widths = [self.entry(f"{c} half-width w [m/s]", spec.get("velocity_width", ["1e5"] * 3)[i])
                       for i, c in enumerate(self.components)]
        self.plateau = self.entry("Plateau fraction [0–1]", spec.get("velocity_plateau", ".5"))
        self.view = QComboBox()
        self.view.addItems(self.components)
        self.form.addRow("2. View component", self.view)
        self.tables = []
        for c in range(3):
            t = PointTable(spec.get(f"velocity_pdf_{c}", DEFAULT_PDF), ("Offset [m/s]", "Relative height"), self.ev)
            t.changed.connect(self.refresh)
            self.controls.addWidget(t)
            self.tables.append(t)
        self.copy_points = QPushButton("Use these points for all components")
        self.copy_points.clicked.connect(self.copy_component_points)
        self.controls.addWidget(self.copy_points)
        note = QLabel("Offsets are added to the drift of the loaded particles (u = γv, like the drift). "
                      "Components are sampled independently.")
        note.setWordWrap(True)
        self.controls.addWidget(note)

    def copy_component_points(self):
        text = self.tables[self.view.currentIndex()].text()
        for table in self.tables:
            table.set_text(text)
        self.refresh()

    # -- model values -------------------------------------------------------------------------
    def result_spec(self):
        d = copy.deepcopy(self.spec)
        d["velocity_distribution"] = self.kind.currentData()
        d["velocity_plateau"] = self.entry_text(self.plateau)
        d["temperature"] = self.entry_text(self.temperature)
        for i, t in enumerate(self.tables):
            d[f"velocity_pdf_{i}"] = t.text()
        if self.beam:
            d.update(energy=self.entry_text(self.energy).strip() or "0", velocity_mean=self.entry_text(self.mean).strip(),
                     velocity_spread=self.entry_text(self.spread), velocity_min=self.entry_text(self.vmin),
                     velocity_max=self.entry_text(self.vmax), velocity_table_kind=self.table_kind.currentData(),
                     transverse_distribution=self.transverse.currentData(),
                     transverse_width=[self.entry_text(w) for w in self.tw], velocity_version="2")
        else:
            d["velocity_width"] = [self.entry_text(w) for w in self.widths]
        return d

    def refresh(self, *_):
        if not hasattr(self, "tables") or not hasattr(self, "view"):
            return
        if self.beam:
            self._refresh_emission()
        else:
            self._refresh_loader()

    def _refresh_emission(self):
        kind = self.kind.currentData()
        tkind = self.transverse.currentData()
        view = self.view.currentIndex()
        self.help.setText(EMISSION_HELP[kind])
        flux = kind != "default"
        self.visible(self.energy, kind in ("default", "cold", "maxwellian", "gaussian"))
        self.visible(self.temperature, kind in ("default", "maxwellian") or (flux and tkind == "thermal"))
        self.visible(self.mean, kind == "gaussian")
        self.visible(self.spread, kind == "gaussian")
        for w in (self.vmin, self.vmax):
            self.visible(w, kind in ("waterbag", "waterbag_phase", "trapezoid"))
        self.visible(self.plateau, kind == "trapezoid" or (flux and tkind == "trapezoid"))
        self.visible(self.table_kind, kind == "arbitrary")
        self.visible(self.transverse, flux)
        for w in self.tw:
            self.visible(w, flux and tkind in ("gaussian", "waterbag", "trapezoid"))
        self.visible(self.barrier, flux)
        self.tables[0].setVisible(kind == "arbitrary" and view == 0)
        for c in (1, 2):
            self.tables[c].setVisible(flux and tkind == "arbitrary" and view == c)
        self.copy_points.setVisible(flux and tkind == "arbitrary")
        try:
            d = self.result_spec()
            D.validate_distribution(d, self.ev, emitter=True)
            ax = self.plot.axes[0]
            ax.clear()
            m = self.mass
            lines = []
            if view == 0:
                if kind == "default":
                    vb = D.beam_speed(d, self.ev, m)
                    T = self.ev.num(d.get("temperature", 0))
                    sig = np.sqrt(max(T, 0) * C.e / m)
                    if sig > 0:
                        v = np.linspace(vb - 4.5 * sig, vb + 4.5 * sig, 601)
                        p = np.exp(-0.5 * ((v - vb) / sig) ** 2) / (np.sqrt(2 * np.pi) * sig)
                    else:
                        v, p = np.array([vb]), None
                    if sig > 0 and vb - 3 * sig < 0:
                        lines.append("Part of this beam starts with vₙ < 0 (back into the surface).")
                else:
                    v, p = D.normal_pdf_curve(d, self.ev, m)
                if p is None:
                    ax.axvline(v[0] / 1e3, color="C0", linewidth=2)
                    ax.set_yticks([])
                    lines.append(f"Single speed vₙ = {_speed_label(v[0])} ({energy_eV(v[0], m):.4g} eV)")
                else:
                    ax.plot(v / 1e3, p * 1e3, color="C0", linewidth=2)
                    ax.fill_between(v / 1e3, 0, p * 1e3, color="C0", alpha=.16)
                    mean = np.trapezoid(v * p, v) / np.trapezoid(p, v)
                    lines.append(f"Mean vₙ = {_speed_label(mean)}; range {_speed_label(v[0])} – {_speed_label(v[-1])}")
                    lines.append(f"Normal energy range {energy_eV(max(v[0], 0), m):.4g} – {energy_eV(v[-1], m):.4g} eV")
                    ax.set_ylabel("P(vₙ) [1/(km/s)]")
                if flux:
                    b = self.ev.num(self.entry_text(self.barrier) or "0")
                    if b > 0:
                        lines.append(f"Transmission over a {b:.4g} V dip: T = {D.transmission(d, self.ev, m, b):.4g}")
                ax.set_xlabel("Normal speed vₙ [km/s]")
                ax.set_title("Injected current-flux distribution")
            else:
                c = view
                if not flux:
                    T = self.ev.num(d.get("temperature", 0))
                    s = np.sqrt(max(T, 0) * C.e / m)
                    pts, gauss = None, s
                else:
                    pts = D.transverse_points(d, self.ev, c)
                    gauss = None
                    if tkind == "thermal":
                        gauss = np.sqrt(max(self.ev.num(d.get("temperature", 0)), 0) * C.e / m)
                    elif tkind == "gaussian":
                        gauss = self.ev.num(d["transverse_width"][c - 1])
                if pts is not None:
                    x, y = pts.T
                    y = y / np.trapezoid(y, x)
                    ax.plot(x / 1e3, y * 1e3, color="C1", linewidth=2)
                    ax.fill_between(x / 1e3, 0, y * 1e3, color="C1", alpha=.16)
                    lines.append(f"Offsets {_speed_label(x[0])} – {_speed_label(x[-1])}")
                elif gauss:
                    x = np.linspace(-4.5 * gauss, 4.5 * gauss, 601)
                    y = np.exp(-0.5 * (x / gauss) ** 2) / (np.sqrt(2 * np.pi) * gauss)
                    ax.plot(x / 1e3, y * 1e3, color="C1", linewidth=2)
                    ax.fill_between(x / 1e3, 0, y * 1e3, color="C1", alpha=.16)
                    lines.append(f"Gaussian σ = {_speed_label(gauss)}")
                else:
                    ax.axvline(0, color="C1", linewidth=2)
                    ax.set_yticks([])
                    lines.append("Cold: no velocity in this direction.")
                ax.set_xlabel(("Along-surface" if c == 1 else "Out-of-plane") + " velocity [km/s]")
                ax.set_ylabel("probability density [1/(km/s)]")
                ax.set_title("Transverse velocity")
                if c == 1 and self.geometry == "1D-Z":
                    lines.append("Not used in 1D.")
            ax.grid(alpha=.2)
            self.plot.draw()
            self.summary.setText("\n".join(lines))
            self.valid()
        except Exception as exc:
            self.failed(exc)

    def _refresh_loader(self):
        kind = self.kind.currentData()
        c = self.view.currentIndex()
        self.help.setText(LOADER_HELP[kind])
        self.visible(self.temperature, kind in ("default", "maxwellian"))
        for w in self.widths:
            self.visible(w, kind in ("waterbag", "trapezoid"))
        self.visible(self.plateau, kind == "trapezoid")
        for i, t in enumerate(self.tables):
            t.setVisible(kind == "arbitrary" and i == c)
        self.copy_points.setVisible(kind == "arbitrary")
        try:
            d = self.result_spec()
            D.validate_distribution(d, self.ev)
            ax = self.plot.axes[0]
            ax.clear()
            cold = kind == "cold"
            sigma = 0
            if kind in ("default", "maxwellian"):
                temperature = self.ev.num(self.entry_text(self.temperature))
                if not np.isfinite(temperature) or temperature < 0:
                    raise ValueError("Temperature must be finite and at least zero.")
                sigma = np.sqrt(temperature * C.e / self.mass)
                cold = sigma == 0
                if not cold:
                    x = np.linspace(-4.5 * sigma, 4.5 * sigma, 601)
                    y = np.exp(-.5 * (x / sigma) ** 2) / (np.sqrt(2 * np.pi) * sigma)
            elif not cold:
                p = component_points(d, self.ev, c)
                cold = p is None
                if not cold:
                    x = p[:, 0]
                    y = p[:, 1] / p[:, 1].max()
                    y /= np.sum(np.diff(x) * (y[1:] + y[:-1]) / 2)
            if cold:
                ax.axvline(0, color="C0", linewidth=2)
                ax.set_xlim(-1, 1)
                ax.set_yticks([])
                self.summary.setText("No random spread: every particle has the drift velocity.")
            else:
                ax.plot(x / 1e3, y * 1e3, color="C0", linewidth=2)
                ax.fill_between(x / 1e3, 0, y * 1e3, color="C0", alpha=.16)
                self.summary.setText("Probability density of the offset · area = 1\n" +
                                     (f"σ = {_speed_label(sigma)}" if kind in ("default", "maxwellian") else
                                      f"Offsets {_speed_label(x[0])} to {_speed_label(x[-1])}"))
            ax.set_xlabel("Offset about the drift [km/s]")
            ax.set_ylabel("probability density [1/(km/s)]" if not cold else "cold")
            ax.set_title(self.components[c])
            ax.grid(alpha=.2)
            self.plot.draw()
            self.valid()
        except Exception as exc:
            self.failed(exc)


PULSE_LABELS = {
    "existing": "Keep current expression",
    "square": "Square - constant while on",
    "trapezoid": "Trapezoid - rise, flat top, fall",
    "gaussian": "Gaussian - FWHM, truncated",
    "sin2": "sin² - smooth, compact",
    "arbitrary": "Custom table (time, height) / CSV",
}
PULSE_HELP = {
    "existing": "This is the current J(t).  Choose a preview window, or pick a shape to create a new pulse.  "
                "Applying keeps the expression unchanged.",
    "square": "J = Jₚ for start ≤ t < start + T.",
    "trapezoid": "J rises linearly in t_r, stays at Jₚ for t_h, falls linearly in t_f;  T = t_r + t_h + t_f.  "
                 "Charge per area Q₁ = Jₚ (t_r/2 + t_h + t_f/2).",
    "gaussian": "J = Jₚ exp(−(t − t_c)²/2σ²),  σ = FWHM/(2√(2 ln 2)) = FWHM/2.3548,  truncated at ±nσ:  "
                "window T = 2nσ,  t_c = start + nσ.  Q₁ = Jₚ σ √(2π) erf(n/√2).",
    "sin2": "J = Jₚ sin²(π(t − start)/T) for 0 ≤ t − start < T:  smooth start and end, FWHM = T/2, Q₁ = Jₚ T/2.",
    "arbitrary": "Times after the pulse start (first row 0) and relative heights; straight lines join the points.  "
                 "The highest point becomes Jₚ (or the area gives the charge you set).",
}
TIME_UNITS = (("ps", 1e-12), ("ns", 1e-9), ("µs", 1e-6), ("s", 1.0))


class PulseDialog(DesignerDialog):
    """Current pulse J(t) in physical units; sampled by the emitter at the middle of each step."""

    def __init__(self, spec, context, parent=None):
        super().__init__("Current pulse", parent)
        self.spec = copy.deepcopy(spec)
        self.context = context
        self.ev = Evaluator(context.get("parameters", {}))
        p = copy.deepcopy(spec.get("pulse_builder", {}))
        # An edited raw expression is authoritative; do not silently regenerate it.
        if p.get("generated_expression") != str(spec.get("current_density", "0")):
            p = {"shape": "existing"}
        else:
            p = normalized_settings(p)
        self.kind = QComboBox()
        for value, label in PULSE_LABELS.items():
            self.kind.addItem(label, value)
        self.kind.setCurrentIndex(max(0, self.kind.findData(p.get("shape", "existing"))))
        self.form.addRow("1. Choose a shape", self.kind)
        params = self.ev.params
        default_duration = repr(float(params.get("support", 1e-9)))
        default_amount = "Jamp" if "Jamp" in params else "1e4"
        self.time_scale = 1e-9
        self.time_unit = QComboBox()
        for label, scale in TIME_UNITS:
            self.time_unit.addItem(label, scale)
        self.time_unit.setCurrentIndex(1)
        self.form.addRow("Time unit", self.time_unit)
        self.time_sources = {}
        self.time_labels = {}
        self.start = self.time_entry("Start time", p.get("start", "0"))
        self.duration = self.time_entry("Duration T", p.get("duration", default_duration))
        d0 = self.ev.num(default_duration)
        self.rise = self.time_entry("Rise time t_r", p.get("rise", repr(0.15 * d0)))
        self.hold = self.time_entry("Flat-top time t_h", p.get("hold", repr(0.7 * d0)))
        self.fall = self.time_entry("Fall time t_f", p.get("fall", p.get("rise", repr(0.15 * d0))))
        self.fwhm = self.time_entry("FWHM", p.get("fwhm", repr(0.4 * d0)))
        self.cutoff = self.entry("Gaussian cutoff n [σ each side]", p.get("cutoff", "3"))
        self.table = PointTable(self._table_to_unit(p.get("points", DEFAULT_TABLE)),
                                ("Time after start [ns]", "Relative height"), self.ev)
        self.table.changed.connect(self.refresh)
        self.controls.addWidget(self.table)
        self.normalization = QComboBox()
        self.normalization.addItem("Peak current density Jₚ [A/m²]", "peak")
        self.normalization.addItem("Charge per area of one pulse [C/m²]", "charge")
        self.normalization.setCurrentIndex(max(0, self.normalization.findData(p.get("normalization", "peak"))))
        self.form.addRow("2. Set strength using", self.normalization)
        self.amount = self.entry("Peak J [A/m²]", p.get("amount", default_amount))
        self.repeat = self.entry("3. Number of pulses N", p.get("repeat", "1") or "1")
        self.period = self.time_entry("Repetition period P", p.get("period", "") or repr(2 * d0))
        self.advanced = QGroupBox("Generated J(t) expression")
        av = QVBoxLayout(self.advanced)
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        body.hide()
        self.advanced.toggled.connect(body.setVisible)
        av.addWidget(body)
        self.expression = QPlainTextEdit()
        self.expression.setReadOnly(True)
        self.expression.setMaximumHeight(110)
        bl.addWidget(self.expression)
        note = QLabel("The emitter evaluates J at the middle of every time step, Q = J(t + dt/2)·A·dt, "
                      "with the time step of Study / Solver; no time-step parameter is needed here.")
        note.setWordWrap(True)
        self.controls.addWidget(note)
        self.controls.addWidget(self.advanced)
        self.controls.addStretch()
        self.kind.currentIndexChanged.connect(self.refresh)
        self.normalization.currentIndexChanged.connect(self.strength_changed)
        self.time_unit.currentIndexChanged.connect(self.unit_changed)
        self.refresh()

    # -- times in the chosen unit ---------------------------------------------------------------
    def canonical_seconds(self, source):
        source = str(source).strip()
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
        widget = self.entry(f"{label} [ns]", display)
        self.time_sources[widget] = (source, widget.text())
        self.time_labels[widget] = label
        widget.setToolTip(f"Stored value in seconds: {source}.  Enter a value in the selected time unit.")
        return widget

    def seconds_text(self, edit):
        source, displayed = self.time_sources[edit]
        if edit.text() == displayed:
            return source
        return self.canonical_seconds(f"({edit.text()})*({self.time_scale!r})")

    def _table_to_unit(self, text, scale=None):
        scale = scale or self.time_scale
        out = []
        for x, y in point_rows(text):
            try:
                out.append(f"{float(self.ev.num(x)) / scale:.12g}, {y.strip()}")
            except Exception:
                out.append(f"({x.strip()})/({scale!r}), {y.strip()}")
        return "\n".join(out)

    def _table_seconds(self):
        out = []
        for x, y in point_rows(self.table.text()):
            out.append(f"{self.canonical_seconds(f'({x.strip()})*({self.time_scale!r})')}, {y.strip()}")
        return "\n".join(out)

    def unit_changed(self, *_):
        widgets = list(self.time_sources)
        values = [self.seconds_text(w) for w in widgets]
        table = self._table_seconds()
        self.time_scale = self.time_unit.currentData()
        unit = self.time_unit.currentText()
        for w, source in zip(widgets, values):
            try:
                value = f"{self.ev.num(source) / self.time_scale:.12g}"
            except Exception:
                value = f"({source})/({self.time_scale!r})"
            self.time_sources[w] = (source, value)
            self.entry_sources[w] = (value, value)
            w.blockSignals(True)
            w.setText(value)
            w.blockSignals(False)
            self.form.labelForField(w).setText(f"{self.time_labels[w]} [{unit}]")
        self.table.set_text(self._table_to_unit(table))
        self.table.table.setHorizontalHeaderLabels((f"Time after start [{unit}]", "Relative height"))
        self.refresh()

    def strength_changed(self, *_):
        if getattr(self, "compiled", None):
            value = self.compiled["peak"] if self.normalization.currentData() == "peak" else self.compiled["charge"]
            self.amount.setText(repr(value))
        self.refresh()

    def settings(self):
        s = dict(shape=self.kind.currentData(), start=self.seconds_text(self.start),
                 normalization=self.normalization.currentData(), amount=self.entry_text(self.amount),
                 repeat=self.entry_text(self.repeat))
        kind = s["shape"]
        if kind in ("square", "sin2"):
            s["duration"] = self.seconds_text(self.duration)
        elif kind == "trapezoid":
            s.update(rise=self.seconds_text(self.rise), hold=self.seconds_text(self.hold),
                     fall=self.seconds_text(self.fall))
        elif kind == "gaussian":
            s.update(fwhm=self.seconds_text(self.fwhm), cutoff=self.entry_text(self.cutoff))
        elif kind == "arbitrary":
            s.update(points=self._table_seconds(), table_units="seconds")
        try:
            if int(round(self.ev.num(s["repeat"]))) > 1:
                s["period"] = self.seconds_text(self.period)
        except Exception:
            pass
        return s

    def result_spec(self):
        d = copy.deepcopy(self.spec)
        if self.kind.currentData() != "existing":
            p = build_pulse(self.settings(), self.ev)
            d.update(current_density=p["expression"], t_start=p["t_start"], t_stop=p["t_stop"])
            d["pulse_builder"] = dict(p["settings"], generated_expression=p["expression"])
        return d

    def refresh(self, *_):
        if not hasattr(self, "period"):
            return
        kind = self.kind.currentData()
        existing = kind == "existing"
        try:
            train = int(round(self.ev.num(self.entry_text(self.repeat)))) > 1
        except Exception:
            train = False
        self.visible(self.duration, kind in ("square", "sin2", "existing"))
        for w in (self.rise, self.hold, self.fall):
            self.visible(w, kind == "trapezoid")
        self.visible(self.fwhm, kind == "gaussian")
        self.visible(self.cutoff, kind == "gaussian")
        self.table.setVisible(kind == "arbitrary")
        for w in (self.normalization, self.amount, self.repeat):
            self.visible(w, not existing)
        self.visible(self.period, not existing and train)
        label = "Peak J [A/m²]" if self.normalization.currentData() == "peak" else "Charge / area [C/m²]"
        self.form.labelForField(self.amount).setText(label)
        if existing:
            self.form.labelForField(self.duration).setText(f"Preview window [{self.time_unit.currentText()}]")
        else:
            self.form.labelForField(self.duration).setText(f"Duration T [{self.time_unit.currentText()}]")
        self.help.setText(PULSE_HELP[kind])
        self.compiled = None
        unit = self.time_unit.currentText()
        try:
            ax = self.plot.axes[0]
            ax.clear()
            if existing:
                start = self.ev.num(self.seconds_text(self.start))
                duration = self.ev.num(self.seconds_text(self.duration))
                if not np.isfinite(start) or not np.isfinite(duration) or duration <= 0:
                    raise ValueError("Preview start must be finite and the window positive.")
                times = np.linspace(start, start + duration, 1001)
                fun = self.ev.func_t(self.spec.get("current_density", "0"))
                t0 = self.ev.num(self.spec.get("t_start", 0))
                t1 = self.ev.num(self.spec.get("t_stop", 1e9))
                j = np.array([fun(t) if t0 <= t <= t1 else 0 for t in times])
                if not np.isfinite(j).all():
                    raise ValueError("The current expression produced non-finite values.")
                self.expression.setPlainText(str(self.spec.get("current_density", "0")))
                self.summary.setText(f"Current expression · largest J in the window {j.max():.5g} A/m²")
            else:
                p = self.compiled = build_pulse(self.settings(), self.ev)
                pad = 0.06 * p["total"]
                times = np.linspace(p["start"] - pad, p["start"] + p["total"] + pad, 2001)
                if p["points"] is not None:
                    times = np.unique(np.r_[times, p["start"] + p["points"][:, 0]])
                j = p["train"](times)
                self.expression.setPlainText(p["expression"])
                text = [f"Peak J = {p['peak']:.5g} A/m²   ·   charge / area of one pulse = {p['charge']:.5g} C/m²",
                        f"Pulse length T = {p['duration']:.5g} s   ·   FWHM = {p['fwhm']:.5g} s"]
                if p["repeat"] > 1:
                    text.append(f"{p['repeat']} pulses, period {p['period']:.5g} s: total charge {p['charge_total']:.5g} C/m²")
                dt_text = str(self.context.get("simulation_dt", "")).strip()
                try:
                    dt = self.ev.num(dt_text) if dt_text and dt_text.lower() != "auto" else None
                except Exception:
                    dt = None
                if dt is None:
                    text.append("Set Study / Solver > Time step (dt): the shortest feature "
                                f"({p['resolve']:.3g} s) should span ≥ 20 steps, i.e. dt ≤ {p['resolve'] / 20:.3g} s.")
                elif dt > 0:
                    n = p["resolve"] / dt
                    text.append(f"Shortest feature spans {n:.3g} steps of dt = {dt:.3g} s" +
                                ("." if n >= 20 else f" - use dt ≤ {p['resolve'] / 20:.3g} s to resolve it."))
                try:
                    end = self.ev.num(self.context.get("simulation_end", ""))
                    if end < p["start"] + p["total"]:
                        text.append("The pulse ends after the simulation end time.")
                except Exception:
                    pass
                self.summary.setText("\n".join(text))
            ax.plot(times / self.time_scale, j, color="C0", linewidth=2)
            ax.fill_between(times / self.time_scale, 0, j, color="C0", alpha=.16)
            ax.set_xlabel(f"Time [{unit}]")
            ax.set_ylabel("Current density J [A/m²]")
            ax.set_title("Current pulse")
            ax.grid(alpha=.2)
            self.plot.draw()
            self.valid()
        except Exception as exc:
            self.failed(exc)
