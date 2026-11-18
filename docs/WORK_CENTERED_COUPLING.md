# Work-centered electromagnetic particle–field coupling

Select **Study / Solver → EM particle–field coupling → Work-centered (implicit)**.
Set **Binomial smoothing passes = 0**, **Current filter passes = 0**, and
**Field gathering = auto** or **energy-conserving**. The explicit Boris/Vay/Higuera
selector is hidden: this mode uses the coupled midpoint update described below.
The tolerance and iteration limit appear when this mode is selected. Model checking
rejects unsupported combinations before the output folder is opened.

```json
"simulation": {
  "em_coupling": "work-centered",
  "field_gathering": "energy-conserving",
  "smoothing": 0,
  "current_filter": 0,
  "coupling_tolerance": "1e-11",
  "coupling_iterations": 100
}
```

These are numerical controls. The equations, applied B, electrode-voltage expressions
(including startup ramps), geometry, emission charge law/distribution and RF-load
model remain the model's inputs. Correcting the numerical approximation can change
trajectories and efficiencies. Existing JSON files default to `em_coupling: legacy`;
their explicit update and staggered momentum convention are preserved. Enabling the
new mode requires a new run; it does not repair old saved trajectories.

## Discrete work identity

The new mode synchronizes momentum and position. For each residence interval `h`,
it solves the Lorentz momentum equation using

\[
\bar v=(u^1+u^0)/(\gamma^1+\gamma^0),\qquad
x^1-x^0=h\bar v,\qquad u=p/m.
\]

This velocity gives the relativistic identity
`ΔK = m (u¹-u⁰) · v̄`; it reduces to the arithmetic velocity average in nonrelativistic
runs. A Cayley magnetic rotation preserves the momentum norm and the electric-work
identity. Iteration resolves the gamma sum, orbit and self-consistent midpoint E.
Magnetic force uses native B at the existing Yee half step and does no particle work.

Electric forces use the weights dual to the existing linear Esirkepov endpoint
fluxes, including the transverse `dSx*dSy/3` term. Stable overlap formulas evaluate
the same fluxes for tiny newborn paths without subtracting nearly equal shapes.
Consequently the particle's `q E_orbit · displacement` equals native
`dt Σ J_particle E_mid dual_volume`, to floating-point and nonlinear tolerances.
There is no rescaling of particle momentum, grid energy, RF output, or residuals
after the update. Charge continuity is retained to floating-point precision.

Maxwell's existing Yee update, PEC masks, material conductivity, antennas and
voltage clamp are retained. Trial iterations do not increment diagnostics or
regenerate emission. The converged current is replayed once for energy accounting.
Nonconvergence stops with an error suggesting a smaller timestep; it never silently
reverts to the legacy update. The reported residual allows for velocity roundoff.
A contractive step uses undamped field iteration; relaxation is reduced if the
residual grows, avoiding unnecessary half-relaxed iterations on every timestep.
A failed step is fatal; it is not an automatically retryable checkpoint.

## Bias, emission and surfaces

* The actual Laplace bias is differentiated directly on native edges and evaluated
  at the step midpoint, including a prescribed voltage ramp. This replaces a nodal
  averaged gradient only within the new coupling mode.
* Emission charge, initial velocity distribution, RNG draws and random birth times
  use the existing emission law. Newborns start with their physical birth momentum
  and are advanced for their actual remaining residence time. The legacy numerical
  half-step pre-acceleration is not used in this mode. Charge originates at the
  emitting surface instead of its legacy tiny vacuum offset, so birth has a
  boundary current rather than an unexplained interior charge source. Birth KE is counted as source
  insertion; subsequent acceleration is counted as electric work.
* Particle absorption occurs at the first intersection with the **same painted
  grid geometry used by Maxwell**, or an absorbing outer wall. Momentum update,
  deposited path, impact KE and event time use the same partial residence. This
  includes internal-object and periodic-seam intersections; it is not a change to
  the underlying CAD or material painting rule.

## Diagnostics and interpretation

Existing work, impact and direct RF controls remain in **Output**. Added history
signals are available in the Live monitor and Results like other saved signals:

| Signal | Meaning |
|---|---|
| `ED_R_exchange` | Particle electric work minus imposed-field work minus native particle-current work |
| `ED_coupling_iterations` | Nonlinear iterations in the last accepted step |
| `ED_coupling_residual` | Last accepted nonlinear residual |
| `ED_W_applied_rf` | Imposed-field fluctuation work **to particles**, relative to the frozen imposed-bias mean |

The frozen reference averages the **converged midpoint** native self E and bias
gradient separately. `dc_reference.npz` includes `bias_E0..2`; its `node_fields`
is a display representation, not the force interpolation. Direct RF work uses
the actual gathered reference-subtracted E dotted into the residence displacement,
without computing or subtracting KE. Native-grid RF work contains self fields only.
During a bias ramp, `ED_R_rf_exchange` therefore includes `+ ED_W_applied_rf` to account
for the externally imposed fluctuation work. The individual terms stay visible.
For static bias this extra term is zero.

Raw RF push traces contain `d_work`. In work-centered mode `d_Boris` is NaN;
`t_before` and `dt` describe each particle's residence, including births and impacts.
The backward-compatible key `position_after_unclipped` is already at impact in this
mode. Metadata identifies the coupling, work convention and impact timing.

Small **particle/grid exchange** residual does not imply perfect full-model energy
closure. Euclidean Yee field energy, finite-grid/time discretization, controller
work, absorber flux and open-boundary flux remain separate. A port diagnostic also
needs a compatible Poynting-flux interpretation. Check timestep/mesh convergence,
and compare residuals with RF output as well as the usually much larger DC input.
No new magnetron conversion efficiency is claimed by these code regressions.

## Supported configurations and tests

The new mode currently requires uniform Cartesian **2D-ZY electromagnetic**, full
particle motion, absorbing or periodic particle boundaries, no field smoothing or
current filtering, and static uniform externally prescribed E/B. Existing supported
prescribed electrode-voltage expressions and Maxwell antennas remain available.
RZ, ES, reflecting particle walls and spatially varying applied fields use legacy
mode. A path longer than one cell is rejected, including nonrelativistic particles
moving faster than the `c*dt` bound; reduce dt instead of depositing an invalid path.

Tests cover independent native-work and charge identities, periodic seams/cell
crossings, DC potential drop, within-step impact timing, cold SCL birth work,
direct RF exchange, nonlinear convergence, diagnostic passivity, GUI round trips,
legacy preservation, invalid-input protection, and serial/MPI equivalence with
empty ranks. Run:

```bash
python -m pytest -q tests/test_work_centered.py tests/test_work_centered_gui.py
mpiexec -n 2 python tests/mpi_work_centered.py
```

The nonlinear solve has additional cost. Validate a copied model before a long
production run. Its convergence error is controlled by the tolerance; spatial and
time discretization still require independent refinement studies.
