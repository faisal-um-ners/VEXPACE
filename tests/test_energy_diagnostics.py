"""Independent energy identities, lost-particle accounting and passive-state tests."""
import copy
import csv
import json
import numpy as np
import pytest
from picstudio import constants as C
from picstudio.model import model as M
from picstudio.core.simulation import Simulation
from picstudio.diagnostics.energy import kinetic, boris_work
from picstudio.particles.species import Species


def model(enabled=True):
    m=M.new_model('2D-ZY','electromagnetic','Energy diagnostic regression')
    m['domain'].update(z_min='0',z_max='.001',nz='8',y_min='0',y_max='.001',ny='8')
    m['simulation'].update(n_steps='30',dt='1e-13',smoothing=1,em_conductors='pec only')
    m['parallel'].update(mode='serial',threads=1)
    m['species']=[dict(name='electrons',preset='electron')]
    m['loaders']=[dict(name='cloud',species='electrons',z0='.0002',z1='.0008',y0='.0002',y1='.0008',density='1e10',ppc='2',temperature='2',drift=['2e6','1e6','0'])]
    m['diagnostics'].update(energy_enabled=enabled,energy_reference_time='5e-13',energy_block_time='8e-13',
        energy_track_every='2',energy_track_stride='1',history_every='5',field_every='1000',particle_every='1000',live_every='1000')
    return m


@pytest.mark.parametrize('rel',[False,True])
def test_electric_kick_work_matches_independent_kinetic_change(rel):
    from picstudio.particles.kernels import _momentum
    rng=np.random.default_rng(21)
    u=rng.normal(size=(3,100))*3e7;E=rng.normal(size=(3,100))*1e7;B=rng.normal(size=(3,100))*.4
    out=np.array([_momentum(*u[:,i],*E[:,i],*B[:,i],-C.e/C.me,1e-12,-1.,1/C.c**2 if rel else 0.,0) for i in range(100)]).T
    total,dc,rf=boris_work(u,out,E,.3*E,-C.e/C.me,1e-12,C.me,rel)
    np.testing.assert_allclose(total,kinetic(out,C.me,rel)-kinetic(u,C.me,rel),rtol=2e-12,atol=1e-29)
    np.testing.assert_allclose(dc-rf,total,rtol=1e-14,atol=1e-30)
    np.testing.assert_allclose(dc,.3*total,rtol=1e-12,atol=1e-30)


def test_ids_survive_compaction_and_capacity_growth():
    sp=Species(dict(name='e',preset='electron'),M.evaluator(M.new_model()),index=2,capacity=2)
    sp.enable_energy_tracking(rank=3)
    a=np.ones(40);sp.add(a,a,a,a,a,a)
    ids=sp._diagnostic_arrays['id'][:40].copy()
    sp._diagnostic_arrays['work_dc'][:40]=np.arange(40)
    sp.keep(np.arange(40)%2==0)
    np.testing.assert_array_equal(sp._diagnostic_arrays['id'][:20],ids[::2])
    np.testing.assert_array_equal(sp._diagnostic_arrays['work_dc'][:20],np.arange(40)[::2])
    sp.add(a,a,a,a,a,a)
    assert len(np.unique(sp._diagnostic_arrays['id'][:sp.n]))==sp.n
    assert np.all(sp._diagnostic_arrays['work_dc'][20:sp.n]==0)


@pytest.mark.parametrize('mode',['held at their potentials','floating','rf-compatible dc bias','pec only'])
@pytest.mark.parametrize('smoothing',[0,1])
def test_enabled_diagnostics_leave_physics_bitwise_identical(tmp_path,mode,smoothing):
    off=model(False);off['simulation'].update(em_conductors=mode,smoothing=smoothing,current_filter=1)
    on=copy.deepcopy(off);on['diagnostics']['energy_enabled']=True
    a=Simulation(off,write_output=False,log=lambda _:None)
    b=Simulation(on,write_output=False,log=lambda _:None)
    for _ in range(30):
        a.step();b.step()
        for x,y in zip(a.species[0].arrays(),b.species[0].arrays()):np.testing.assert_array_equal(x,y)
        for k in ('E0','E1','E2','B0','B1','B2','J0','J1','J2'):
            np.testing.assert_array_equal(getattr(a.yee,k),getattr(b.yee,k))
    d=b.energy_diag;h=dict(zip(d.names_units(),d.history_values()))
    assert abs(h['ED_R_particle']) < 1e-24
    assert abs(h['ED_R_work_split']) < 1e-24
    assert d.reference_ready
    # Read-only history access must not consume/reset the energy counters.
    assert d.history_values()==d.history_values()
    a.out.close();b.out.close();d.close()


def test_absorption_counts_exact_weighted_KE_before_deletion():
    m=model();m['loaders']=[]
    s=Simulation(m,write_output=False,log=lambda _:None);sp=s.species[0]
    z=np.array([.0003,.0004]);y=z.copy();u=np.array([1e7,4e7]);w=np.array([2e5,3e5]);zero=u*0
    sp.add(z,y,u,zero,zero,w)
    flag=np.array([3,4],dtype=np.int32)
    expected=kinetic(np.array([u,zero,zero]),sp.m,True)*w
    s._account(sp,flag);sp.keep(flag==0)
    assert sp.n==0
    np.testing.assert_allclose(s.energy_diag.surfaces[2:4,2],expected,rtol=1e-14)
    np.testing.assert_allclose(s.energy_diag.hist[2:4].sum(axis=1),w)
    s.energy_diag.close()


def test_CN_load_loss_matches_actual_electric_energy_removal():
    m=model();m['loaders']=[]
    m['objects']=[dict(name='load',shape='rectangle',z0='0',z1='.001',y0='0',y1='.001',material='lossy',loss_spec='sigma',sigma='.1')]
    s=Simulation(m,write_output=False,log=lambda _:None);d=s.energy_diag
    rng=np.random.default_rng(7)
    for k in range(3):getattr(s.yee,'E'+str(k))[:]=rng.normal(size=getattr(s.yee,'E'+str(k)).shape)*getattr(s.yee,'m'+str(k))
    before=d.field_energy()[0];d.before_E();s.yee.full_E(s.dt);d.after_E();after=d.field_energy()[0]
    np.testing.assert_allclose(before-after,d.grid['load'],rtol=3e-12,atol=1e-28)
    assert d.grid['load']>0
    d.close()


def test_output_files_and_units_are_readable(tmp_path):
    m=model();m['diagnostics']['energy_save_work_grids']=True
    s=Simulation(m,out_dir=str(tmp_path/'run'),log=lambda _:None);assert s.run()
    cols=s.history_columns();units=s.history_units();assert len(cols)==len(units)
    assert units[cols.index('ED_W_rf')]=='J/m';assert units[cols.index('ED_P_load')]=='W/m'
    assert units[cols.index('ED_eta_load')]=='%'
    root=tmp_path/'run';meta=json.loads((root/'energy_diagnostics/metadata.json').read_text())
    assert meta['reference_ready']
    with np.load(root/'live.npz') as a:
        assert 'ED_W_rf' in a['history_columns'];assert 'Jz' in a.files
    with np.load(sorted((root/'particles').glob('part_*.npz'))[-1]) as a:assert 'electrons__id' in a.files
    rows=list(csv.DictReader((root/'energy_diagnostics/trajectories_rank0000.csv').open()))
    assert rows and {'id','W_dc_J','W_rf_J'}<=set(rows[0])
    assert list((root/'energy_diagnostics').glob('work_block_*.npz'))


def test_unsupported_mode_rejected_before_touching_output(tmp_path):
    m=model();m['simulation']['particle_pusher']='vay'
    p=tmp_path/'keep';p.mkdir();f=p/'history.csv';f.write_text('original')
    assert any(l=='error' and 'Boris' in v for l,v in M.validate(m))
    with pytest.raises(ValueError,match='Boris'):Simulation(m,out_dir=str(p))
    assert f.read_text()=='original'


def test_rerun_does_not_leave_stale_energy_files(tmp_path):
    from picstudio.diagnostics.output import Output
    aux=tmp_path/'energy_diagnostics';aux.mkdir()
    stale=aux/'work_block_99999.npz';stale.write_bytes(b'old')
    track=aux/'trajectories_rank0003.csv';track.write_text('old')
    note=aux/'user_notes.txt';note.write_text('keep')
    Output(str(tmp_path)).close()
    assert not stale.exists() and not track.exists()
    assert note.read_text()=='keep'


def test_voltage_source_work_has_correct_sign_and_drift_limit():
    m=model();m['simulation'].update(em_conductors='held at their potentials',smoothing=0,dt='1e-14')
    for side in ('z_min','z_max'):m['boundaries'][side].update(field='periodic',particles='periodic')
    m['boundaries']['y_max']['voltage']='100'
    m['loaders'][0].update(density='1e7',drift=['0','1e7','0'],temperature='0')
    s=Simulation(m,write_output=False,log=lambda _:None)
    for _ in range(30):s.step()
    h=dict(zip(s.energy_diag.names_units(),s.energy_diag.history_values()))
    assert h['ED_W_voltage']>0 and h['ED_W_applied']>0
    np.testing.assert_allclose(h['ED_W_voltage'],h['ED_W_applied'],rtol=1e-3)
    s.energy_diag.close()
