"""Run explicitly: mpiexec -n 2 python tests/mpi_energy_diagnostics.py.

No output folder is opened. Checks MPI bookkeeping and passive measurements.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from mpi4py import MPI
from picstudio.core.simulation import Simulation
from picstudio.model import model as M
from picstudio.diagnostics.energy import kinetic


def model(enabled):
    m=M.new_model('2D-ZY','electromagnetic')
    m['domain'].update(z_max='.001',y_max='.001',nz='8',ny='8')
    m['parallel'].update(mode='mpi',threads=1)
    m['simulation'].update(dt='1e-13',n_steps='3',em_conductors='pec only')
    m['species']=[dict(name='e',preset='electron')]
    m['diagnostics'].update(energy_enabled=enabled,energy_reference_time='1e-13',energy_block_time='1e-13')
    return m


def check():
    assert MPI.COMM_WORLD.Get_size()==2, 'Launch with exactly two MPI ranks'
    for enabled in (False,True):
        s=Simulation(model(enabled),write_output=False,log=lambda _:None)
        if s.rank==0:
            a=np.ones(1);s.species[0].add(a*.0005,a*.0005,a*1e7,a*2e7,a*0,a*1e5)
        if enabled:s.energy_diag.initial_KE=s.energy_diag._global_KE()
        for _ in range(3):
            s.step()
            for k in ('E0','E1','E2','B0','B1','B2','J0','J1','J2'):
                arrays=MPI.COMM_WORLD.allgather(getattr(s.yee,k))
                np.testing.assert_array_equal(arrays[0],arrays[1],err_msg=k)
        if enabled:s.energy_diag.close()
    s=Simulation(model(True),write_output=False,log=lambda _:None)
    sp=s.species[0];a=np.ones(1);sp.add(a*.0005,a*.0009999,a*0,a*1e7,a*0,a*(s.rank+1))
    s.energy_diag.initial_KE=s.energy_diag._global_KE()
    ids=MPI.COMM_WORLD.allgather(int(sp._diagnostic_arrays['id'][0]));assert len(set(ids))==2
    for _ in range(3):s.step()
    h=dict(zip(s.energy_diag.names_units(),s.energy_diag.history_values()))
    expected=float(kinetic(np.array([[0.],[1e7],[0.]]),sp.m,True)[0])*3
    np.testing.assert_allclose(h['ED_K_surface_3'],expected,rtol=1e-12)
    np.testing.assert_allclose(h['ED_U_electric'],s.energy_diag.field_energy()[0],rtol=1e-14)
    assert abs(h['ED_R_particle'])<1e-29
    s.energy_diag.close()
    # Only the enabled object's compact current accumulator is MPI-reduced.
    m=model(False)
    m['objects']=[dict(name=f'object{i}',shape='rectangle',material='conductor',
                       z0='.0006',z1='.0007',y0='.0002',y1='.0008',
                       record_current=i==1,record_voltage=i==1) for i in range(3)]
    s=Simulation(m,write_output=False,log=lambda _:None);sp=s.species[0]
    a=np.ones(3);sp.add(a*.0005,a*.0005,a*0,a*0,a*0,np.array([1.,2.,3.])*(s.rank+1))
    s._account(sp,np.array([10,11,12],dtype=np.int32));s.t=s.dt
    cols=s.history_columns();row=s.history_row()
    assert 'I_object0' not in cols and 'V_object2' not in cols
    assert s.coll_obj.size==1 and len(cols)==len(row)==len(s.history_units())
    np.testing.assert_allclose(row[cols.index('I_object1')],sp.q*6/s.dt,rtol=1e-14)
    if s.rank==0:print('Passed: empty-rank current updates, unique IDs, global impact energy and replicated-field accounting.')


if __name__=='__main__':check()
