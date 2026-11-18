"""Passive direct RF-field work for the existing full-motion Boris push.

Passive direct RF-field work for an already completed, unchanged Boris push.
All inputs have shape (3,n), in actual VEXPACE component order (z,y,x).
u=p/m has velocity units, but is not the physical velocity at relativistic
energies. Each returned work is Joules per physical particle, NOT multiplied
by the macro-particle weight. Positive means electron -> fluctuating field.
"""
import numpy as np

C = 299792458.0


def direct_rf_boris_work(u_before, u_after, electric, frozen_dc, charge,
                         mass, dt, relativistic=True):
    """Compute -q (E_gathered-E_DC) dot d_Boris, without work/KE subtraction.

    Valid for unconstrained full-motion Cartesian Boris pushes, matching the
    existing VEXPACE diagnostic scope. Apply only after reference_ready.
    No particle update is performed and no argument is written to.
    """
    a, b, E, E_dc = [np.asarray(x, dtype=float) for x in
                      (u_before, u_after, electric, frozen_dc)]
    if a.ndim != 2 or a.shape[0] != 3 or not all(x.shape == a.shape for x in (b, E, E_dc)):
        raise ValueError('Expected four arrays of shape (3,n)')
    if dt <= 0 or mass <= 0:
        raise ValueError('dt and mass must be positive')
    kick = .5 * charge / mass * dt * E
    u_minus = a + kick
    u_plus = b - kick
    if relativistic:
        gamma = lambda u: np.sqrt(1. + np.sum(u*u, axis=0)/C**2)
        v_first = (a + u_minus) / (gamma(a) + gamma(u_minus))
        v_second = (u_plus + b) / (gamma(u_plus) + gamma(b))
    else:
        v_first = .5 * (a + u_minus)
        v_second = .5 * (u_plus + b)
    d_boris = .5 * dt * (v_first + v_second)
    # This explicit RF-field dot product never computes or subtracts K,
    # total electric work, or mean-field work.
    E_rf = E - E_dc
    components = -charge * E_rf * d_boris
    return dict(rf_direct_J=np.sum(components, axis=0),
                rf_direct_components_J=components,
                E_rf_V_per_m=E_rf,
                boris_displacement_m=d_boris)
