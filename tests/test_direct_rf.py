"""Direct RF dot product, passive integration, event coverage and GUI controls."""
import copy
import csv
import json
import numpy as np
import pytest
from picstudio import constants as C
from picstudio.core.simulation import Simulation
from picstudio.diagnostics.direct_rf import direct_rf_boris_work
from picstudio.diagnostics.energy import boris_work
from picstudio.model import model as M
from picstudio.particles.species import Species
from test_energy_diagnostics import model


@pytest.mark.parametrize('rel',[False,True])
def test_direct_rf_dot_product_and_passivity(rel):
    from picstudio.particles.kernels import _momentum
    rng=np.random.default_rng(915)
    u=rng.normal(size=(3,64))*3e7;E=rng.normal(size=(3,64))*1e7;B=rng.normal(size=(3,64))*.4
    mean=rng.normal(size=(3,64))*1e6;dt=1e-13
    after=np.array([_momentum(*u[:,i],*E[:,i],*B[:,i],-C.e/C.me,dt,-1.,1/C.c**2 if rel else 0.,0) for i in range(64)]).T
    inputs=[u,after,E,mean];before=[x.copy() for x in inputs]
    result=direct_rf_boris_work(u,after,E,mean,-C.e,C.me,dt,rel)
    np.testing.assert_allclose(result['rf_direct_J'],boris_work(u,after,E,mean,-C.e/C.me,dt,C.me,rel)[2],rtol=2e-12,atol=1e-30)
    for a,b in zip(inputs,before):np.testing.assert_array_equal(a,b)
    assert not np.any(direct_rf_boris_work(u,after,E,E,-C.e,C.me,dt,rel)['rf_direct_J'])
    zero=np.zeros((3,1));field=np.array([[1.],[0.],[0.]])
    accelerated=zero-C.e/C.me*dt*field
    work=direct_rf_boris_work(zero,accelerated,field,zero,-C.e,C.me,dt,False)['rf_direct_J'][0]
    np.testing.assert_allclose(work,-C.e**2*dt**2/(2*C.me),rtol=1e-14)
    assert work<0


@pytest.mark.parametrize('mode',['held at their potentials','floating','rf-compatible dc bias','pec only'])
@pytest.mark.parametrize('smoothing',[0,1])
def test_direct_option_leaves_simulation_bitwise_identical(mode,smoothing):
    off=model();off['simulation'].update(em_conductors=mode,smoothing=smoothing,current_filter=1)
    on=copy.deepcopy(off);on['diagnostics'].update(energy_direct_rf=True,energy_rf_push_trace=True)
    a=Simulation(off,write_output=False,log=lambda _:None)
    b=Simulation(on,write_output=False,log=lambda _:None)
    for _ in range(30):
        a.step();b.step()
        for x,y in zip(a.species[0].arrays(),b.species[0].arrays()):np.testing.assert_array_equal(x,y)
        for key in ('E0','E1','E2','B0','B1','B2','J0','J1','J2'):
            np.testing.assert_array_equal(getattr(a.yee,key),getattr(b.yee,key))
        assert a.rng.bit_generator.state==b.rng.bit_generator.state
    d=b.energy_diag;h=dict(zip(d.names_units(),d.history_values()))
    np.testing.assert_allclose(h['ED_W_rf_direct'],h['ED_W_rf'],rtol=1e-12,atol=1e-28)
    assert abs(h['ED_R_rf_arithmetic'])<1e-25
    assert h['ED_R_rf_exchange']==h['ED_W_rf_direct']-h['ED_W_grid_rf_direct']
    a.energy_diag.close();b.energy_diag.close();a.out.close();b.out.close()


def test_direct_array_birth_compaction_and_slot_reuse():
    sp=Species(dict(name='e',preset='electron'),M.evaluator(M.new_model()),index=1,capacity=2)
    sp.enable_energy_tracking(rank=2,direct_rf=True)
    x=np.ones(40);sp.add(x,x,x,x,x,x)
    a=sp._diagnostic_arrays;a['work_rf_direct'][:40]=np.arange(40);a['rf_valid_since'][:40]=.25
    ids=a['id'][:40].copy();sp.keep(np.arange(40)%2==0)
    np.testing.assert_array_equal(a['work_rf_direct'][:20],np.arange(40)[::2])
    np.testing.assert_array_equal(a['id'][:20],ids[::2])
    sp.add(x,x,x,x,x,x)
    a=sp._diagnostic_arrays
    assert np.all(a['work_rf_direct'][20:60]==0)
    assert np.all(np.isnan(a['rf_valid_since'][20:60]))
    assert len(np.unique(a['id'][:sp.n]))==sp.n
    # Enabling the additional counter later must not regenerate identities.
    other=Species(dict(name='e',preset='electron'),M.evaluator(M.new_model()))
    other.enable_energy_tracking();other.add(x,x,x,x,x,x)
    original=other._diagnostic_arrays['id'][:40].copy()
    other.enable_energy_tracking(direct_rf=True)
    np.testing.assert_array_equal(original,other._diagnostic_arrays['id'][:40])
    assert np.isnan(other._diagnostic_arrays['rf_valid_since'][:40]).all()


def test_raw_trace_reproduces_work_without_KE_or_work_residual(tmp_path):
    m=model();m['diagnostics'].update(energy_direct_rf=True,energy_rf_push_trace=True)
    s=Simulation(m,out_dir=str(tmp_path/'run'),log=lambda _:None);assert s.run()
    root=tmp_path/'run';rows=[]
    for p in sorted((root/'energy_diagnostics').glob('rf_push_rank*.npz')):
        with np.load(p) as a:rows.append({k:a[k].copy() for k in a.files})
    assert rows
    a={k:np.concatenate([r[k] for r in rows]) for k in rows[0]}
    explicit=C.e*np.sum((a['E_gathered']-a['E_DC_gathered'])*a['d_Boris'],axis=1)
    np.testing.assert_allclose(explicit,a['delta_W_rf_direct_J'],rtol=1e-13,atol=1e-30)
    hist=np.genfromtxt(root/'history.csv',delimiter=',',names=True)
    np.testing.assert_allclose(np.dot(a['weight'],explicit),hist['ED_W_rf_direct'][-1],rtol=2e-8,atol=1e-28)
    # A write cadence of two steps still captures EVERY post-reference push.
    assert np.any(a['step']%2==1)
    with np.load(root/'live.npz') as live:
        cols=list(live['history_columns']);assert 'ED_W_rf_direct' in cols
        assert live['history_units'][cols.index('ED_P_rf_direct')]=='W/m'
    meta=json.loads((root/'energy_diagnostics/metadata.json').read_text())
    assert meta['direct_rf_enabled'] and meta['raw_rf_push_trace'] and meta['format_version']==2


def test_crossing_and_absorption_push_are_not_lost(tmp_path):
    m=model();m['loaders']=[];m['diagnostics'].update(energy_direct_rf=True,energy_rf_push_trace=True,
        energy_reference_time='1e-13',energy_hub_y='.0005')
    s=Simulation(m,out_dir=str(tmp_path/'events'),log=lambda _:None)
    s.step();assert s.energy_diag.reference_ready
    sp=s.species[0];x=np.ones(2);zero=x*0
    sp.add(x*.0004,np.array([.00049999,.00099999]),zero,x*1e7,zero,x)
    s.step()
    assert sp.n==1
    s.energy_diag.close();s.out.close()
    root=tmp_path/'events/energy_diagnostics'
    events=list(csv.DictReader((root/'impacts_rank0000.csv').open()))
    crosses=list(csv.DictReader((root/'hub_crossings_rank0000.csv').open()))
    assert len(events)==len(crosses)==1
    hit=events[0];assert np.isfinite(float(hit['W_rf_direct_J']))
    assert float(hit['y_after_unclipped'])>float(hit['y'])
    assert float(hit['rf_valid_since'])==pytest.approx(1e-13)
    assert {'W_rf_direct_before_J','W_rf_direct_after_J','fraction'}<=set(crosses[0])
    with np.load(next(root.glob('rf_push_rank*.npz'))) as trace:
        assert int(hit['id']) in trace['id']
        assert int(hit['step']) in trace['step']


def test_native_rf_uses_actual_midpoint_and_particle_current():
    m=model();m['loaders']=[];m['diagnostics']['energy_direct_rf']=True
    s=Simulation(m,write_output=False,log=lambda _:None);d=s.energy_diag
    d.reference_ready=True
    rng=np.random.default_rng(3)
    for k in range(3):
        d.native_mean[k][:]=rng.normal(size=d.native_mean[k].shape)
        d.particle_J[k][:]=rng.normal(size=d.particle_J[k].shape)
        getattr(s.yee,f'E{k}')[:]=rng.normal(size=d.native_mean[k].shape)
    d.before_E()
    for k in range(3):getattr(s.yee,f'E{k}')[:]+=2
    expected=-s.dt*sum(float(np.sum(d.particle_J[k]*(d.old_E[k]+1-d.native_mean[k])*d.vol[k])) for k in range(3))
    d.after_E();np.testing.assert_allclose(d.grid['rf_direct'],expected,rtol=1e-14)
    d.close()


def test_invalid_trace_setting_preserves_existing_output(tmp_path):
    m=model();m['diagnostics']['energy_rf_push_trace']=True
    root=tmp_path/'keep';root.mkdir();f=root/'history.csv';f.write_text('original')
    with pytest.raises(ValueError,match='require Direct RF'):Simulation(m,out_dir=str(root))
    assert f.read_text()=='original'


def test_trace_cleanup_only_removes_owned_files(tmp_path):
    from picstudio.diagnostics.output import Output
    aux=tmp_path/'energy_diagnostics';aux.mkdir()
    stale=aux/'rf_push_rank0001_00002.npz';stale.write_bytes(b'stale')
    note=aux/'rf_push_notes.npz';note.write_bytes(b'keep')
    Output(str(tmp_path)).close()
    assert not stale.exists() and note.read_bytes()==b'keep'


def test_gui_controls_and_history_labels(tmp_path):
    from PySide6.QtWidgets import QApplication
    from picstudio.gui.forms import FieldForm
    from picstudio.gui.results import LivePanel
    from picstudio.model import schema as S
    app=QApplication.instance() or QApplication([])
    m=M.new_model('2D-ZY','electromagnetic');form=FieldForm(S.DIAGNOSTICS,m['diagnostics'])
    assert form.widgets['energy_direct_rf'].isHidden()
    form.widgets['energy_enabled'].setChecked(True)
    assert not form.widgets['energy_direct_rf'].isHidden()
    assert form.widgets['energy_rf_push_trace'].isHidden()
    form.widgets['energy_direct_rf'].setChecked(True)
    assert not form.widgets['energy_rf_push_trace'].isHidden()
    form.widgets['energy_rf_push_trace'].setChecked(True)
    path=tmp_path/'new.pic.json';M.save(m,path);loaded=M.load(path)
    assert loaded['diagnostics']['energy_direct_rf'] and loaded['diagnostics']['energy_rf_push_trace']
    panel=LivePanel();panel._rebuild_signal_menu(['t','ED_W_rf_direct','ED_P_rf_direct','ED_R_rf_exchange'])
    labels={a.text() for a in panel.sig_menu.actions()}
    assert 'Direct RF work from particles [J/m]' in labels
    assert 'Direct RF power from particles [W/m]' in labels
    assert 'Particle minus native-grid RF work [J/m]' in labels
    panel.close();form.close()
