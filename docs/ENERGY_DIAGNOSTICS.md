# Magnetron energy diagnostics

Enable **Output → Energy conversion diagnostics** for a **2D-ZY electromagnetic,
Boris, full-motion** model. The default is off. The diagnostics observe the
existing push, current deposition and field updates; they never change forces,
emission, boundary handling, smoothing, or conductor modes. They add memory,
arithmetic and output cost. Other geometries and pushers are rejected when the
option is enabled, before an output folder is opened.

Set **Mean-field reference starts at** after the oscillation settles and choose
a reference duration covering many RF periods. The diagnostic records a time
mean of the fields actually gathered by the particles, then freezes that mean
as its DC reference. The evolving simulation fields are unaffected. DC/RF
measurements start after this reference is complete; earlier values are NaN.
The reference-subtracted field includes all fluctuations, not just a selected
magnetron mode. Repeat with different reference windows to check sensitivity.

## Measurements

- `ED_W_push`: total electric work **to** particles, using the unchanged Boris
  electric kicks and their kinetic-energy-consistent velocities.
- `ED_W_dc`: work **to** particles from the frozen mean field.
- `ED_W_rf`: work **from** particles to the reference-subtracted field. Positive
  means net delivery by particles. Over the measurement interval,
  `ΔK = W_dc − W_rf` for each particle, apart from insertion/removal and roundoff.
  The total-work counter also includes the earlier reference-collection interval.
- `ED_K_surface_i`, `ED_P_surface_i`: cumulative absorbed KE and interval impact
  power by boundary/object. They measure all absorbed particles before deletion.
  `metadata.json` maps surface numbers to names. Impacts are at the solver's
  removal state after a full push; check timestep convergence for physical impact KE.
- `ED_W_load`, `ED_W_load_rf`, `ED_P_load`, `ED_P_load_rf`: conductivity loss using
  the actual Crank–Nicolson midpoint electric field; RF uses the reference-subtracted
  native Yee field. Load means every object with material conductivity. If several
  are present the signal is their sum. Absorbing-layer losses are separate.
- `ED_W_voltage`: `Σ V_group(t+dt/2) (−C p)_group` from each held-voltage
  correction. This is distinct from work by the imposed field and from the
  native Yee field energy change caused by the correction (`ED_W_constraint`).
  Time-varying imposed-voltage field energy is not included in the Yee budget.
- `ED_eta_load`: 100 times RF conductivity loss divided by held-voltage source
  work, both since reference completion. It is NaN without positive source work.
  It is a candidate load-conversion measure, requiring stationary operation and
  convergence checks, not an automatic proof of physical efficiency. Unclamped
  conductor modes have no measured voltage-source work and therefore no such efficiency.
- `ED_R_particle`, `ED_R_work_split`: independent particle KE and split residuals.
  `ED_R_model` checks particle plus native Yee energy against applied-field,
  antenna/controller work, injection, absorption, load and absorber losses. It
  includes exchange/filtering/discretization errors and unmeasured open-boundary
  flux; it is not forced to zero. Use the existing power monitors to measure
  outward flux when the model has open boundaries.

In 2D-ZY integrated energies are **J/m** and powers **W/m** of out-of-plane
depth. Per-electron trajectory work and KE are **J**; multiply by the particle
weight (real electrons/m) to obtain its contribution. The instantaneous `Jz`,
`Jy`, `Jx` maps are A/m². Native staggered currents are saved for analysis and
excluded from the GUI's nodal-field selector. `J_time` records their half-step time.

## Output and GUI

The Live monitor **History → Signals** menu and saved **Results → History**
include the `ED_` signals, with units and descriptive labels/tooltips. Output
controls save/load with the model. The live status reports reference readiness.
The app starts light and keeps its theme toggle. The four Live monitor subplots
retain their dark backgrounds. Figure exports always use white backgrounds,
including exported Live monitor plots, geometry vacuum patches and legend frames.

### Direct RF work every particle push

With Energy conversion diagnostics enabled, select **Direct RF work every
particle push**. Its default is off, preserving existing model settings. The
new signals appear with readable labels in Live monitor and Results History:

| Signal | Measurement |
|---|---|
| `ED_W_rf_direct` | Explicit RF-field work from all particles, J/m |
| `ED_P_rf_direct` | Interval direct RF power from all particles, W/m |
| `ED_W_grid_rf_direct` | Explicit native-grid particle-current RF work, J/m |
| `ED_R_rf_arithmetic` | Direct work minus the original work-split counter, J/m |
| `ED_R_rf_exchange` | Particle direct RF work minus native-grid RF work, J/m |

At each existing Boris push the diagnostic computes
`delta_W_rf_direct = -q * (E_actual_gathered - E_DC_gathered) dot d_Boris`.
`d_Boris` is the work displacement of the two original electric kicks, using
their relativistic energy-consistent velocities. The explicit RF dot product
does not subtract KE or total/DC work counters, reconstruct field snapshots,
or change particle/field updates. Positive means energy from particles to the
reference-subtracted fluctuations. All particles contribute every push;
history/trajectory write intervals only control reporting cadence.

The native-grid counter explicitly integrates
`-dt * sum(J_particle * (E_native_mid - E_native_DC) * dual_volume)`.
Only particle current is used; antenna current stays separate. Replicated
grid work is not summed over MPI ranks. Comparing it with particle work
exposes exchange discrepancies; the direct particle dot product should match
the original work-split counter to roundoff but does not establish that this
energy reached the RF load or fix a coupling/conservation error.

Selected trajectory and impact CSVs append `W_rf_direct_J` and `rf_valid_since`.
An unavailable reference/coverage gives NaN, and `rf_valid_since` records the
first classified time. For particles already present, coverage begins at
reference completion; later particles begin at their first classified push.
Never claim complete segment/lifetime work before that coverage begins.
The global time integral retains work from particles after they are absorbed.
`surface_energy.csv` adds classified direct work attributed to absorbed
cohorts and their represented particle count; do not add this attribution
again to the global energy ledger. Hub records include before/after counters
and endpoints plus a labelled linear within-push crossing estimate. Impacts
retain unclipped push endpoints and the existing full-push KE/work convention;
they do not claim an exact physical substep wall-interception energy.

**Save gathered RF fields every push (selected IDs)** is a separate option,
off by default. When enabled, buffered `rf_push_rankNNNN_IIIII.npz` files save
the deterministic tracked-ID sample every classified push, including its
absorption push. Fields include ID/species index, step/time/dt, physical
particle weight, charge/mass, old/new unclipped positions and momenta, actual
gathered E, gathered DC reference, `d_Boris`, incremental direct RF work,
cumulative direct RF work and coverage time. Vectors use component order
`z,y,x`; positions use `z,y`. Join impact records by ID and step. These records
permit a direct offline field dot product without dense full-grid snapshots.
They can produce large files. Raw trace selection never thins integration of
the global and per-particle counters or consumes the simulation RNG.

Each new Simulation is a new diagnostic epoch; restoring a cumulative direct
RF diagnostic from a restart is not implemented. Do not concatenate reset
counters across runs. These are numerical work diagnostics and need reference,
timestep, mesh and particle/grid-budget checks before physical interpretation.

Ordinary geometry-object `I_`/`V_` histories are separately opt-in under
**Geometry Objects → Record current (I) / Record voltage (V)**. Enable them for
the electrodes you want to analyze. They do not gate energy-impact accounting;
see [Optional geometry-object histories](OBJECT_HISTORY.md).

`<output>/energy_diagnostics/` contains:

- `metadata.json` and `dc_reference.npz`: definitions, signs, units, surfaces,
  averaging interval and frozen reference.
- `surface_energy.csv`, `impact_histograms.npz`: global surface measurements.
  The histogram has a separate overflow bin; no high-energy impact is discarded.
- `trajectories_rankNNNN.csv`, `impacts_rankNNNN.csv`: persistent particle IDs
  and work/KE. Deterministic ID selection does not consume the solver random
  generator. Track stride applies only to detailed records; population totals
  and histograms include every particle. IDs persist through growth/deletion.
- `hub_crossings_rankNNNN.csv`: optional selected-particle crossing records at
  a specified y plane, interpolated linearly within the step. Choose a physically
  justified hub plane; this is not an automatically determined Brillouin edge.
- `work_blocks.csv`: native self-field/current mean and covariance work as an
  independent check; imposed DC fields are excluded from this grid check.
  **Save block-mean E and J grids** adds spatial mean arrays for each block.

MPI particle counters are reduced once; replicated field quantities are not
summed over ranks. Detailed trajectories/impacts are per-rank files. Standard
particle snapshots retain their existing per-rank sampling behavior and are
not a substitute for these global energy totals. Particle `u` remains p/m at
the solver's half-step; records do not claim synchronized physical wall times.

The accompanying MPI correction makes every replicated Yee grid use the global
deposition flag, including an empty rank. It fixes a missed current update without
changing the deposition or field equations. Regression check:
`mpiexec -n 2 python tests/mpi_energy_diagnostics.py`.

## Answering the potential-versus-kinetic-energy question

Run copies of the validated cases with diagnostics enabled, retain the original
model physics, and average in settled windows. Compare DC work, RF delivery,
changes in stored particle KE, electrode impact KE, and RF load loss. Selected
trajectories and a justified hub plane distinguish energy acquired during RF
interaction from KE already carried into that interaction. Check reference-window,
mesh, timestep and particle-count convergence, and account for the energy residuals
before claiming a partition of potential and kinetic contributions. A large RF
output alone does not resolve that partition. No old result gains these missing
particle/impact measurements retrospectively.
