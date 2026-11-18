"""Opt-in, work-paired Cartesian EM particle/field integration.

Physical equations, painted geometry, emission laws, bias and Maxwell/load
operators are unchanged. Momentum and current are solved together against the
same midpoint native E. A nonconverged step is an error, never a legacy fallback.
"""
import numpy as np
from .. import constants as C
from ..particles import kernels as K
from ..particles.work_centered import orbit_gather, first_absorption, paired_flux


def validate(model):
    sim=model['simulation'];mode=sim.get('em_coupling','legacy')
    if mode not in ('legacy','work-centered'): raise ValueError('Unknown EM particle-field coupling')
    if mode=='legacy': return
    if sim['geometry']!='2D-ZY' or sim['solver']!='electromagnetic':
        raise ValueError('Work-centered coupling requires Cartesian 2D-ZY electromagnetic geometry')
    if int(sim.get('smoothing',0) or 0) or int(sim.get('current_filter',0) or 0):
        raise ValueError('Work-centered coupling requires smoothing=0 and current_filter=0')
    if sim.get('field_gathering','auto') not in ('auto','energy-conserving'):
        raise ValueError('Work-centered coupling requires native energy-conserving gathering')
    if any(s.get('motion','full')!='full' for s in model['species']):
        raise ValueError('Work-centered coupling requires full particle motion')
    for b in model['boundaries'].values():
        if b.get('field')!='periodic' and b.get('particles','absorb')!='absorb':
            raise ValueError('Work-centered coupling supports absorbing or periodic particle walls')
    from ..model.model import evaluator
    ev=evaluator(model)
    for field in model['external_fields']:
        if field.get('type','uniform')!='uniform' or ev.is_time_dependent(field.get('time_factor','1')):
            raise ValueError('Work-centered coupling currently supports static uniform applied fields')
    tol=ev.num(sim.get('coupling_tolerance','1e-11'));limit=ev.num(sim.get('coupling_iterations','100'))
    if not np.isfinite(tol) or not 0<tol<1e-3: raise ValueError('Coupling tolerance must be between 0 and 1e-3')
    if not np.isfinite(limit) or limit!=int(limit) or limit<2: raise ValueError('Coupling iterations must be an integer >= 2')


def bias_fields(s,time=None):
    """Native gradient of the actual imposed Laplace potential, without nodal averaging."""
    g=s.grid
    phi=s.poisson.laplace_field(s.voltages(time)) if time is not None and s.v_td else s.bias_phi
    if phi is None:
        return [np.zeros_like(getattr(s.yee,'E'+str(k))) for k in range(3)]
    p=phi
    return [-(p[1:]-p[:-1])/g.dz,-(p[:,1:]-p[:,:-1])/g.dy,np.zeros_like(p)]


def gather(s, native, z0,y0,z1,y1):
    g=s.grid
    return orbit_gather(*native,(z0-g.z_min)/g.dz,(y0-g.y_min)/g.dy,
                        (z1-g.z_min)/g.dz,(y1-g.y_min)/g.dy,g.nz,g.ny,s.pz,s.py)


def velocity(a,b,rel):
    if not rel:return .5*(a+b)
    ga=np.sqrt(1+np.sum(a*a,axis=0)/C.c**2)
    gb=np.sqrt(1+np.sum(b*b,axis=0)/C.c**2)
    return (a+b)/(ga+gb)


def momentum_target(a,guess,E,B,h,qm,hand,rel):
    """Cayley solution of midpoint Lorentz force for a trial gamma sum.

    The rotation preserves |u| exactly. Unlike a damped momentum iteration it
    also preserves the electric-work identity before nonlinear convergence.
    """
    den=(np.sqrt(1+np.sum(a*a,axis=0)/C.c**2)+
         np.sqrt(1+np.sum(guess*guess,axis=0)/C.c**2)) if rel else 2.
    kick=.5*qm*h*E
    minus=a+kick;rotation=hand*qm*h*B/den
    prime=minus+np.cross(minus.T,rotation.T).T
    plus=minus+np.cross(prime.T,(2*rotation/(1+np.sum(rotation*rotation,axis=0))).T).T
    return plus+kick


def _advance(s,old,J,t,dt,diagnostics=False):
    y=s.yee;d=s.energy_diag if diagnostics else None
    for k in range(3):
        getattr(y,'E'+str(k))[:]=old[k]
        getattr(y,'B'+str(k))[:]=old[3+k]
        getattr(y,'J'+str(k))[:]=J[k]
    if d:d.record_particle_current()
    for source in s.sources: source.apply(y,t+.5*dt)
    if d:d.before_B()
    y.half_B(dt)
    if d:d.after_B();d.before_E()
    y.full_E(dt,s.axis_factor)
    if d:d.after_E();d.before_B()
    y.half_B(dt)
    if d:d.after_B()


def step(s,t,dt):
    """Implicit Lorentz/current solve with no diagnostic effects in trial iterations."""
    if getattr(s,'_coupling_failed',False):
        raise RuntimeError('A work-centered step failed; start a new Simulation with corrected inputs instead of retrying the failed epoch')
    g=s.grid;y=s.yee
    if C.c*dt>min(g.dz,g.dy):
        raise ValueError('Work-centered coupling requires c*dt <= min(dz,dy); reduce the timestep')
    old=[getattr(y,p+str(k)).copy() for p in ('E','B') for k in range(3)]
    saved_J=[getattr(y,'J'+str(k)).copy() for k in range(3)]
    # B at n+1/2 from the unchanged Yee half-step. It does no particle work.
    y.half_B(dt);B=[getattr(y,'B'+str(k)).copy() for k in range(3)]
    for k in range(3):getattr(y,'B'+str(k))[:]=old[3+k]
    ext=s.ext.nodal(t+.5*dt)
    extE=np.zeros(3) if ext is None else ext[:3,0,0]
    extB=np.zeros(3) if ext is None else ext[3:,0,0]
    bias=bias_fields(s,t+.5*dt)
    data=[]
    # Generate birth charge once from the original emission law and RNG stream.
    # Newborns supply their physical initial momentum and remaining residence time.
    original_counts={sp.name:sp.n for sp in s.species}
    residence={sp.name:np.full(sp.n,dt) for sp in s.species}
    seed={sp.name:np.zeros((3,sp.n)) for sp in s.species}
    for sp,out in s._emit(t):
        residence[sp.name]=np.r_[residence[sp.name],out['residence_time']]
        direction=np.zeros((3,len(out['w'])));direction[:2]=out['iteration_seed']
        seed[sp.name]=np.column_stack([seed[sp.name],direction])
        sp.add(out['z'],out['y'],out['u0'],out['u1'],out['u2'],out['w'])
    for sp in s.species:
        if not sp.n:continue
        a=np.array([sp.u0,sp.u1,sp.u2])
        # Outward seed only initializes the nonlinear solve at a surface; it is
        # never an injected momentum/energy or part of the accepted solution.
        data.append(dict(sp=sp,a=a,u=a+seed[sp.name],z0=sp.z.copy(),y0=sp.y.copy(),tau=residence[sp.name]))
    guess=[a.copy() for a in old[:3]]
    tol=s.ev.num(s.model['simulation']['coupling_tolerance'])
    limit=int(s.ev.num(s.model['simulation']['coupling_iterations']))
    relaxation=1.;previous_error=np.inf
    try:
        for iteration in range(limit):
            flux=[np.zeros_like(a) for a in old[:3]]
            local_error=0.
            invalid_move=False
            for d in data:
                sp=d['sp'];v=velocity(d['a'],d['u'],s.rel);tau=d['tau']
                fullz=d['z0']+tau*v[0];fully=d['y0']+tau*v[1]
                if (not np.all(np.isfinite(v)) or np.any(abs(fullz-d['z0'])>g.dz)
                        or np.any(abs(fully-d['y0'])>g.dy)):
                    invalid_move=True;continue
                alpha,flag=first_absorption((d['z0']-g.z_min)/g.dz,(d['y0']-g.y_min)/g.dy,
                    (fullz-g.z_min)/g.dz,(fully-g.y_min)/g.dy,s.mats.cell_obj,g.nz,g.ny,s.pz,s.py)
                h=tau*alpha;z=d['z0']+h*v[0];yy=d['y0']+h*v[1]
                mid=[.5*(a+b) for a,b in zip(old[:3],guess)]
                native=gather(s,mid,d['z0'],d['y0'],z,yy)
                applied=gather(s,bias,d['z0'],d['y0'],z,yy)+extE[:,None]
                E=native+applied
                bz=np.ascontiguousarray(((d['z0']+z)/2-g.z_min)/g.dz)
                by=np.ascontiguousarray(((d['y0']+yy)/2-g.y_min)/g.dy)
                # Periodic lookup only: leave deposited trajectories unwrapped.
                if s.pz:bz%=g.nz
                if s.py:by%=g.ny
                P=np.zeros((6,sp.n));zero=[np.zeros_like(a) for a in old[:3]]
                K.gather_ec_yee_2d(*zero,*B,bz,by,sp.n,g.nz,g.ny,P)
                magnetic=P[3:]+extB[:,None]
                target=momentum_target(d['a'],d['u'],E,magnetic,h,sp.qm,s.hand,s.rel)
                scale=max(1.,float(np.max(np.abs(target-d['a']))))
                roundoff=16*np.finfo(float).eps*max(1.,float(np.max(abs(target))),float(np.max(abs(d['a']))))
                local_error=max(local_error,max(0.,float(np.max(np.abs(target-d['u'])))-roundoff)/scale)
                # Native scatter is unchanged. Q2 carries only the actual residence
                # fraction; its full-step normalization is applied in Yee.set_J.
                dep=paired_flux((d['z0']-g.z_min)/g.dz,(d['y0']-g.y_min)/g.dy,
                                (z-g.z_min)/g.dz,(yy-g.y_min)/g.dy,
                                v[2]*h/dt,sp.w,sp.q,g.nz,g.ny,s.pz,s.py)
                for f,a in zip(flux,dep):f+=a
                d.update(target=target,z=z,y=yy,h=h,flag=flag,v=v)
            if s.comm.allsum(int(invalid_move)):
                raise RuntimeError('Work-centered path exceeds one cell or is nonfinite; reduce dt')
            if s.size>1:flux=[s.comm.allreduce(a) for a in flux]
            y.J0[:]=flux[0]/(dt*y.Az[None,:]);y.J1[:]=flux[1]/(dt*y.Ay);y.J2[:]=flux[2]/y.vol
            J=[getattr(y,'J'+str(k)).copy() for k in range(3)]
            _advance(s,old,J,t,dt)
            nextE=[getattr(y,'E'+str(k)).copy() for k in range(3)]
            if s.comm.allsum(int(not all(np.all(np.isfinite(a)) for a in nextE))):
                raise RuntimeError('Nonfinite work-centered field update; check inputs and reduce dt')
            field_error=max(float(np.max(abs(a-b)))/max(1.,float(np.max(abs(a))),float(np.max(abs(b)))) for a,b in zip(nextE,guess))
            error=max(s.comm.allsum(local_error),field_error)
            if error<tol:break
            # Most resolved PIC steps are contractive without damping. Reduce
            # relaxation only if the coupled residual grows, rather than paying
            # ~40 half-relaxed iterations even for a weakly coupled step.
            if error>1.1*previous_error:relaxation=max(.25,.5*relaxation)
            previous_error=error
            for d in data:d['u']=d['target']
            guess=[(1-relaxation)*a+relaxation*b for a,b in zip(guess,nextE)]
        else:
            raise RuntimeError(f'Work-centered coupling did not converge in {limit} iterations (residual {error:.3g}); reduce dt')
    except Exception:
        s._coupling_failed=True
        for k in range(3):
            getattr(y,'E'+str(k))[:]=old[k];getattr(y,'B'+str(k))[:]=old[3+k]
            getattr(y,'J'+str(k))[:]=saved_J[k]
        # No old particle state was advanced. Remove trial newborns; a failed
        # step is fatal (emission RNG must not be silently retried).
        for sp in s.species:sp.keep(np.arange(sp.n)<original_counts[sp.name])
        raise
    _advance(s,old,J,t,dt,diagnostics=True)
    actual_mid=[.5*(a+getattr(y,'E'+str(k))) for k,a in enumerate(old[:3])]
    if s.energy_diag:s.energy_diag.centered_reference(actual_mid,bias)
    s._impact_times={}
    for d in data:
        sp=d['sp'];sp._z[:sp.n]=d['z'];sp._y[:sp.n]=d['y']
        for k in range(3):getattr(sp,'_u'+str(k))[:sp.n]=d['u'][k]
        E=gather(s,actual_mid,d['z0'],d['y0'],d['z'],d['y'])
        applied=gather(s,bias,d['z0'],d['y0'],d['z'],d['y'])+extE[:,None]
        disp=d['h']*d['v']
        s._impact_times[sp.name]=t+dt-d['tau']+d['h']
        if s.energy_diag:
            diag=s.energy_diag
            ref=None
            reference_applied=None
            if diag.reference_ready:
                reference_applied=gather(s,diag.bias_mean,d['z0'],d['y0'],d['z'],d['y'])+extE[:,None]
                ref=gather(s,diag.native_mean,d['z0'],d['y0'],d['z'],d['y'])+reference_applied
            diag.pushed(sp,d['a'],d['z0'],d['y0'],E+applied,ref,applied,
                        work_displacement=disp,durations=d['h'],start_times=t+dt-d['tau'],reference_applied=reference_applied)
        s._account(sp,d['flag']);sp.keep(d['flag']==0)
        if s.pz:K.pick(K.wrap_periodic,sp.n)(sp._z,sp.n,g.z_min,g.z_max)
        if s.py:K.pick(K.wrap_periodic,sp.n)(sp._y,sp.n,g.y_min,g.y_max)
    if s.circuit is not None:
        before=sum(s.energy_diag.field_energy()) if s.energy_diag else 0.
        correction=s.circuit.apply()
        if s.energy_diag:s.energy_diag.control(before,correction)
    s.coupling_iterations=iteration+1;s.coupling_residual=error
    s._j_dirty=True
    s._em_fields(t+dt)
