"""Passive energy diagnostics for Cartesian 2D electromagnetic Boris runs.

Particle work follows the selected numerical update: the unchanged Boris
electric kicks in legacy mode, or the actual work-centered orbit residence.
The frozen mean field is a diagnostic reference, never a force imposed on the
simulation. Source/control work and numerical residuals remain separate.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .. import constants as C
from ..particles import kernels as K
from .direct_rf import direct_rf_boris_work


def kinetic(u, mass, relativistic=True):
    uu = np.sum(np.asarray(u)**2, axis=0)
    # Stable even for slow particles (avoid subtracting gamma - 1).
    return mass*uu/(np.sqrt(1.+uu/C.c**2)+1.) if relativistic else .5*mass*uu


def boris_work(u_before, u_after, electric, dc, qm, dt, mass, relativistic=True):
    """Per-physical-particle work, consistent with the two electric kicks.

    Returns total electric work on particles, mean-field work on particles,
    and fluctuating-field work delivered BY particles. No trajectory is changed.
    """
    h = .5*qm*dt
    um, up = u_before+h*electric, u_after-h*electric
    if relativistic:
        gamma = lambda u: np.sqrt(1.+np.sum(u*u, axis=0)/C.c**2)
        v1 = (u_before+um)/(gamma(u_before)+gamma(um))
        v2 = (up+u_after)/(gamma(up)+gamma(u_after))
    else:
        v1, v2 = .5*(u_before+um), .5*(up+u_after)
    displacement = .5*dt*(v1+v2)
    total = mass*qm*np.sum(electric*displacement, axis=0)
    mean = mass*qm*np.sum(dc*displacement, axis=0) if dc is not None else np.zeros_like(total)
    return total, mean, -(total-mean)


class EnergyDiagnostics:
    def __init__(self, sim, write_output=True):
        self.s = sim
        self.validate(sim.model)
        d, ev = sim.model['diagnostics'], sim.ev
        self.direct_rf = bool(d.get('energy_direct_rf', False))
        self.push_trace = bool(d.get('energy_rf_push_trace', False))
        self.push_records = []
        self.push_record_count = 0
        self.push_trace_index = 0
        self.push_positions = {}
        self.start = ev.num(d['energy_start'])
        self.reference_time = ev.num(d['energy_reference_time'])
        self.block_time = ev.num(d['energy_block_time'])
        self.track_every = int(ev.num(d['energy_track_every']))
        self.track_stride = int(ev.num(d['energy_track_stride']))
        self.hub_y = ev.num(d['energy_hub_y']) if str(d['energy_hub_y']).strip() else None
        self.bins = int(ev.num(d['energy_hist_bins']))
        self.max_eV = ev.num(d['energy_hist_max_eV'])
        self.reference_ready = False
        self.reference_count = 0
        self.reference_started = None
        self.reference_finished = None
        self.node_mean = np.zeros((6,)+sim.grid.shape)
        self.native_mean = [np.zeros_like(getattr(sim.yee, 'E'+str(k))) for k in range(3)]
        self.bias_mean = [np.zeros_like(a) for a in self.native_mean]
        self.zero_B = [np.zeros_like(getattr(sim.yee, 'B'+str(k))) for k in range(3)]
        self.surface_names = ['boundary:'+k for k in ('z_min','z_max','y_min','y_max')]
        self.surface_names += ['object:'+str(i)+':'+n for i,n in enumerate(sim.obj_names)]
        self.nsurf = len(self.surface_names)
        # Local particle quantities are MPI-reduced only when read; grid data
        # are already replicated/allreduced by the solver and must not be summed.
        self.local = dict(push=0., applied=0., dc=0., rf=0., classified=0., inserted=0.)
        if sim.work_centered:self.local['applied_rf']=0.
        self.surfaces = np.zeros((self.nsurf, 3))  # count, charge, KE
        self.hist = np.zeros((self.nsurf, self.bins+1))  # last bin = overflow
        self.grid = dict(particle=0., antenna=0., load=0., load_rf=0., absorber=0., control=0., voltage=0.)
        if self.direct_rf:
            self.local['rf_direct'] = 0.
            self.grid['rf_direct'] = 0.
        self.rf_surfaces = np.zeros((self.nsurf, 2))  # classified RF work, represented count
        self.ref_grid0 = None
        self.last_history = None
        self.previous_power = {}
        self.previous_time = sim.t
        self.vol = self._volumes()
        self.load_rate = self._load_rates()
        self.particle_J = [np.zeros_like(getattr(sim.yee, 'J'+str(k))) for k in range(3)]
        self.old_E = None
        self.aux = Path(sim.out_dir)/'energy_diagnostics'
        self.writing = bool(write_output)
        self.handles = []
        self.track_writer = self.cross_writer = self.event_writer = None
        self.block_elapsed = 0.
        self.block_index = 0
        self.sum_E = [np.zeros_like(v) for v in self.native_mean]
        self.sum_J = [np.zeros_like(v) for v in self.native_mean]
        self.sum_JE = 0.
        self.initial_KE = self._global_KE()
        self.initial_field = sum(self.field_energy())
        for sp in sim.species:
            sp.enable_energy_tracking(sim.rank, direct_rf=self.direct_rf)
        if self.writing:
            sim.comm.barrier()  # rank 0 finishes Output's old-run cleanup first
            self.aux.mkdir(parents=True, exist_ok=True)
            self.track_writer = self._writer(f'trajectories_rank{sim.rank:04d}.csv',
                ['step','t','species','id','weight','z','y','u0','u1','u2','K_J','W_total_J','W_dc_J','W_rf_J','reference_ready'] + self._direct_columns())
            self.event_writer = self._writer(f'impacts_rank{sim.rank:04d}.csv',
                ['step','t','species','id','surface','weight','z','y','K_J','W_total_J','W_dc_J','W_rf_J','reference_ready'] + self._direct_columns() + (['z_before','y_before','z_after_unclipped','y_after_unclipped'] if self.direct_rf else []))
            self.cross_writer = self._writer(f'hub_crossings_rank{sim.rank:04d}.csv',
                ['step','t_linear','species','id','direction','weight','z_linear','y','K_J_linear','W_total_J_linear','W_dc_J_linear','W_rf_J_linear','reference_ready'] + (['W_rf_direct_J_linear','W_rf_direct_before_J','W_rf_direct_after_J','rf_valid_since','t_before','dt','fraction','z_before','y_before','z_after_unclipped','y_after_unclipped'] if self.direct_rf else []))
            if sim.rank == 0:
                self.surface_writer = self._writer('surface_energy.csv',
                    ['step','t','surface','macro_count','charge_C_per_m','KE_J_per_m','P_impact_W_per_m'] + (['W_rf_direct_J_per_m','RF_classified_particles_per_m'] if self.direct_rf else []))
                self.block_writer = self._writer('work_blocks.csv',
                    ['block','t_end','duration','P_grid_DC_to_particles_W_per_m','P_grid_fluct_to_fields_W_per_m'])
                self.write_metadata()

    @staticmethod
    def validate(model):
        d, sim = model['diagnostics'], model['simulation']
        if d.get('energy_rf_push_trace', False) and not d.get('energy_direct_rf', False):
            raise ValueError('Per-push RF traces require Direct RF work every particle push')
        if sim['geometry'] != '2D-ZY' or sim['solver'] != 'electromagnetic':
            raise ValueError('Energy diagnostics currently require 2D-ZY electromagnetic geometry')
        if ((sim.get('em_coupling','legacy') != 'work-centered' and sim.get('particle_pusher', 'boris') != 'boris')
                or any(s.get('motion','full') != 'full' for s in model['species'])):
            raise ValueError('Energy diagnostics require Boris and full particle motion')
        from ..model.model import evaluator
        ev = evaluator(model)
        for key in ('energy_reference_time','energy_block_time','energy_track_every','energy_track_stride','energy_hist_bins','energy_hist_max_eV'):
            v = ev.num(d[key])
            if not np.isfinite(v) or v <= 0:
                raise ValueError(key+' must be finite and positive')
            if key in ('energy_track_every','energy_track_stride','energy_hist_bins') and v != int(v):
                raise ValueError(key+' must be an integer')
        if not np.isfinite(ev.num(d['energy_start'])) or ev.num(d['energy_start']) < 0:
            raise ValueError('Energy diagnostic start time must be finite and nonnegative')
        if str(d['energy_hub_y']).strip():
            y = ev.num(d['energy_hub_y'])
            if not ev.num(model['domain']['y_min']) < y < ev.num(model['domain']['y_max']):
                raise ValueError('Diagnostic hub plane must lie inside the domain')

    def _writer(self, name, columns):
        fh = (self.aux/name).open('w', newline='', encoding='utf-8')
        self.handles.append(fh)
        writer = csv.writer(fh);writer.writerow(columns)
        return writer

    def _volumes(self):
        g = self.s.grid
        return [np.broadcast_to(g.dz*g.wr[None,:], self.s.yee.E0.shape).copy(),
                np.broadcast_to(g.wz[:,None]*g.dy, self.s.yee.E1.shape).copy(),g.node_volume.copy()]

    def _load_rates(self):
        y, sig, ec = self.s.yee, self.s.mats.sigma_cell, self.s.mats.eps_cell
        p = np.pad(sig/(C.eps0*ec),1)
        return [.5*(p[1:-1,:-1]+p[1:-1,1:]), .5*(p[:-1,1:-1]+p[1:,1:-1]),
                .25*(p[:-1,:-1]+p[1:,:-1]+p[:-1,1:]+p[1:,1:])]

    def field_energy(self):
        y,g=self.s.yee,self.s.grid
        ue = sum(.5*C.eps0*np.sum(getattr(y,'er'+str(k))*getattr(y,'E'+str(k))**2*self.vol[k]) for k in range(3))
        ub = .5/C.mu0*(np.sum(y.B0**2*self.vol[1])+np.sum(y.B1**2*self.vol[0])+np.sum(y.B2**2)*g.dz*g.dy)
        return float(ue),float(ub)

    def _global_KE(self):
        local = sum(float(np.dot(sp.w, kinetic(np.array([sp.u0,sp.u1,sp.u2]),sp.m,self.s.rel))) for sp in self.s.species)
        return self.s.comm.allsum(local)

    def begin_step(self):
        s=self.s
        if s.work_centered:return  # accumulate actual converged midpoint fields instead
        if s.t >= self.start and not self.reference_ready:
            if self.reference_started is None:self.reference_started=s.t
            self.reference_count+=1
            self.node_mean += s.F_gather if s.gather_ec else s.F
            for k in range(3):self.native_mean[k] += getattr(s.yee,'E'+str(k))

    def centered_reference(self,native,bias):
        s=self.s
        if s.t<self.start or self.reference_ready:return
        if self.reference_started is None:self.reference_started=s.t
        self.reference_count+=1
        for a,b,c,d in zip(self.native_mean,self.bias_mean,native,bias):a+=c;b+=d

    def finish_step(self):
        s=self.s
        if (not self.reference_ready and self.reference_started is not None
                and self.reference_count*s.dt >= self.reference_time*(1.-1e-12)):
            self.node_mean /= self.reference_count
            for a in self.native_mean:a /= self.reference_count
            if s.work_centered:
                for a in self.bias_mean:a/=self.reference_count
                from ..fields.fdtd import _avg_half_to_node
                combined=[a+b for a,b in zip(self.native_mean,self.bias_mean)]
                self.node_mean[0]=_avg_half_to_node(combined[0],0,s.pz)
                self.node_mean[1]=_avg_half_to_node(combined[1],1,s.py)
                self.node_mean[2]=combined[2]
                external=s.ext.nodal(s.t)
                if external is not None:self.node_mean+=external
            self.reference_ready=True;self.reference_finished=s.t
            self.ref_grid0=self.grid.copy()
            if self.writing and s.rank==0:
                extra={f'bias_E{k}':a for k,a in enumerate(self.bias_mean)} if s.work_centered else {}
                np.savez_compressed(self.aux/'dc_reference.npz',node_fields=self.node_mean,
                                    E0=self.native_mean[0],E1=self.native_mean[1],E2=self.native_mean[2],
                                    t_start=self.reference_started,t_end=s.t,z=s.grid.z,y=s.grid.y,
                                    gather_energy_conserving=s.gather_ec,**extra)
                self.write_metadata()
            if self.direct_rf:
                for sp in s.species:
                    sp._diagnostic_arrays['rf_valid_since'][:sp.n] = s.t
        if self.writing and s.step_count % self.track_every==0:
            for sp in s.species:self.write_tracks(sp)

    def gather_reference(self, sp):
        if not self.reference_ready:return None
        s,g=self.s,self.s.grid
        if s.work_centered:
            from ..core.work_centered import gather
            out=gather(s,[a+b for a,b in zip(self.native_mean,self.bias_mean)],sp.z,sp.y,sp.z,sp.y)
            external=s.ext.nodal(s.t)
            if external is not None:out+=external[:3,0,0,None]
            return out
        zl,yl=np.ascontiguousarray(g.lz(sp.z)),np.ascontiguousarray(g.ly(sp.y))
        out=np.empty((6,sp.n))
        K.gather_nodal_2d(self.node_mean,zl,yl,sp.n,g.nz,g.ny,out)
        if s.gather_ec:
            K.gather_ec_yee_2d(*self.native_mean,*self.zero_B,zl,yl,sp.n,g.nz,g.ny,out)
        return out[:3]

    def applied_at(self, sp):
        s=self.s
        if s.work_centered:
            from ..core.work_centered import gather,bias_fields
            out=gather(s,bias_fields(s,s.t+.5*s.dt),sp.z,sp.y,sp.z,sp.y)
            external=s.ext.nodal(s.t)
            if external is not None:out+=external[:3,0,0,None]
            return out
        fields=np.zeros_like(s.F)
        if s.static_E is not None:
            for k,a in enumerate(s.static_E):fields[k]+=a
        ext=s.ext.nodal(s.t)
        if ext is not None:fields[:3]+=ext[:3]
        out=np.empty((6,sp.n))
        K.gather_nodal_2d(fields,np.ascontiguousarray(s.grid.lz(sp.z)),np.ascontiguousarray(s.grid.ly(sp.y)),sp.n,s.grid.nz,s.grid.ny,out)
        return out[:3]

    def pushed(self, sp, old_u, old_z, old_y, fields, ref, applied,
               work_displacement=None, durations=None, start_times=None,reference_applied=None):
        s=self.s
        u=np.array([sp.u0,sp.u1,sp.u2])
        if work_displacement is None:
            total,dc,rf=boris_work(old_u,u,fields[:3],ref,sp.qm,s.dt,sp.m,s.rel)
            _,wa,_=boris_work(old_u,u,fields[:3],applied,sp.qm,s.dt,sp.m,s.rel)
        else:
            total=sp.q*np.sum(fields[:3]*work_displacement,axis=0)
            dc=sp.q*np.sum(ref*work_displacement,axis=0) if ref is not None else np.zeros_like(total)
            rf=-(total-dc)
            wa=sp.q*np.sum(applied*work_displacement,axis=0)
            if reference_applied is not None:
                self.local['applied_rf']+=float(np.dot(sp.w,sp.q*np.sum((applied-reference_applied)*work_displacement,axis=0)))
        self.local['push']+=float(np.dot(sp.w,total))
        self.local['applied']+=float(np.dot(sp.w,wa))
        a=sp._diagnostic_arrays
        previous={k:a[k][:sp.n].copy() for k in ('work_total','work_dc','work_rf')} if self.hub_y is not None else None
        direct = None
        direct_before = None
        if self.direct_rf:
            self.push_positions[sp.name] = (old_z, old_y, sp.z.copy(), sp.y.copy())
            if ref is not None:
                direct_before = a['work_rf_direct'][:sp.n].copy() if self.hub_y is not None else None
                if work_displacement is None:
                    direct = direct_rf_boris_work(old_u, u, fields[:3], ref, sp.q, sp.m, s.dt, s.rel)
                else:
                    # Direct orbit-field dot product, independently of K or DC-work subtraction.
                    components=-sp.q*(fields[:3]-ref)*work_displacement
                    direct=dict(rf_direct_J=np.sum(components,axis=0),
                                rf_direct_components_J=components,E_rf_V_per_m=fields[:3]-ref,
                                boris_displacement_m=work_displacement)
                missing = np.isnan(a['rf_valid_since'][:sp.n])
                a['rf_valid_since'][:sp.n][missing] = (s.t if start_times is None else start_times[missing])
                a['work_rf_direct'][:sp.n] += direct['rf_direct_J']
                self.local['rf_direct'] += float(np.dot(sp.w, direct['rf_direct_J']))
                if self.writing and self.push_trace:
                    self._record_push(sp, old_u, u, old_z, old_y, fields[:3], ref, direct,
                                      durations=durations,start_times=start_times)
        a['work_total'][:sp.n]+=total
        if ref is not None:
            self.local['dc']+=float(np.dot(sp.w,dc));self.local['rf']+=float(np.dot(sp.w,rf))
            self.local['classified']+=float(np.dot(sp.w,total))
            a['work_dc'][:sp.n]+=dc;a['work_rf'][:sp.n]+=rf
        if self.hub_y is not None and self.writing:
            cross=(old_y-self.hub_y)*(sp.y-self.hub_y)<0
            selected=self.selected(sp)&cross
            K0,K1=kinetic(old_u,sp.m,s.rel),kinetic(u,sp.m,s.rel)
            for i in np.flatnonzero(selected):
                f=(self.hub_y-old_y[i])/(sp.y[i]-old_y[i])
                vals=[previous[k][i]+f*(a[k][i]-previous[k][i]) for k in ('work_total','work_dc','work_rf')]
                if not self.reference_ready:vals[1:]=[np.nan,np.nan]
                extra = []
                if self.direct_rf:
                    before = direct_before[i] if direct_before is not None else np.nan
                    after = a['work_rf_direct'][i] if ref is not None else np.nan
                    extra = [before+f*(after-before),before,after,a['rf_valid_since'][i],s.t if start_times is None else start_times[i],s.dt if durations is None else durations[i],f,old_z[i],old_y[i],sp.z[i],sp.y[i]]
                cross_time=s.t+f*s.dt if durations is None else start_times[i]+f*durations[i]
                self.cross_writer.writerow([s.step_count+1,cross_time,sp.name,int(a['id'][i]),int(np.sign(sp.y[i]-old_y[i])),sp.w[i],old_z[i]+f*(sp.z[i]-old_z[i]),self.hub_y,K0[i]+f*(K1[i]-K0[i]),*vals,int(self.reference_ready),*extra])

    def _direct_columns(self):
        return ['W_rf_direct_J', 'rf_valid_since'] if self.direct_rf else []

    def _direct_values(self, sp, i):
        if not self.direct_rf:
            return []
        a = sp._diagnostic_arrays
        valid = self.reference_ready and np.isfinite(a['rf_valid_since'][i])
        return [a['work_rf_direct'][i] if valid else np.nan, a['rf_valid_since'][i]]

    def _record_push(self, sp, old_u, new_u, old_z, old_y, E, ref, direct,
                     durations=None,start_times=None):
        pick = self.selected(sp)
        n = int(np.count_nonzero(pick))
        if not n:
            return
        s, a = self.s, sp._diagnostic_arrays
        record = dict(id=a['id'][:sp.n][pick].copy(), species_index=np.full(n,sp.index,dtype=np.int32),
            step=np.full(n,s.step_count+1,dtype=np.int64),
            t_before=np.full(n,s.t) if start_times is None else start_times[pick].copy(),
            dt=np.full(n,s.dt) if durations is None else durations[pick].copy(),
            weight=sp.w[pick].copy(),charge_C=np.full(n,sp.q),mass_kg=np.full(n,sp.m),
            position_before=np.column_stack([old_z[pick],old_y[pick]]),
            position_after_unclipped=np.column_stack([sp.z[pick],sp.y[pick]]),
            u_before=old_u[:,pick].T.copy(),u_after=new_u[:,pick].T.copy(),
            E_gathered=E[:,pick].T.copy(),E_DC_gathered=ref[:,pick].T.copy(),
            d_Boris=direct['boris_displacement_m'][:,pick].T.copy(),
            d_work=direct['boris_displacement_m'][:,pick].T.copy(),
            delta_W_rf_direct_J=direct['rf_direct_J'][pick].copy(),
            W_rf_direct_J=a['work_rf_direct'][:sp.n][pick].copy(),
            rf_valid_since=a['rf_valid_since'][:sp.n][pick].copy())
        self.push_records.append(record)
        if s.work_centered:
            record['d_Boris'][:]=np.nan  # explicitly not a Boris push in this mode
        self.push_record_count += n
        if self.push_record_count >= 8192:
            self._flush_push_trace()

    def _flush_push_trace(self):
        if not self.push_records:
            return
        data = {k:np.concatenate([r[k] for r in self.push_records]) for k in self.push_records[0]}
        path = self.aux/f'rf_push_rank{self.s.rank:04d}_{self.push_trace_index:05d}.npz'
        np.savez_compressed(path,**data)
        self.push_trace_index += 1
        self.push_records.clear()
        self.push_record_count = 0

    def selected(self,sp):
        ids=sp._diagnostic_arrays['id'][:sp.n]
        # Select on rank-local sequence, retaining every selected ID for life.
        return (ids & np.uint64((1<<40)-1)) % self.track_stride == 0

    def write_tracks(self,sp):
        kk=kinetic(np.array([sp.u0,sp.u1,sp.u2]),sp.m,self.s.rel);a=sp._diagnostic_arrays
        for i in np.flatnonzero(self.selected(sp)):
            dc,rf=(a['work_dc'][i],a['work_rf'][i]) if self.reference_ready else (np.nan,np.nan)
            self.track_writer.writerow([self.s.step_count,self.s.t,sp.name,int(a['id'][i]),sp.w[i],sp.z[i],sp.y[i],sp.u0[i],sp.u1[i],sp.u2[i],kk[i],a['work_total'][i],dc,rf,int(self.reference_ready),*self._direct_values(sp,i)])

    def inserted(self,sp,out):
        self.local['inserted']+=float(np.dot(out['w'],kinetic(np.array([out['u0'],out['u1'],out['u2']]),sp.m,self.s.rel)))

    def impact(self,sp,flag):
        hit=flag!=0
        if not hit.any():return
        kk=kinetic(np.array([sp.u0,sp.u1,sp.u2]),sp.m,self.s.rel)
        indices=np.where(flag<10,flag-1,4+flag-10)
        for j in np.unique(indices[hit]):
            pick=hit&(indices==j);self.surfaces[j]+=[pick.sum(),sp.q*sp.w[pick].sum(),np.dot(sp.w[pick],kk[pick])]
            bucket=np.minimum((kk[pick]/C.e/self.max_eV*self.bins).astype(int),self.bins)
            self.hist[j]+=np.bincount(bucket,weights=sp.w[pick],minlength=self.bins+1)
            if self.direct_rf and self.reference_ready:
                a = sp._diagnostic_arrays
                classified = pick & np.isfinite(a['rf_valid_since'][:sp.n])
                self.rf_surfaces[j] += [np.dot(sp.w[classified],a['work_rf_direct'][:sp.n][classified]),sp.w[classified].sum()]
        if self.writing:
            a=sp._diagnostic_arrays
            for i in np.flatnonzero(hit&self.selected(sp)):
                dc,rf=(a['work_dc'][i],a['work_rf'][i]) if self.reference_ready else (np.nan,np.nan)
                positions = []
                if self.direct_rf:
                    positions = [v[i] for v in self.push_positions.get(sp.name,(sp.z,sp.y,sp.z,sp.y))]
                times=getattr(self.s,'_impact_times',{}).get(sp.name)
                impact_time=self.s.t+self.s.dt if times is None else times[i]
                self.event_writer.writerow([self.s.step_count+1,impact_time,sp.name,int(a['id'][i]),self.surface_names[indices[i]],sp.w[i],sp.z[i],sp.y[i],kk[i],a['work_total'][i],dc,rf,int(self.reference_ready),*self._direct_values(sp,i),*positions])

    def before_B(self):
        self.old_B=[getattr(self.s.yee,'B'+str(k)).copy() for k in range(3)]

    def after_B(self):
        y=self.s.yee;vol=[self.vol[1],self.vol[0],np.full_like(y.B2,self.s.grid.dz*self.s.grid.dy)]
        self.grid['absorber']+=sum(float(.5*self.s.dt/C.mu0*np.sum(getattr(y,'sB'+str(k))*(.5*(self.old_B[k]+getattr(y,'B'+str(k))))**2*vol[k])) for k in range(3))

    def record_particle_current(self):
        self.particle_J=[getattr(self.s.yee,'J'+str(k)).copy() for k in range(3)]
        if self.s.j_filter:
            from types import SimpleNamespace
            from ..fields.fdtd import filter_current
            proxy=SimpleNamespace(**{'J'+str(k):v for k,v in enumerate(self.particle_J)})
            filter_current(proxy,self.s.j_filter,(self.s.grid.nz,self.s.grid.ny),(self.s.pz,self.s.py))

    def before_E(self):
        self.old_E=[getattr(self.s.yee,'E'+str(k)).copy() for k in range(3)]

    def after_E(self):
        s,y=self.s,self.s.yee
        mid=[.5*(self.old_E[k]+getattr(y,'E'+str(k))) for k in range(3)]
        for k in range(3):
            vol=self.vol[k];dt=s.dt;er=getattr(y,'er'+str(k));J=getattr(y,'J'+str(k))
            self.grid['particle']+=float(dt*np.sum(self.particle_J[k]*mid[k]*vol))
            self.grid['antenna']-=float(dt*np.sum((J-self.particle_J[k])*mid[k]*vol))
            scale=C.eps0*er*vol*dt
            self.grid['load']+=float(np.sum(scale*self.load_rate[k]*mid[k]**2))
            self.grid['absorber']+=float(np.sum(scale*(getattr(y,'sE'+str(k))-self.load_rate[k])*mid[k]**2))
            if self.reference_ready:
                self.grid['load_rf']+=float(np.sum(scale*self.load_rate[k]*(mid[k]-self.native_mean[k])**2))
            if self.direct_rf and self.reference_ready:
                self.grid['rf_direct'] -= float(dt*np.sum(self.particle_J[k]*(mid[k]-self.native_mean[k])*vol))
            self.sum_E[k]+=mid[k]*dt;self.sum_J[k]+=self.particle_J[k]*dt
            self.sum_JE+=float(dt*np.sum(self.particle_J[k]*mid[k]*vol))
        self.block_elapsed+=s.dt
        if self.block_elapsed>=self.block_time*(1.-1e-12):self.flush_block(s.t+s.dt)

    def control(self,before,p):
        self.grid['control']+=sum(self.field_energy())-before
        c=self.s.circuit
        if p is not None and c is not None:
            voltages=self.s.voltages(self.s.t+.5*self.s.dt)
            group=np.zeros(c.nk)
            for i,v in enumerate(voltages):group[c.group_of[i]]=v
            self.grid['voltage']+=float(np.dot(group,-c.C@p))

    def flush_block(self,t_end):
        if not self.block_elapsed:return
        T=self.block_elapsed
        dc=sum(float(np.sum(self.sum_J[k]/T*self.sum_E[k]/T*self.vol[k])) for k in range(3))
        rf=-(self.sum_JE/T-dc)
        if self.writing and self.s.rank==0:
            self.block_writer.writerow([self.block_index,t_end,T,dc,rf])
            if self.s.model['diagnostics']['energy_save_work_grids']:
                np.savez_compressed(self.aux/f'work_block_{self.block_index:05d}.npz',
                    **{'mean_E'+str(k):self.sum_E[k]/T for k in range(3)},
                    **{'mean_J'+str(k):self.sum_J[k]/T for k in range(3)},
                    t_end=t_end,duration=T,grid_work_J_per_m=self.sum_JE)
        self.block_index+=1;self.block_elapsed=0.;self.sum_JE=0.
        for a in self.sum_J+self.sum_E:a[:]=0.

    def names_units(self):
        base={'ED_reference_ready':'','ED_W_push':'J/m','ED_W_dc':'J/m','ED_W_rf':'J/m',
              'ED_W_applied':'J/m','ED_W_grid_particle':'J/m','ED_W_antenna':'J/m',
              'ED_W_load':'J/m','ED_W_load_rf':'J/m','ED_W_absorber':'J/m',
              'ED_W_voltage':'J/m','ED_W_constraint':'J/m','ED_K_inserted':'J/m',
              'ED_K_absorbed':'J/m','ED_U_electric':'J/m','ED_U_magnetic':'J/m',
              'ED_R_particle':'J/m','ED_R_work_split':'J/m','ED_R_model':'J/m',
              'ED_eta_load':'%','ED_P_load':'W/m','ED_P_load_rf':'W/m'}
        if self.direct_rf:
            base.update(ED_W_rf_direct='J/m',ED_P_rf_direct='W/m',ED_W_grid_rf_direct='J/m',
                        ED_R_rf_arithmetic='J/m',ED_R_rf_exchange='J/m')
        if self.s.work_centered:
            base.update(ED_R_exchange='J/m',ED_W_applied_rf='J/m',ED_coupling_iterations='',ED_coupling_residual='')
        for j in range(self.nsurf):base[f'ED_K_surface_{j}']='J/m';base[f'ED_P_surface_{j}']='W/m'
        return base

    def history_values(self):
        s=self.s
        if self.last_history is not None and s.t == self.previous_time:
            return [self.last_history[k] for k in self.names_units()]
        local=s.comm.allreduce(np.array([self.local[k] for k in self.local])) if s.size>1 else np.array(list(self.local.values()))
        p=dict(zip(self.local,local));sur=s.comm.allreduce(self.surfaces) if s.size>1 else self.surfaces.copy()
        rf_sur = None
        if self.direct_rf:
            rf_sur = s.comm.allreduce(self.rf_surfaces) if s.size>1 else self.rf_surfaces.copy()
        lost=float(sur[:,2].sum());ke=self._global_KE();ue,ub=self.field_energy();G=self.grid
        ready=self.reference_ready
        eta=np.nan
        if ready:
            v=G['voltage']-self.ref_grid0['voltage']
            if v>0:eta=100*(G['load_rf']-self.ref_grid0['load_rf'])/v
        values={'ED_reference_ready':float(ready),'ED_W_push':p['push'],
                'ED_W_dc':p['dc'] if ready else np.nan,'ED_W_rf':p['rf'] if ready else np.nan,
                'ED_W_applied':p['applied'],'ED_W_grid_particle':G['particle'],
                'ED_W_antenna':G['antenna'],'ED_W_load':G['load'],
                'ED_W_load_rf':G['load_rf'] if ready else np.nan,'ED_W_absorber':G['absorber'],
                'ED_W_voltage':G['voltage'],'ED_W_constraint':G['control'],
                'ED_K_inserted':p['inserted'],'ED_K_absorbed':lost,
                'ED_U_electric':ue,'ED_U_magnetic':ub,
                'ED_R_particle':ke-self.initial_KE-p['push']-p['inserted']+lost,
                'ED_R_work_split':p['classified']-p['dc']+p['rf'] if ready else np.nan,
                'ED_R_model':ke-self.initial_KE+ue+ub-self.initial_field-p['applied']-G['antenna']-G['control']-p['inserted']+lost+G['load']+G['absorber'],
                'ED_eta_load':eta}
        dt=s.t-self.previous_time
        if s.work_centered:
            values.update(ED_R_exchange=p['push']-p['applied']-G['particle'],
                          ED_W_applied_rf=p['applied_rf'] if ready else np.nan,
                          ED_coupling_iterations=getattr(s,'coupling_iterations',0),
                          ED_coupling_residual=getattr(s,'coupling_residual',np.nan))
        for label,key in [('ED_P_load','load'),('ED_P_load_rf','load_rf')]:
            values[label]=(G[key]-self.previous_power.get(key,0.))/dt if dt>0 else np.nan
            if key=='load_rf' and not ready:values[label]=np.nan
            self.previous_power[key]=G[key]
        if self.direct_rf:
            elapsed = s.t-max(self.previous_time,self.reference_finished) if ready else 0.
            values.update(ED_W_rf_direct=p['rf_direct'] if ready else np.nan,
                ED_P_rf_direct=(p['rf_direct']-self.previous_power.get('rf_direct',0.))/elapsed if elapsed>0 else np.nan,
                ED_W_grid_rf_direct=G['rf_direct'] if ready else np.nan,
                ED_R_rf_arithmetic=p['rf_direct']-p['rf'] if ready else np.nan,
                ED_R_rf_exchange=p['rf_direct']-G['rf_direct']+p.get('applied_rf',0.) if ready else np.nan)
            self.previous_power['rf_direct'] = p['rf_direct']
        for j in range(self.nsurf):
            key='surface_'+str(j);values[f'ED_K_surface_{j}']=sur[j,2]
            power=(sur[j,2]-self.previous_power.get(key,0.))/dt if dt>0 else np.nan
            values[f'ED_P_surface_{j}']=power;self.previous_power[key]=sur[j,2]
            if self.writing and s.rank==0:self.surface_writer.writerow([s.step_count,s.t,self.surface_names[j],*sur[j],power,*(rf_sur[j] if self.direct_rf else [])])
        self.previous_time=s.t;self.last_history=values
        for fh in self.handles:fh.flush()
        return [values[k] for k in self.names_units()]

    def current_snapshot(self):
        j0,j1,j2=self.particle_J
        # Spatial interpolation only; time stamps explicitly preserve staggering.
        from ..fields.fdtd import _avg_half_to_node
        return {'Jz':_avg_half_to_node(j0,0,self.s.pz),'Jy':_avg_half_to_node(j1,1,self.s.py),
                'Jx':j2.copy(),'J_time':self.s.t-.5*self.s.dt,
                'native_Jz':j0,'native_Jy':j1,'native_Jx':j2}

    def write_metadata(self):
        if not self.writing or self.s.rank!=0:return
        metadata=dict(format_version=1,geometry='2D-ZY',energy_unit='J/m',power_unit='W/m',
            momentum='u=p/m [m/s]',weight='real particles per metre of out-of-plane depth',
            surfaces=dict(enumerate(self.surface_names)),reference_ready=self.reference_ready,
            reference_t_start=self.reference_started,reference_t_end=self.reference_finished,
            particle_work='Exact electric-kick work of the Boris push; RF positive from particles to reference-subtracted fluctuations.',
            reference='Frozen time mean of the actual gather operator; diagnostic only, never applied to the solver.',
            impact='KE at solver removal after its full push; physical wall interception requires timestep convergence.',
            insertion='KE of the numerical half-step state inserted by the emitter, not assumed cathode thermal KE.',
            voltage_work='sum V_group(t+dt/2)*(-C*p)_group per held-voltage correction; separate from direct applied-field and controller work.',
            model_balance='K+native Yee field energy; applied-particle/antenna/controller work, inserted/absorbed KE, load and absorber losses accounted. Residual includes grid/pusher exchange, filtering, field discretization and unmeasured open-boundary flux. Not forced to zero.',
            eta='RF load loss / V*dQ work after reference freeze; meaningful only for stationary held-voltage operation with converged residuals. Not available before reference.',
            grid_blocks='Covariance of native Yee self E and filtered particle J, excluding imposed/static electric fields; cross-check distinct from actual gathered-particle work.',
            histogram='Weighted impact counts; final bin contains all energies above range.',
            track_stride=self.track_stride,track_every=self.track_every,MPI_ranks=self.s.size,
            event_files='Per-rank shards; global counters MPI-reduced once, replicated fields never MPI-summed.',
            hub_crossings='Selected trajectories; time, position, KE/work linearly interpolated within a step.',
            signal_units=self.names_units())
        metadata.update(em_coupling=self.s.model['simulation'].get('em_coupling','legacy'),
                        work_displacement='orbit residence * discrete-gradient velocity' if self.s.work_centered else 'two Boris electric kicks',
                        direct_rf_enabled=self.direct_rf,raw_rf_push_trace=self.push_trace,
            species={sp.index:sp.name for sp in self.s.species})
        if self.direct_rf:
            metadata.update(format_version=2,
                direct_rf='Explicit -q*(actual gathered E - frozen gathered mean E).d_Boris every existing particle push. No KE/work subtraction; positive from particles to fluctuations.',
                direct_rf_coverage='rf_valid_since is the first classified time (reference freeze for existing particles, first classified push for later births). Earlier segments are incomplete; unavailable values are NaN.',
                direct_rf_units='Per-particle work J; global sum weight*work J/m. History output stride never thins integration.',
                direct_rf_impact='Full numerical push before absorption; unclipped endpoints retained. Lifetime work at a surface is cohort attribution, not another output energy channel.',
                direct_rf_trace='Optional per-rank buffered rf_push_rank*.npz. Selected IDs every push after reference; z,y positions and vector components z,y,x. Join impact events by ID and step. d_Boris is electric-kick work displacement, not clipped geometric displacement.',
                direct_rf_restart='Each new Simulation starts a new diagnostic epoch. Persistent restart restoration is not implemented; do not concatenate counters across independent runs.',
                direct_rf_grid='Explicit -dt*sum J_particle*(native E_mid-native frozen mean)*dual_volume; already global grids are never MPI-summed.',
                direct_rf_interpretation='Fluctuations include noncoherent fields/mean drift. Pusher arithmetic agreement does not establish particle-grid conservation or load output.')
        if self.s.work_centered:
            metadata.update(particle_work='q times orbit-averaged E dot actual residence displacement; nonlinear Lorentz/current solve, synchronized momenta.',
                impact='First painted-cell or domain intersection; momentum, current, work and event time use the same partial residence.',
                insertion='Physical birth kinetic energy before acceleration; random birth time and charge/emission law retained.',
                reference='Frozen converged midpoint native self E and native bias gradient, with static uniform applied E. node_fields is a nodal display representation; forces use orbit gathering.',
                direct_rf='Explicit -q*(orbit E - orbit frozen native/bias mean E).d_work. No KE subtraction.',
                direct_rf_grid='Native self-field RF current work only. ED_R_rf_exchange additionally accounts for ED_W_applied_rf, the imposed-bias fluctuation work to particles; a startup ramp is not unexplained grid RF.',
                direct_rf_impact='Work ends at the first absorbing surface, including within-step birth/impact.',
                direct_rf_trace='d_work is the actual 3-component work displacement. d_Boris is NaN; dt/t_before describe individual residence. position_after_unclipped is already at impact in this mode.')
        (self.aux/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')

    def close(self):
        self._flush_push_trace()
        self.flush_block(self.s.t)
        hist=self.s.comm.allreduce(self.hist) if self.s.size>1 else self.hist
        if self.writing and self.s.rank==0:
            np.savez_compressed(self.aux/'impact_histograms.npz',weighted_counts=hist,
                                energy_edges_eV=np.linspace(0,self.max_eV,self.bins+1),
                                surface_names=np.asarray(self.surface_names),last_bin_is_overflow=True)
            self.write_metadata()
        for fh in self.handles:fh.close()
        self.handles.clear()
