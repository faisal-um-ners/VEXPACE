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
