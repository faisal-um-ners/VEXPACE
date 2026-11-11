"""Object histories opt in independently and never gate material physics."""
import copy
from unittest.mock import Mock, patch

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from picstudio.core.simulation import Simulation
from picstudio.gui.forms import FieldForm
from picstudio.gui.results import LivePanel, ResultsPanel
from picstudio.model import model as M, schema as S
from picstudio.post.reader import Results


def model(solver='electromagnetic'):
    m=M.new_model('2D-ZY',solver)
    m['domain'].update(z_max='.001',y_max='.001',nz='16',ny='12')
    m['parallel'].update(mode='serial',threads=1)
    m['simulation'].update(n_steps='25',dt='5e-13')
    m['objects']=[dict(name='tooth',shape='rectangle',material='conductor',
                        z0='.0006',z1='.0007',y0='.0002',y1='.0008',voltage='7')]
    m['species']=[dict(name='e',preset='electron')]
    m['loaders']=[dict(name='cloud',species='e',z0='.0003',z1='.0005',y0='.0003',y1='.0007',
                       density='1e9',ppc='2',temperature='0',drift=['2e7','0','0'])]
    m['diagnostics'].update(history_every='5',live_every='25')
    return m


@pytest.mark.parametrize('current',[False,True])
@pytest.mark.parametrize('voltage',[False,True])
def test_independent_switches_control_saved_columns_and_real_work(current,voltage,tmp_path):
    m=model();m['objects'][0].update(record_current=current,record_voltage=voltage)
    s=Simulation(m,out_dir=str(tmp_path/'run'),log=lambda _:None)
    index=next(i for i,c in enumerate(s.mats.conductors) if c['source']=='object')
    observed=Mock(wraps=s.vfuncs[index]);s.vfuncs[index]=observed
    cols=s.history_columns();row=s.history_row()
    assert ('I_tooth' in cols)==current and ('V_tooth' in cols)==voltage
    assert observed.call_count==int(voltage)
    assert s.coll_obj.size==int(current)
    assert len(cols)==len(row)==len(s.history_units())
    # Actual object absorption still occurs and the source still supplies 7 V.
    assert s.voltages(0)[index]==7
    assert s.run()
    h,c=Results(str(tmp_path/'run')).history()
    assert ('I_tooth' in c)==current and ('V_tooth' in c)==voltage
    if current:assert np.max(abs(h[:,c.index('I_tooth')]))>0
    if voltage:np.testing.assert_allclose(h[:,c.index('V_tooth')],7)
    with np.load(tmp_path/'run/live.npz') as live:
        assert list(live['history_columns'])==c


def test_disabled_current_skips_object_histogram_but_not_dielectric_charging():
    m=model('electrostatic');m['objects'][0].update(material='dielectric',collect_charge=True)
    s=Simulation(m,write_output=False,log=lambda _:None)
    assert not s.obj_cur
    sp=s.species[0]
    with patch('picstudio.core.simulation.np.bincount',wraps=np.bincount) as histogram, \
         patch.object(s,'_stick_charge') as charging:
        s._account(sp,np.full(sp.n,10,dtype=np.int32))
    histogram.assert_not_called()
    charging.assert_called_once()


@pytest.mark.parametrize('solver',['electrostatic','electromagnetic'])
@pytest.mark.parametrize('material',['conductor','dielectric','absorber'])
def test_recording_choices_leave_particle_fields_and_charge_bitwise_identical(solver,material):
    off=model(solver);off['objects'][0].update(material=material,collect_charge=True)
    on=copy.deepcopy(off);on['objects'][0].update(record_current=True,record_voltage=True)
    a=Simulation(off,write_output=False,log=lambda _:None)
    b=Simulation(on,write_output=False,log=lambda _:None)
    for _ in range(25):
        a.step();b.step()
        for x,y in zip(a.species[0].arrays(),b.species[0].arrays()):np.testing.assert_array_equal(x,y)
        np.testing.assert_array_equal(a.F,b.F)
        np.testing.assert_array_equal(a.phi,b.phi)
        np.testing.assert_array_equal(a.rho,b.rho)
        if solver=='electromagnetic':
            for key in ('E0','E1','E2','B0','B1','B2','J0','J1','J2'):
                np.testing.assert_array_equal(getattr(a.yee,key),getattr(b.yee,key))
        if a.step_count%5==0:a.history_row();b.history_row()


def test_dense_current_slots_map_to_selected_object_not_object_index():
    m=model();one=m['objects'][0]
    m['objects']=[dict(one,name='skip0'),dict(one,name='enabled',record_current=True),dict(one,name='skip2')]
    s=Simulation(m,write_output=False,log=lambda _:None);sp=s.species[0]
    weights=sp.w[:3].copy();sp.keep(np.arange(sp.n)<3)
    s._account(sp,np.array([10,11,12],dtype=np.int32))
    np.testing.assert_allclose(s.coll_obj,[sp.q*weights[1]])
    assert s.obj_cur==[1]


def test_many_teeth_do_not_grow_history_unless_enabled():
    m=model('electrostatic');m['loaders']=[]
    m['objects']=[dict(m['objects'][0],name=f'tooth_{i}') for i in range(72)]
    s=Simulation(m,write_output=False,log=lambda _:None)
    assert not any('tooth_' in c for c in s.history_columns())
    assert s.coll_obj.size==0
    assert len(s.mats.conductors)==76  # all physical conductor objects remain
    assert len(s.history_columns())==13  # step,t,N,KE,W + domain I/V


def test_gui_options_round_trip_and_available_history_signals(tmp_path):
    app=QApplication.instance() or QApplication([])
    m=M.complete(model());values=m['objects'][0]
    assert values['record_current'] is False and values['record_voltage'] is False
    form=FieldForm(S.OBJECT,values)
    form.widgets['record_current'].setChecked(True)
    assert values['record_current'] and not values['record_voltage']
    form.widgets['record_voltage'].setChecked(True)
    path=tmp_path/'enabled.pic.json';M.save(m,path);loaded=M.load(path)
    assert loaded['objects'][0]['record_current'] and loaded['objects'][0]['record_voltage']
    copied=copy.deepcopy(loaded['objects'][0]);assert copied['record_current'] and copied['record_voltage']
    s=Simulation(loaded,write_output=False,log=lambda _:None)
    panel=LivePanel();panel._rebuild_signal_menu(s.history_columns())
    signals={a.text() for a in panel.sig_menu.actions()}
    assert {'I_tooth','V_tooth'}<=signals
    form.widgets['material'].setCurrentText('vacuum')
    assert form.widgets['record_current'].isHidden() and form.widgets['record_voltage'].isHidden()
    panel.close();form.close()
