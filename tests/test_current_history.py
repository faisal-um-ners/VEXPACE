"""A three-step square source must not be drawn as a trapezoid."""
from pathlib import Path
import numpy as np
import pytest
from matplotlib.figure import Figure
from PySide6.QtWidgets import QApplication

from picstudio.core.simulation import Simulation
from picstudio.gui.results import LivePanel
from picstudio.gui.figure_export.bridge import snapshot_spec, render_snapshot
from picstudio.gui.figure_export.gui import export_dialog as E
from picstudio.model import model as M
from picstudio.post import plotting as P
from picstudio.sources.pulses import build_pulse


@pytest.mark.parametrize('geom,name',[('2D-RZ','rz'),('2D-ZY','zy')])
def test_three_step_square_has_three_nonzero_recorded_intervals(geom,name):
    root=Path(__file__).resolve().parents[1]
    m=M.load(root/'examples'/f'source_designer_pulse_{name}.pic.json')
    settings=dict(shape='square',start='0',duration='3e-12',amount='10000')
    pulse=build_pulse(settings,M.evaluator(m))
    m['emitters'][0].update(current_density=pulse['expression'],t_start=pulse['t_start'],
                            t_stop=pulse['t_stop'],particles_per_cell='64',
                            pulse_builder=dict(settings,generated_expression=pulse['expression']))
    s=Simulation(m,write_output=False,log=lambda _:None)
    rows=[s.history_row()]
    for _ in range(6):
        s.step();rows.append(s.history_row())
    H=np.asarray(rows);cols=s.history_columns();i=cols.index('Iemit_pulsed_beam')
    np.testing.assert_array_equal(np.flatnonzero(H[:,i]),[1,2,3])
    R=M.evaluator(m).num('R')
    area=np.pi*R**2 if geom=='2D-RZ' else R
    np.testing.assert_allclose(abs(H[1:4,i])/area,10000,rtol=.01)
    np.testing.assert_array_equal(H[4:,i],0)
    assert np.isclose(np.sum(H[1:,i]*np.diff(H[:,cols.index('t')])),
                      s.species[0].q*s.species[0].w.sum(),rtol=1e-12,atol=0)


def assert_no_diagonal_segments(line):
    delta=np.diff(line.get_path().vertices,axis=0)
    assert not np.any((delta[:,0]!=0)&(delta[:,1]!=0))


def test_live_results_and_export_show_current_intervals_without_invented_ramps():
    app=QApplication.instance() or QApplication([])
    cols=['t','Iemit_beam','I_collector','N_electrons']
    H=np.array([[0,0,0,0],[1e-12,-.07,0,768],[2e-12,-.07,0,1536],
                [3e-12,-.07,0,2304],[4e-12,0,0,2304],[5e-12,0,0,2304]])
    d=dict(history=H,history_columns=cols,history_units=['s','A','A',''],t_end=5e-12)
    panel=LivePanel();panel.checked=set(cols[1:]);panel.sig_names=cols[1:]
    panel._history(panel.plot.axes[-1],d)
    fig=Figure();ax=fig.subplots();P.plot_history(ax,H,cols,cols[1:])
    for axis in (panel.plot.axes[-1],ax):
        assert [line.get_drawstyle() for line in axis.lines]==['steps-pre','steps-pre','default']
        for line in axis.lines[:2]:
            assert_no_diagonal_segments(line)
            np.testing.assert_array_equal(line.get_xdata(),H[:,0])
        np.testing.assert_array_equal(axis.lines[0].get_ydata(),H[:,1])
    spec,view=snapshot_spec(panel.plot.fig)
    opts=E.ExportOptions(panels=E.defaults_from_spec(spec,view))
    with __import__('matplotlib').rc_context(E.export_rc(opts)):
        exported,axes=render_snapshot(E.build_spec(spec,opts),opts,100)
    for line in axes[-1].lines[:2]:assert_no_diagonal_segments(line)
    panel.close()
