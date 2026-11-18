"""Independent work/charge identities and coupled integration, not output snapshots."""
import copy
import numpy as np
import pytest
from picstudio import constants as C
from picstudio.model import model as M
from picstudio.core.simulation import Simulation
from picstudio.particles import kernels as K
from picstudio.particles.work_centered import orbit_gather, first_absorption, paired_flux
from picstudio.diagnostics.energy import kinetic


def model(diagnostics=True):
    m=M.new_model('2D-ZY','electromagnetic','Work pairing regression')
    m['domain'].update(z_min='0',z_max='.001',nz='8',y_min='0',y_max='.001',ny='8')
    m['simulation'].update(em_coupling='work-centered',smoothing=0,current_filter=0,
        dt='1e-13',n_steps='4',em_conductors='pec only',initial_field='none')
    m['parallel'].update(mode='serial',threads=1)
    m['species']=[dict(name='e',preset='electron')]
    m['diagnostics'].update(energy_enabled=diagnostics,energy_direct_rf=True,
        energy_reference_time='1e-13',energy_track_stride='1',energy_track_every='1')
    return m


def particle(s,z=.0005,y=.0005,u=(1e7,2e7,0.),w=1e6):
    s.species[0].add(*[np.array([x]) for x in [z,y,*u,w]])
    if s.energy_diag:s.energy_diag.initial_KE=s.energy_diag._global_KE()


def history(s):return dict(zip(s.energy_diag.names_units(),s.energy_diag.history_values()))


@pytest.mark.parametrize('periodic',[False,True])
def test_orbit_gather_is_native_scatter_work_dual_including_cell_crossings(periodic):
    m=model();nz=ny=8;dz=dy=.001/8;dt=1e-13
    if periodic:
        for b in m['boundaries'].values():b['field']='periodic'
    s=Simulation(m,write_output=False,log=lambda _:None);g=s.grid
    rng=np.random.default_rng(51)
    x0=rng.uniform(1,6,80);y0=rng.uniform(1,6,80)
    dx=rng.uniform(-.8,.8,80);dy_=rng.uniform(-.8,.8,80)
    if periodic:x0[:4]=[7.8,.1,7.9,.2];y0[:4]=[.1,7.9,7.8,.1]
    dx[-4:]=0.;dy_[-2:]=0.
    x1=x0+dx;y1=y0+dy_
    E=[rng.normal(size=getattr(s.yee,'E'+str(k)).shape) for k in range(3)]
    if periodic:
        E[1][-1]=E[1][0];E[0][:,-1]=E[0][:,0]
        E[2][-1]=E[2][0];E[2][:,-1]=E[2][:,0]
    weights=rng.uniform(.3,2,80);v2=rng.normal(size=80)*1e7
    flux=K.pick(K.esirkepov_2d,80)(np.ascontiguousarray(x0*dz),np.ascontiguousarray(y0*dy),
        np.ascontiguousarray(x1*dz),np.ascontiguousarray(y1*dy),np.zeros(80),np.zeros(80),v2,
        weights,80,-C.e,0.,0.,dz,dy,13,13,2,1,False)
    s.yee.zero_J();s.yee.set_J(*flux,2,dt)
    gathered=orbit_gather(*E,x0,y0,x1,y1,nz,ny,periodic,periodic)
    d=np.array([dx*dz,dy_*dy,v2*dt])
    particle_work=-C.e*np.sum(weights*np.sum(gathered*d,axis=0))
    native=sum(np.sum(getattr(s.yee,'J'+str(k))*E[k]*s.energy_diag.vol[k])*dt for k in range(3))
    np.testing.assert_allclose(particle_work,native,rtol=3e-13,atol=1e-32)
    paired=paired_flux(x0,y0,x1,y1,v2,weights,-C.e,nz,ny,periodic,periodic)
    # New stable formulas must reproduce the existing mathematical scatter;
    # this comparison does not reuse the new gather to define the answer.
    expected=[s.yee.J0*dt*s.yee.Az[None,:],s.yee.J1*dt*s.yee.Ay,s.yee.J2*s.yee.vol]
    for a,b in zip(paired,expected):np.testing.assert_allclose(a,b,rtol=1e-11,atol=1e-32)
    # Independently verify discrete charge continuity at interior/periodic nodes.
    q0=K.deposit_2d.serial(x0*dz,y0*dy,weights,80,-C.e,0.,0.,dz,dy,nz,ny,1)
    q1=K.deposit_2d.serial(x1*dz,y1*dy,weights,80,-C.e,0.,0.,dz,dy,nz,ny,1)
    if not periodic:
        Jz,Jy=s.yee.J0,s.yee.J1
        fluxdiv=np.zeros_like(q0)
        fluxdiv[:-1]+=Jz*g.wr[None,:]*dt;fluxdiv[1:]-=Jz*g.wr[None,:]*dt
        fluxdiv[:,:-1]+=Jy*g.wz[:,None]*dt;fluxdiv[:,1:]-=Jy*g.wz[:,None]*dt
        np.testing.assert_allclose(q1-q0+fluxdiv,0,atol=2e-33)


def test_first_hit_finds_object_crossing_domain_corner_and_periodic_seam():
    obj=np.full((8,8),-1,np.int64);obj[4,3]=7
    x0=np.array([3.5,7.8,7.8]);y0=np.array([3.5,7.8,3.5])
    x1=np.array([4.2,8.2,8.3]);y1=np.array([3.5,8.2,3.5])
    f,flag=first_absorption(x0,y0,x1,y1,obj,8,8,False,False)
    np.testing.assert_allclose(f,[.5/.7,.5,.4]);assert flag.tolist()==[17,4,2]
    obj[0,3]=9
    f,flag=first_absorption(x0[-1:],y0[-1:],x1[-1:],y1[-1:],obj,8,8,True,False)
    assert flag[0]==19;assert f[0]==pytest.approx(.4)


@pytest.mark.parametrize('rel',[False,True])
def test_coupled_grid_particle_work_and_direct_RF_match(rel):
    m=model();m['simulation']['relativistic']=rel
    m['external_fields']=[dict(name='B',type='uniform',B=['0','0','.55'])]
    s=Simulation(m,write_output=False,log=lambda _:None)
    particle(s,u=(2e7,1e7,8e6))
    for _ in range(4):s.step()
    h=history(s)
    assert abs(h['ED_R_particle'])<2e-24
    np.testing.assert_allclose(h['ED_W_push']-h['ED_W_applied'],h['ED_W_grid_particle'],rtol=2e-12,atol=1e-30)
    np.testing.assert_allclose(h['ED_W_rf_direct'],h['ED_W_grid_rf_direct'],rtol=2e-11,atol=1e-30)
    assert abs(h['ED_R_rf_arithmetic'])<1e-29
    reference=s.energy_diag.gather_reference(s.species[0])
    assert reference.shape==(3,s.species[0].n) and np.all(np.isfinite(reference))


def test_tighter_coupling_tolerance_reduces_independent_kinetic_work_residual():
    errors=[];residuals=[]
    for tol in ['1e-7','1e-12']:
        m=model();m['simulation']['coupling_tolerance']=tol
        m['external_fields']=[dict(type='uniform',E=['0','-1e7','0'])]
        s=Simulation(m,write_output=False,log=lambda _:None);particle(s)
        for _ in range(3):s.step()
        errors.append(abs(history(s)['ED_R_particle']))
        residuals.append(s.coupling_residual)
    # The accepted E is the final Maxwell midpoint. Loose nonlinear convergence
    # can differ from the E used in the last trial Cayley rotation.
    assert errors[1]<max(1e-24,errors[0]*.01)
    assert errors[1]<1e-23
    assert residuals[1]<residuals[0]*.01


def test_DC_bias_work_matches_potential_drop_at_fractional_wall_hit(tmp_path):
    m=model();m['simulation']['em_conductors']='held at their potentials'
    m['boundaries']['y_max']['voltage']='1000'
    s=Simulation(m,out_dir=str(tmp_path/'dc'),write_output=True,log=lambda _:None)
    particle(s,y=.001-1e-6,u=(0.,5e7,0.),w=1.)
    expected_drop=1000.-float(s.grid.interp(s.bias_phi,s.species[0].z,s.species[0].y)[0])
    initial_K=s.energy_diag._global_KE();s.step();h=history(s)
    assert s.species[0].n==0
    np.testing.assert_allclose(h['ED_W_applied']/C.e,expected_drop,rtol=1e-10)
    assert abs(h['ED_R_particle'])<2e-26
    impact=h['ED_K_absorbed'];assert abs(impact-initial_K-h['ED_W_push'])<2e-26
    s.energy_diag.close()
    import csv
    rows=list(csv.DictReader((tmp_path/'dc/energy_diagnostics/impacts_rank0000.csv').open()))
    assert 0<float(rows[0]['t'])<s.dt
    assert float(rows[0]['y'])==pytest.approx(.001,abs=1e-15)


def test_newborn_charge_distribution_is_unchanged_and_work_is_counted():
    m=model();m['simulation']['em_conductors']='held at their potentials'
    m['boundaries']['y_max']['voltage']='1000'
    m['emitters']=[dict(name='cathode',species='e',model='scl',z0='0',z1='.001',
        y0='0',y1='0',normal='+y',particles_per_cell='1')]
    s=Simulation(m,write_output=False,log=lambda _:None)
    em=s.emitters[0];one=np.random.default_rng(123);two=np.random.default_rng(123)
    legacy=em.emit(0,s.dt,one,yee=s.yee,static_E=s.F_static,work_centered=False)
    centered=em.emit(0,s.dt,two,yee=s.yee,static_E=s.F_static,work_centered=True)
    np.testing.assert_array_equal(legacy['w'],centered['w'])
    np.testing.assert_allclose(legacy['z_birth'],centered['z_birth'],atol=1e-15)
    np.testing.assert_allclose(legacy['y_birth']-centered['y_birth'],em.eps,atol=1e-18)
    assert one.random()==two.random()
    for _ in range(3):s.step()
    h=history(s)
    assert s.species[0].n>0
    assert abs(h['ED_K_inserted'])<1e-40 # cold cathode; acceleration is work, not insertion energy
    assert abs(h['ED_R_particle'])<1e-21
    np.testing.assert_allclose(h['ED_W_push']-h['ED_W_applied'],h['ED_W_grid_particle'],rtol=1e-10,atol=1e-27)


def test_prescribed_voltage_ramp_is_preserved_and_RF_source_work_is_separate():
    m=model();m['simulation']['em_conductors']='held at their potentials'
    m['boundaries']['y_max']['voltage']='1e15*t'
    s=Simulation(m,write_output=False,log=lambda _:None);particle(s)
    for _ in range(4):s.step()
    h=history(s)
    assert h['ED_W_applied_rf']>0
    assert abs(h['ED_R_exchange'])<1e-25
    assert abs(h['ED_R_rf_exchange'])<1e-25
    raw=h['ED_W_rf_direct']-h['ED_W_grid_rf_direct']
    np.testing.assert_allclose(raw,-h['ED_W_applied_rf'],rtol=1e-12,atol=1e-29)
    # The ramp is evaluated at the actual new time, rather than frozen/replaced.
    assert s.voltages(s.t)[s.mats.conductors.index(next(c for c in s.mats.conductors if c['voltage']=='1e15*t'))]==pytest.approx(400.)


@pytest.mark.parametrize('upper',[False,True])
def test_surface_births_preserve_free_node_Gauss_law_without_offset_charge(upper):
    m=model();m['simulation']['em_conductors']='held at their potentials'
    m['boundaries']['y_max']['voltage']='-1000' if upper else '1000'
    m['emitters']=[dict(name='cathode',species='e',model='scl',z0='0',z1='.001',
        y0='.001' if upper else '0',y1='.001' if upper else '0',normal='-y' if upper else '+y',particles_per_cell='1')]
    s=Simulation(m,write_output=False,log=lambda _:None)
    for _ in range(3):s.step()
    sp=s.species[0];assert sp.n>0
    assert np.all((sp.y>0)&(sp.y<.001))
    g=s.grid;y=s.yee
    q=K.deposit_2d.serial(sp.z,sp.y,sp.w,sp.n,sp.q,0.,0.,g.dz,g.dy,g.nz,g.ny,1)
    div=np.zeros_like(q)
    div[:-1]+=C.eps0*y.E0*y.Az[None,:];div[1:]-=C.eps0*y.E0*y.Az[None,:]
    div[:,:-1]+=C.eps0*y.E1*y.Ay;div[:,1:]-=C.eps0*y.E1*y.Ay
    free=s.mats.node_cond<0
    np.testing.assert_allclose(div[free],q[free],atol=max(1e-30,float(np.max(abs(q)))*1e-10),rtol=1e-10)


def test_diagnostics_do_not_change_work_centered_solution():
    a=Simulation(model(False),write_output=False,log=lambda _:None)
    b=Simulation(model(True),write_output=False,log=lambda _:None)
    particle(a);particle(b)
    for _ in range(3):a.step();b.step()
    for x,y in zip(a.species[0].arrays(),b.species[0].arrays()):np.testing.assert_array_equal(x,y)
    for k in ('E0','E1','E2','B0','B1','B2'):np.testing.assert_array_equal(getattr(a.yee,k),getattr(b.yee,k))


@pytest.mark.parametrize('change',[dict(smoothing=1),dict(current_filter=1),dict(field_gathering='momentum-conserving'),
    dict(geometry='2D-RZ'),dict(coupling_tolerance='0'),dict(coupling_iterations=1)])
def test_invalid_combinations_reject_before_output_cleanup(tmp_path,change):
    m=model();m['simulation'].update(change)
    out=tmp_path/'existing';out.mkdir();sentinel=out/'history.csv';sentinel.write_text('keep original')
    assert any(level=='error' for level,_ in M.validate(m))
    with pytest.raises(ValueError):Simulation(m,out_dir=str(out),write_output=True,log=lambda _:None)
    assert sentinel.read_text()=='keep original'


def test_nonconverged_step_stops_and_restores_old_field_and_particle_state():
    m=model();m['simulation'].update(coupling_iterations=2,coupling_tolerance='1e-14')
    s=Simulation(m,write_output=False,log=lambda _:None);particle(s)
    old=[a.copy() for a in s.species[0].arrays()];fields=[s.yee.E0.copy(),s.yee.B2.copy()]
    with pytest.raises(RuntimeError,match='reduce dt'):s.step()
    for x,y in zip(old,s.species[0].arrays()):np.testing.assert_array_equal(x,y)
    np.testing.assert_array_equal(fields[0],s.yee.E0);np.testing.assert_array_equal(fields[1],s.yee.B2)
    assert s.t==0
    with pytest.raises(RuntimeError,match='new Simulation'):s.step()


def test_absent_new_setting_preserves_legacy_solution():
    m=model(False);m['simulation']['em_coupling']='legacy'
    old=copy.deepcopy(m);del old['simulation']['em_coupling']
    a=Simulation(m,write_output=False,log=lambda _:None)
    b=Simulation(old,write_output=False,log=lambda _:None)
    particle(a);particle(b)
    for _ in range(2):a.step();b.step()
    for x,y in zip(a.species[0].arrays(),b.species[0].arrays()):np.testing.assert_array_equal(x,y)


def test_uniform_crossed_field_orbit_converges_to_independent_analytic_solution():
    duration=2e-12;Ey=-1e7;Bx=.55;errors=[]
    for steps in [20,40]:
        m=model(False);m['simulation'].update(relativistic=False,dt=str(duration/steps))
        m['external_fields']=[dict(type='uniform',E=['0',str(Ey),'0'],B=['0','0',str(Bx)])]
        s=Simulation(m,write_output=False,log=lambda _:None);particle(s,u=(0.,0.,0.),w=1e-20)
        for _ in range(steps):s.step()
        sp=s.species[0];omega=sp.qm*Bx
        exact=np.array([Ey/Bx*(np.cos(omega*duration)-1),Ey/Bx*np.sin(omega*duration)])
        errors.append(float(np.linalg.norm(np.array([sp.u0[0],sp.u1[0]])-exact)))
    assert 3.8<errors[0]/errors[1]<4.2 # second-order physical orbit, independent of budget formulas
