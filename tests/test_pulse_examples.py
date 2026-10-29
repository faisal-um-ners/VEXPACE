"""The teaching pulse examples remain resolved, finite and self-consistent."""
from pathlib import Path
import numpy as np
import pytest
from picstudio import constants as C
from picstudio.model import model as M
from picstudio.mesh.grid import grid_from_model
from picstudio.sources.pulses import build_pulse

CASES = [
    ('source_designer_beam_1d', '1D-Z', 'gaussian'),
    ('source_designer_square_1d', '1D-Z', 'square'),
    ('source_designer_trapezoid_1d', '1D-Z', 'trapezoid'),
    ('source_designer_pulse_rz', '2D-RZ', 'gaussian'),
    ('source_designer_pulse_zy', '2D-ZY', 'trapezoid'),
]


@pytest.mark.parametrize('name,geometry,shape', CASES)
def test_vacuum_pulse_example_definitions(name, geometry, shape):
    p = Path(__file__).resolve().parents[1]/'examples'/(name+'.pic.json')
    m = M.load(p)
    ev = M.evaluator(m)
    assert not [msg for level,msg in M.validate(m) if level=='error']
    assert m['objects'] == [] and m['external_fields'] == []
    assert m['simulation']['geometry'] == geometry
    assert m['emitters'][0]['model'] == 'beam'
    e = m['emitters'][0]
    pulse = build_pulse(e['pulse_builder'], ev)
    assert e['pulse_builder']['shape'] == shape
    assert e['current_density'] == pulse['expression']
    dt = ev.num(m['simulation']['dt'])
    assert pulse['duration']/dt >= 100
    gamma = 1 + ev.num(e['energy'])*C.e/(C.me*C.c**2)
    speed = C.c*np.sqrt(1-1/gamma**2)
    travel = (ev.num(m['domain']['z_max'])-ev.num(m['domain']['z_min']))/speed
    assert ev.num(m['simulation']['t_end']) > pulse['start']+pulse['duration']+travel
    if geometry != '1D-Z':
        regions = m['mesh_refinements']
        assert [r['region_shape'] for r in regions] == ['polygon', 'rectangle']
        assert all(r['axis'] == 'local 2D' and ev.num(r['buffer']) > 0 and ev.num(r['growth']) > 1 for r in regions)
        g = grid_from_model(m, ev)
        assert hasattr(g, 'local_mesh')
        assert np.max(g.local_mesh.area) > 2*np.min(g.local_mesh.area)
        assert m['simulation']['smoothing'] == 0
