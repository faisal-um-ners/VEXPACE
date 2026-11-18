"""Launch with two MPI ranks; tests empty-rank collectives and serial equivalence."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from mpi4py import MPI
from picstudio.core.simulation import Simulation
from picstudio.core.parallel import SerialComm
from picstudio.model import model as M


def model():
    m=M.new_model('2D-ZY','electromagnetic')
    m['domain'].update(z_max='.001',y_max='.001',nz='8',ny='8')
    m['simulation'].update(em_coupling='work-centered',smoothing=0,current_filter=0,
        dt='1e-13',n_steps='3',em_conductors='pec only',initial_field='none')
    m['species']=[dict(name='e',preset='electron')]
    m['parallel'].update(mode='serial',threads=1)
    m['diagnostics'].update(energy_enabled=True,energy_direct_rf=True,energy_reference_time='1e-13')
    return m


def add(s):
    a=np.ones(2);s.species[0].add(a*.0005,np.array([.0005,.0009995]),a*1e7,a*2e7,a*3e6,a*1e5)


def main():
    assert MPI.COMM_WORLD.size==2
    m=model();m['parallel']['mode']='mpi'
    parallel=Simulation(m,write_output=False,log=lambda _:None)
    serial=Simulation(model(),comm=SerialComm(),write_output=False,log=lambda _:None)
    add(serial)
    if parallel.rank==0:add(parallel) # second rank remains empty, including after impact
    for s in [serial,parallel]:s.energy_diag.initial_KE=s.energy_diag._global_KE()
    for _ in range(4):
        serial.step();parallel.step()
        for k in ('E0','E1','E2','B0','B1','B2','J0','J1','J2'):
            np.testing.assert_allclose(getattr(parallel.yee,k),getattr(serial.yee,k),rtol=2e-13,atol=1e-30)
        if parallel.rank==0:
            for a,b in zip(parallel.species[0].arrays(),serial.species[0].arrays()):
                np.testing.assert_allclose(a,b,rtol=2e-13,atol=1e-30)
    ph=dict(zip(parallel.energy_diag.names_units(),parallel.energy_diag.history_values()))
    sh=dict(zip(serial.energy_diag.names_units(),serial.energy_diag.history_values()))
    for k in ['ED_W_push','ED_W_applied','ED_W_grid_particle','ED_K_absorbed','ED_W_rf_direct']:
        np.testing.assert_allclose(ph[k],sh[k],rtol=2e-12,atol=1e-29)
    assert abs(ph['ED_R_exchange'])<1e-28
    assert abs(ph['ED_R_rf_exchange'])<1e-28
    # Emission panels/RNG streams are rank-decomposed: trajectories need not
    # equal a serial random realization, but the global work identity must.
    m=model();m['parallel']['mode']='mpi';m['simulation']['em_conductors']='held at their potentials'
    m['boundaries']['y_max']['voltage']='1000'
    m['emitters']=[dict(name='cathode',species='e',model='scl',z0='0',z1='.001',y0='0',y1='0',normal='+y',particles_per_cell='1')]
    emitted=Simulation(m,write_output=False,log=lambda _:None)
    for _ in range(4):emitted.step()
    eh=dict(zip(emitted.energy_diag.names_units(),emitted.energy_diag.history_values()))
    scale=max(abs(eh['ED_W_push']),abs(eh['ED_W_applied']),1e-30)
    assert abs(eh['ED_R_exchange'])/scale<1e-10
    assert abs(eh['ED_R_particle'])/scale<1e-9
    for k in ('E0','E1','E2'):
        copies=MPI.COMM_WORLD.allgather(getattr(emitted.yee,k))
        np.testing.assert_array_equal(copies[0],copies[1])
    if parallel.rank==0: print('Passed: work-centered serial/MPI equivalence, empty rank, fractional impact, RF exchange and global SCL birth work.')


if __name__=='__main__':main()
