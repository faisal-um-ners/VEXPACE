"""Distribution statistics, opt-in integration, pulse normalization and guided editors."""
import copy
import os
import numpy as np
import pytest
from scipy.integrate import quad

from picstudio import constants as C
from picstudio.expr import Evaluator
from picstudio.model import model as M
from picstudio.sources.distributions import read_points, table_quantile, sample_offsets
from picstudio.sources.pulses import build_pulse


@pytest.mark.parametrize("plateau", [0, .4, 1])
def test_bounded_distributions_have_expected_moments(plateau):
    # Var(trapezoid on [-a,a], plateau [-pa,pa]) = a²(1+p²)/6.
    spec = dict(velocity_distribution="trapezoid", velocity_width=["2", "3", "0"],
                velocity_plateau=str(plateau))
    v = sample_offsets(spec, Evaluator(), np.random.default_rng(3), 300_000)
    assert np.max(abs(v[0])) <= 2 and np.max(abs(v[1])) <= 3
    assert np.all(v[2] == 0)
    assert abs(v[0].mean()) < .006
    np.testing.assert_allclose(v[:2].var(axis=1), np.array([4, 9])*(1+plateau**2)/6, rtol=.009)
    assert abs(np.corrcoef(v[:2])[0, 1]) < .008


def test_tabulated_inverse_cdf_and_empty_intervals():
    # f(x) = 2x on [0,1]: inverse CDF is sqrt(p).
    p = np.linspace(0, 1, 10001)
    np.testing.assert_allclose(table_quantile(np.array([[0., 0.], [1., 2.]]), p), np.sqrt(p), atol=1e-14)
    table = np.array([[0., 0.], [1., 0.], [2., 1.], [3., 0.], [4., 0.]])
    values = table_quantile(table, (np.arange(10000)+.5)/10000)
    assert values.min() >= 1 and values.max() <= 3
    assert abs(values.mean()-2) < 1e-12
    points = read_points("offset,weight\n-a,0\n0,1\na,0", Evaluator({"a": "2"}))
    np.testing.assert_array_equal(points[:, 0], [-2, 0, 2])


def test_quiet_custom_quantiles_are_stratified_per_cell():
    spec = dict(velocity_distribution="waterbag", velocity_width=["2", "0", "0"])
    v = sample_offsets(spec, Evaluator(), np.random.default_rng(5), 64, quiet=True, ppc=32,
                       cells=np.repeat([4, 7], 32), slots=np.tile(np.arange(32), 2))
    for cell in v[0].reshape(2, 32):
        np.testing.assert_allclose(np.sort(cell), -2+4*(np.arange(32)+.5)/32, atol=1e-14)


@pytest.mark.parametrize("text", ["0,1\n0,2", "0,-1\n1,1", "0,0\n1,0", "0,nan\n1,1", "0,1"])
def test_invalid_tables_rejected(text):
    with pytest.raises(ValueError):
        read_points(text, Evaluator())


@pytest.mark.parametrize("shape", ["square", "trapezoid", "gaussian", "arbitrary"])
@pytest.mark.parametrize("normalization", ["peak", "charge"])
def test_pulse_expression_and_continuous_charge(shape, normalization):
    settings = dict(shape=shape, start="2e-9", duration="3e-9", rise=".6e-9", cutoff="2.5",
                    normalization=normalization, amount="0.0002" if normalization == "charge" else "5e4")
    ev = Evaluator()
    p = build_pulse(settings, ev)
    f = ev.func_t(p["expression"])
    start, end = 2e-9, 5e-9
    actual = quad(lambda x: f(start+x*(end-start))*(end-start), 0, 1,
                  points=[.2, .3, .5, .7, .8], epsabs=1e-16)[0]
    assert actual == pytest.approx(p["charge"], rel=1e-10)
    assert f(start-1e-12) == 0 and f(end+1e-12) == 0
    if normalization == "charge":
        assert actual == pytest.approx(.0002, rel=1e-10)


def test_parameter_changes_propagate_through_generated_expression():
    for shape in ("square", "trapezoid", "gaussian", "arbitrary"):
        a = dict(duration="D", amount="Q", normalization="charge", shape=shape,
                 rise="D/5", cutoff="cut", points="0,0\n0.4,height\n1,0")
        p = build_pulse(a, Evaluator({"D": "1e-9", "Q": "1e-5", "cut": "2", "height": "2"}))
        new = Evaluator({"D": "2e-9", "Q": "3e-5", "cut": "3", "height": "4"})
        f = new.func_t(p["expression"])
        actual = quad(lambda x: f(x*2e-9)*2e-9, 0, 1, points=[.2,.4,.8], epsabs=1e-15)[0]
        assert actual == pytest.approx(3e-5, rel=1e-9)
        assert new.num(p["t_stop"]) == pytest.approx(2e-9, rel=1e-12)


def test_short_pulse_existing_convention_reproduced():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for shape in ("square", "trapezoid", "gaussian"):
        m = M.load(root / f"examples/short_pulse_diode_2025_{shape}_1d.pic.json")
        ev = M.evaluator(m)
        settings = dict(shape=shape, start="0", duration="support", normalization="peak", amount="Jamp",
                        rise="ramp_fraction*support" if shape == "trapezoid" else "support/5",
                        cutoff="gaussian_cutoff_sigma" if shape == "gaussian" else "3",
                        sample_shift="sample_dt/2")          # old setting: dropped (midpoint emitter)
        new = ev.func_t(build_pulse(settings, ev)["expression"])
        old = ev.func_t(m["emitters"][0]["current_density"])
        for t in np.linspace(0, ev.num("support")*1.05, 201):
            assert new(t) == pytest.approx(old(t), abs=1e-7, rel=1e-12)


def test_beam_custom_distribution_keeps_charge_and_default_results():
    from picstudio.core.simulation import Simulation
    m = M.new_model("1D-Z")
    m["parallel"].update(mode="serial", threads=1)
    m["domain"].update(z_max=".01", nz="16")
    m["species"] = [dict(name="e", preset="electron")]
    m["emitters"] = [dict(name="beam", model="beam", species="e", current_density="1e-4", energy="1",
                           temperature=".1", particles_per_cell="4000", z0="0", velocity_version="2")]
    m["simulation"].update(dt="1e-13", n_steps="2")
    def emitted(model):
        sim = Simulation(model, write_output=False, log=lambda _: None)
        return sim, sim.emitters[0].emit(0, sim.dt, np.random.default_rng(10), phi=sim.phi)
    _, a = emitted(m)
    _, a2 = emitted(copy.deepcopy(m))
    for key in a:                                  # the default (legacy) beam is unchanged/deterministic
        np.testing.assert_array_equal(a[key], a2[key])
    vb = C.c*np.sqrt(1-1/(1+C.e/(C.me*C.c**2))**2)
    s = np.sqrt(.1*C.e/C.me)
    cases = {
        "cold": dict(),
        "maxwellian": dict(energy="0"),                                  # Rayleigh flux, mean s*sqrt(pi/2)
        "gaussian": dict(velocity_mean="6e5", velocity_spread="5e4"),
        "waterbag": dict(velocity_min="2e5", velocity_max="6e5"),
        "waterbag_phase": dict(velocity_min="2e5", velocity_max="6e5"),
        "trapezoid": dict(velocity_min="2e5", velocity_max="6e5", velocity_plateau=".5"),
        "arbitrary": dict(velocity_pdf_0="1e5,0\n3e5,1\n5e5,0", velocity_table_kind="flux"),
    }
    expected = {"cold": vb, "maxwellian": s*np.sqrt(np.pi/2), "gaussian": 6e5, "waterbag": 4e5,
                "waterbag_phase": 2/3*(6e5**3-2e5**3)/(6e5**2-2e5**2), "trapezoid": 4e5, "arbitrary": 3e5}
    for kind, extra in cases.items():
        custom = copy.deepcopy(m)
        custom["emitters"][0].update(velocity_distribution=kind, **extra)
        sim, b = emitted(custom)
        assert b["w"].sum() == pytest.approx(a["w"].sum(), rel=1e-12)   # same charge
        assert np.all(b["u1"] == 0)  # Existing 1D emitter constraint.
        assert np.all(b["u0"] >= 0)  # normal speeds point out of the wall
        u = b["u0"]
        v = u/np.sqrt(1+(u/C.c)**2)
        assert v.mean() == pytest.approx(expected[kind], rel=0.03), kind
        if kind.startswith("waterbag") or kind == "trapezoid":
            assert v.min() >= 2e5*(1-1e-9) and v.max() <= 6e5*(1+1e-9)


@pytest.mark.parametrize("local", [False, True])
def test_custom_loader_reaches_both_mesh_paths(local):
    from picstudio.core.simulation import Simulation
    m = M.new_model("2D-ZY")
    m["parallel"].update(mode="serial", threads=1)
    m["domain"].update(z_max="1", y_max="1", nz="8", ny="8")
    m["simulation"]["dt"] = "1e-18"
    m["species"] = [dict(name="e", preset="electron")]
    m["loaders"] = [dict(name="load", species="e", z0="0", z1="1", y0="0", y1="1", ppc="16",
                         density="1", drift=["10", "0", "0"], quiet_start=True,
                         velocity_distribution="waterbag", velocity_width=["2", "0", "0"])]
    if local:
        m["mesh_refinements"] = [dict(axis="local 2D", region_shape="rectangle", z0="0", z1=".5",
                                      y0="0", y1=".5", size=".06", growth="1.2", buffer=".02")]
    sim = Simulation(m, write_output=False, log=lambda _: None)
    sp = sim.species[0]
    assert sp.n > 0
    assert np.max(abs(sp.u0-10)) <= 2
    # Simulation initialization includes its existing electric half-step kick.
    assert np.max(abs(sp.u1)) < 1e-12 and np.all(sp.u2 == 0)
    assert sp.w.sum() == pytest.approx(1)


def test_model_roundtrip_custom_data_and_invalid_shape(tmp_path):
    m = M.new_model("1D-Z")
    m["species"] = [dict(name="e", preset="electron")]
    m["loaders"] = [dict(name="load", species="e", velocity_distribution="arbitrary",
                          velocity_pdf_0="-10,0\n0,1\n10,0")]
    path = tmp_path/"custom.pic.json"
    M.save(m, path)
    new = M.load(path)
    assert not [text for lvl, text in M.validate(new) if lvl == "error"]
    assert new["loaders"][0]["velocity_pdf_0"] == m["loaders"][0]["velocity_pdf_0"]
    new["loaders"][0]["velocity_pdf_1"] = "0,1\n0,2"
    assert any(level == "error" and "velocity" in msg for level,msg in M.validate(new))


def test_guided_dialogs_cancel_units_and_live_validation():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from picstudio.gui.source_designer import VelocityDialog, PulseDialog
    app = QApplication.instance() or QApplication([])
    spec = dict(species="e", current_density="10", energy="100")
    baseline = copy.deepcopy(spec)
    context = dict(species_specs=[dict(name="e", preset="electron")])
    v = VelocityDialog(spec, context, beam=True)
    for kind in ("cold", "maxwellian", "waterbag", "trapezoid", "arbitrary"):
        v.kind.setCurrentIndex(v.kind.findData(kind))
        assert not v.error.text(), v.error.text()
    v.reject()
    assert spec == baseline
    p = PulseDialog(spec, context)
    assert p.result_spec() == spec
    p.kind.setCurrentIndex(p.kind.findData("gaussian"))
    assert not p.error.text()
    fwhm = p.compiled["fwhm"]
    assert fwhm > 0 and p.compiled["duration"] > fwhm      # truncated at +-n sigma
    p.time_unit.setCurrentIndex(p.time_unit.findText("ps"))
    assert float(p.fwhm.text()) == pytest.approx(fwhm*1e12)
    assert p.compiled["fwhm"] == pytest.approx(fwhm, rel=1e-12)
    p.kind.setCurrentIndex(p.kind.findData("square"))
    p.duration.setText("-2")
    assert not p.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert p.error.text()
    p.reject()
    assert spec == baseline
    app.processEvents()


def test_form_applies_guided_edits_and_emits_dirty_signals():
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication, QDialog
    from picstudio.gui.forms import FieldForm
    from picstudio.gui.source_designer import VelocityDialog, PulseDialog
    from picstudio.model import schema as S
    app = QApplication.instance() or QApplication([])
    data = S.defaults(S.EMITTER)
    data.update(model="beam", species="e")
    form = FieldForm(S.EMITTER, data, dict(species=["e"], species_specs=[dict(name="e", preset="electron")]))
    changed = []
    form.changed.connect(changed.append)
    def velocity(dialog):
        dialog.kind.setCurrentIndex(dialog.kind.findData("waterbag"))
        return QDialog.Accepted
    with patch.object(VelocityDialog, "exec", velocity):
        form._source_dialog("velocity")
    assert data["velocity_distribution"] == "waterbag"
    assert "velocity_distribution" in changed
    def pulse(dialog):
        dialog.kind.setCurrentIndex(dialog.kind.findData("trapezoid"))
        return QDialog.Accepted
    with patch.object(PulseDialog, "exec", pulse):
        form._source_dialog("pulse")
    assert data["pulse_builder"]["shape"] == "trapezoid"
    assert form.widgets["current_density"].text() == data["current_density"]
    before = copy.deepcopy(data)
    with patch.object(PulseDialog, "exec", lambda _: QDialog.Rejected):
        form._source_dialog("pulse")
    assert data == before
    app.processEvents()


@pytest.mark.parametrize("values", [dict(duration="0"), dict(amount="-1"), dict(rise="1"), dict(cutoff="1")])
def test_invalid_pulse_settings_rejected(values):
    settings = dict(shape="trapezoid" if "rise" in values else "gaussian", duration="1e-9")
    settings.update(values)
    with pytest.raises(ValueError):
        build_pulse(settings, Evaluator())


def test_changed_parameters_validate_saved_pulse_metadata():
    m = M.new_model("1D-Z")
    m["species"] = [dict(name="e", preset="electron")]
    m["parameters"]["duration"] = "1e-9"
    settings = dict(shape="square", duration="duration", start="0", amount="1")
    compiled = build_pulse(settings, M.evaluator(m))
    m["emitters"] = [dict(name="e", model="beam", species="e", current_density=compiled["expression"],
                          pulse_builder=dict(settings, generated_expression=compiled["expression"]))]
    assert not [msg for lvl,msg in M.validate(m) if lvl == "error"]
    m["parameters"]["duration"] = "-1"
    assert any(lvl == "error" and "pulse" in msg for lvl,msg in M.validate(m))


def test_source_help_wraps_after_model_switch_and_panel_resize():
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QScrollArea
    from picstudio.gui.forms import FieldForm
    from picstudio.gui.theme import stylesheet
    from picstudio.model import schema as S
    app = QApplication.instance() or QApplication([])
    previous_style = app.styleSheet()
    window = QWidget()
    layout = QVBoxLayout(window)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    layout.addWidget(scroll)
    holder = QWidget()
    column = QVBoxLayout(holder)
    spec = S.defaults(S.EMITTER)
    spec['model'] = 'beam'
    form = FieldForm(S.EMITTER, spec, dict(species=['electrons']))
    column.addWidget(form)
    column.addStretch()
    scroll.setWidget(holder)
    window.show()
    try:
        for theme in ('light', 'dark'):
            app.setStyleSheet(stylesheet(theme))
            for width in (320, 400, 560, 360):
                window.resize(width, 650)
                for model in ('beam', 'scl', 'thermionic', 'photo', 'beam'):
                    form.widgets['model'].setCurrentIndex(form.widgets['model'].findData(model))
                    for _ in range(6):
                        app.processEvents()
                    for label in (form.velocity_summary, form.pulse_summary, form.source_hint):
                        if label.isVisible():
                            assert label.height() >= label.heightForWidth(label.width()), (theme, width, model, label.text())
                    assert not form.velocity_button.isHidden() if model == 'beam' else form.velocity_button.isHidden()
    finally:
        window.close()
        app.setStyleSheet(previous_style)
        app.processEvents()


def test_general_gaussian_cutoffs_and_weighting():
    """Gaussian with cut-offs and flux / phase-density weighting; Maxwellian is the special case
    mu = 0, sigma = sqrt(kT/m) with phase-density weighting."""
    from scipy.stats import truncnorm
    from picstudio.sources import distributions as D
    ev, rng = Evaluator(), np.random.default_rng(3)
    def mean(spec):
        return D.sample_normal(spec, ev, rng, 200000, C.me).mean()
    cut = dict(velocity_distribution="gaussian", velocity_mean="3e5", velocity_spread="2e5",
               velocity_cut_min="3e5", velocity_cut_max="5e5")
    v = D.sample_normal(cut, ev, rng, 20000, C.me)
    assert v.min() >= 3e5 and v.max() <= 5e5
    assert mean(cut) == pytest.approx(truncnorm.mean(0, 1, loc=3e5, scale=2e5), rel=3e-3)
    s = float(np.sqrt(0.2*C.e/C.me))
    phase = dict(velocity_distribution="gaussian", velocity_mean="0", velocity_spread=str(s),
                 velocity_weight="phase_density")
    assert mean(phase) == pytest.approx(mean(dict(velocity_distribution="maxwellian", temperature="0.2")), rel=1e-2)
    wb = dict(velocity_distribution="waterbag", velocity_min="1e5", velocity_max="4e5", velocity_weight="phase_density")
    assert mean(wb) == pytest.approx(2/3*(4e5**3-1e5**3)/(4e5**2-1e5**2), rel=3e-3)
    old = dict(velocity_distribution="waterbag_phase", velocity_min="1e5", velocity_max="4e5")
    assert D.weighting(old) == "phase_density"
    with pytest.raises(ValueError):
        D.validate_distribution(dict(cut, velocity_cut_max="2e5"), ev, emitter=True)
