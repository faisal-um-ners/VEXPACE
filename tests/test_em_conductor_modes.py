"""Regression checks for general electromagnetic conductor/bias choices.

Run: python -m pytest -q tests/test_em_conductor_modes.py

These tests are device-agnostic; they cover the model schema, validation,
existing GUI form integration, and the actual electromagnetic solver modes.
"""
import numpy as np
import pytest

from picstudio.model import model as M
from picstudio.model import schema as S


MODES = (
    "held at their potentials",
    "floating",
    "rf-compatible dc bias",
    "pec only",
)


def _field_only_model(mode, voltage="10"):
    m = M.new_model("2D-ZY", "electromagnetic", "EM conductor-mode test")
    m["domain"].update(z_min="0", z_max="0.01", nz="12",
                       y_min="0", y_max="0.005", ny="8")
    m["boundaries"]["y_max"]["voltage"] = str(voltage)
    m["simulation"].update(em_conductors=mode, n_steps="2")
    return m


@pytest.mark.parametrize("mode", MODES)
def test_modes_available_to_schema_and_json(mode, tmp_path):
    opts = {f.name: f for f in S.SIMULATION}
    field = opts["em_conductors"]
    assert mode in field.choices
    assert S.is_visible(field, {"solver": "electromagnetic"})
    assert not S.is_visible(field, {"solver": "electrostatic"})
    model = _field_only_model(mode)
    p = tmp_path / "case.pic.json"
    M.save(model, str(p))
    assert M.load(str(p))["simulation"]["em_conductors"] == mode


def test_legacy_default_is_preserved():
    m = M.new_model("2D-ZY", "electromagnetic")
    assert m["simulation"]["em_conductors"] == "held at their potentials"


def test_static_bias_rejects_time_dependent_voltage():
    m = _field_only_model("rf-compatible dc bias", "100*sin(2*pi*1e9*t)")
    errs = [message for level, message in M.validate(m) if level == "error"]
    assert any("time-independent" in message for message in errs)


def test_static_bias_rejects_time_dependent_voltage_at_runtime():
    from picstudio.core.simulation import Simulation
    m = _field_only_model("rf-compatible dc bias", "100*sin(2*pi*1e9*t)")
    with pytest.raises(ValueError, match="time-independent"):
        Simulation(m, write_output=False, log=lambda _: None)


@pytest.mark.parametrize("mode", MODES)
def test_em_modes_instantiated_and_stepped(mode):
    from picstudio.core.simulation import Simulation
    m = _field_only_model(mode)
    errs = [message for level, message in M.validate(m) if level == "error"]
    assert not errs
    sim = Simulation(m, write_output=False, log=lambda _: None)
    assert (sim.circuit is not None) == (mode == "held at their potentials")
    sim.step()
    assert np.isfinite(sim.yee.energy())


def test_pec_only_ignores_applied_voltage():
    from picstudio.core.simulation import Simulation
    m = _field_only_model("pec only", voltage="100")
    sim = Simulation(m, write_output=False, log=lambda _: None)
    assert np.all(sim.F[:3] == 0.0)
    sim.step()
    assert np.all(sim.F[:3] == 0.0)


def test_prescribed_dc_bias_affects_particle_fields_but_not_yee_state():
    from picstudio.core.simulation import Simulation
    m = _field_only_model("rf-compatible dc bias", voltage="100")
    sim = Simulation(m, write_output=False, log=lambda _: None)
    assert np.max(np.abs(sim.F[:2])) > 0
    assert np.max(np.abs(sim.yee.E0)) == 0.0
    assert np.max(np.abs(sim.yee.E1)) == 0.0
    sim.step()
    assert np.max(np.abs(sim.yee.E0)) == 0.0
    assert np.max(np.abs(sim.yee.E1)) == 0.0


def test_legacy_floating_with_time_dependent_voltage_is_unchanged():
    from picstudio.core.simulation import Simulation
    m = _field_only_model("floating", "100*sin(2*pi*1e9*t)")
    sim = Simulation(m, write_output=False, log=lambda _: None)
    assert sim.circuit is None
    sim.step()
    assert np.isfinite(sim.yee.energy())
