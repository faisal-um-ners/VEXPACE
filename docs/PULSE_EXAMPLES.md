# Checked vacuum pulse examples

Open **File → Examples**, select one of the following, and select
**Emission → pulsed_beam → Current pulse…**. Change a shape or value, click
**Apply to model**, then **Run**. The old result display is cleared when settings
change. A cancelled or failed save cancels Run, rather than running the old file.

| Example file | Coordinates | Pulse shape | Velocity spread | Mesh |
|---|---|---|---|---|
| `source_designer_beam_1d.pic.json` | 1D z | Gaussian | Maxwellian, kT = 0.5 eV | 120 uniform cells |
| `source_designer_square_1d.pic.json` | 1D z | Square | Waterbag, axial half-width 200 km/s | 120 uniform cells |
| `source_designer_trapezoid_1d.pic.json` | 1D z | Trapezoid | Trapezoid, axial half-width 200 km/s | 120 uniform cells |
| `source_designer_pulse_rz.pic.json` | Axisymmetric z,r | Gaussian | Maxwellian, kT = 0.5 eV | Local P1 triangles |
| `source_designer_pulse_zy.pic.json` | Cartesian z,y (YZ plane) | Trapezoid | Waterbag, half-width 200 km/s per component | Local P1 triangles |

These are illustrative beam transport problems, not published benchmark cases.
All have a vacuum interior with **no geometry objects, no applied fields**, a
15 mm axial domain, 1 keV injected electrons, and both axial boundary planes
grounded. The current is prescribed by the **beam** emission model. The
self-consistent space-charge field is still solved; “vacuum” does not turn
off the particles' own field.

## Pulse and observation times

- Physical pulse start: **0.10 ns**.
- Full pulse duration: **0.30 ns**, ending at **0.40 ns**.
- Peak current density: **10 A/m²** in the 1D cases and **100 A/m²** in the 2D cases.
- Gaussian cutoff: **3 sigma** on each side; FWHM is about **0.118 ns**.
- Trapezoid: each ramp is **0.06 ns**, with a **0.18 ns** flat top.
- Timestep: **1 ps**, giving 300 steps across the pulse support.
- Observation ends at **1.5 ns**, after the pulse has crossed the domain.

The advanced source evaluation offset is explicitly `pic_dt/2`, matching the
midpoint-current convention of the earlier short-pulse examples. The current
expression and its time gates share this offset. The particle pusher and
emission law are unchanged.

Pulse controls contain the source's duration and strength. Global parameters
contain the geometry, beam energy, solver timestep, and observation end. There
are no duplicate, inactive pulse-duration parameters in these examples.

At the final time the domain is empty: the pulse has reached the collector.
The history still shows its emission and arrival. To see spatial particles or
fields, use the Results snapshot slider to inspect an earlier saved frame,
for example around 0.2–1.0 ns.

## Two-dimensional vacuum mesh

The RZ and YZ cases have an emitter radius/half-width `R = 1.5 mm` and a
transverse extent `4*R = 6 mm`. The planar case represents the positive-y
half of a symmetric strip: y=0 is a symmetry plane. The RZ case uses r=0 as
the symmetry axis. The outer transverse boundary has a Neumann field condition
and absorbs particles. The measured planar current is for this half strip,
per unit out-of-plane depth.

The local mesh follows the approach in `local_mesh_b0_envelope_zy`:

1. A **filled polygon** covers an assumed expanding pulse envelope, with
   target size `R/6`, a safety buffer `.4*R`, and growth ratio 1.2.
2. A **filled rectangle** resolves injection more finely, from z=0 to D/12
   and transverse coordinate 0 to 1.2R, with target size `R/12`, buffer R/5,
   and growth ratio 1.2.

The background resolution is 40×24. The final conforming triangular mesh is
nonuniform and fixed before PIC. The polygon and rectangle only prescribe
resolution; they are not walls and do not constrain trajectories. Smoothing
is zero, as required by the local P1 backend.

## Verification

All five examples were run for their full 1,500 steps in `tfgpu`. Recorded
emitted current was compared with the requested waveform, the injected charge
was integrated, collection was balanced, and saved vacuum fields were checked
for finite values. The largest continuous-charge discrepancy was about 0.032%
in the RZ case, where the existing radial macro-particle weighting introduces
sampling variation. This is a functionality check, not a mesh/timestep/particle
convergence study.

GUI regression tests also change square → Gaussian → trapezoid, rerun into the
same output folder, and compare the saved model, emitted-current history, and
live plot data. Separate tests change the actual RZ and YZ dialogs and run the
full local-mesh cases. Focused field/table edits, failed saves, failed reruns,
old output on model reopening, and repeated unit changes are covered.
