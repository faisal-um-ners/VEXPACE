# Checked vacuum pulse examples

Open **File → Examples**, select one of the following, and select
**Emission → pulsed_beam → Current pulse…**. Change a shape or value, click
**Apply to model**, then **Run**. The last run remains visible when settings change, with a notice that
it used earlier settings. Plots are replaced when the next run starts. A cancelled or failed save cancels Run, rather than running the old file.

| Example file | Coordinates | Pulse shape | Emitted normal-speed law | Mesh |
|---|---|---|---|---|
| `source_designer_beam_1d.pic.json` | 1D z | Gaussian, FWHM 0.1 ns, ±3σ | Gaussian (flux), μ = v_b, σ = 200 km/s | 120 uniform cells |
| `source_designer_square_1d.pic.json` | 1D z | Square, 0.3 ns | uniform-flux waterbag v_b ± 200 km/s | 120 uniform cells |
| `source_designer_trapezoid_1d.pic.json` | 1D z | Trapezoid 0.06/0.18/0.06 ns | trapezoid on v_b ± 200 km/s, plateau 0.5 | 120 uniform cells |
| `source_designer_pulse_rz.pic.json` | Axisymmetric z,r | Gaussian, FWHM 0.1 ns, ±3σ | Maxwellian flux, kT = 0.2 eV, thermal transverse | Local P1 triangles |
| `source_designer_pulse_zy.pic.json` | Cartesian z,y | Trapezoid 0.06/0.18/0.06 ns | waterbag v_b ± 200 km/s, transverse waterbag 200 km/s | Local P1 triangles |
| `Gaussian_VD_Barrier.pic.json` | 1D z | constant 1e5 A/m² | Gaussian cut at 0 (as you set it) | 512 uniform cells |

v_b is the speed of the 1 keV beam energy (`speed_eV(beam_energy)`). These are illustrative beam
transport problems, not published benchmark cases. Each has a labelled **vacuum** geometry object over
the gap (first in the object list, so it never carves electrodes); it does not change the fields. The
current is prescribed by the **beam** emission model and the self-consistent space-charge field is
solved; "vacuum" does not turn off the particles' own field.

* **1D drifts:** 15 mm grounded gap, 1 keV electrons, peak 10 A/m², start 0.1 ns.
* **RZ small disk:** emitter radius R = 0.1 mm at the cathode of a 10 mm, 10 kV gap; peak 1e4 A/m²
  (below the planar Child–Langmuir value 2.3e4 A/m²); outer radius 20R (Neumann, absorbing).
* **ZY sheet beam:** half-width R = 1.5 mm, 15 mm grounded gap, 1 keV, peak 100 A/m²; y = 0 is a
  symmetry plane, so the measured current is per unit depth for the half strip.
* **Gaussian_VD_Barrier:** injection far above the space-charge limit of a 15 mm, 100 V gap
  (Child–Langmuir 10.4 A/m²), so a potential minimum forms in front of the emitter and reflects most
  electrons. The model check reports this on purpose; compare the transmitted fraction with T(b) in
  the Velocity distribution dialog.

## Pulse and observation times

- Time step: **dt = 1 ps** entered directly in Study / Solver (no extra parameter).
- The emitter samples J at the middle of every step, Q = J(t + dt/2)·A·dt; the J(t) expressions
  contain no time shift.
- Observation ends at **1.5 ns** (1,500 steps), after the pulse has crossed the domain.
- Pulse controls hold the source's timing and strength; global parameters hold geometry, beam
  energy and observation end.

At the final time the domain is empty: the pulse has reached the collector.
The history still shows its emission and arrival. To see spatial particles or
fields, use the Results snapshot slider to inspect an earlier saved frame,
for example around 0.2–1.0 ns.

## Two-dimensional vacuum mesh

The local triangle mesh follows the approach in `local_mesh_b0_envelope_zy`:

1. A **filled polygon** covers the assumed expanding pulse envelope (RZ: target size R/2; ZY: R/8),
   buffer 0.4R, growth 1.2.
2. A **filled rectangle** resolves the emission region more finely (RZ: z 0…D/10, r 0…1.2R, size
   R/6; ZY: z 0…D/12, y 0…1.2R, size R/12), buffer R/5, growth 1.2.

The background mesh is 40×8 (RZ, nearly square cells) and 40×24 (ZY). The conforming triangular mesh
is fixed before PIC; the polygon and rectangle only prescribe resolution and do not constrain
trajectories. Smoothing is zero, as required by the local P1 backend. The model check warns if a
refinement size is not smaller than the background cell (it would have no effect).

## Verification

The five pulse examples run for their full 1,500 steps. Recorded
emitted current was compared with the requested waveform, the injected charge
was integrated, collection was balanced, and saved vacuum fields were checked
for finite values. In the RZ case the emitted charge agrees with the requested 3.33e-14 C to 0.1 %. This is a functionality check, not a mesh/timestep/particle
convergence study.

GUI regression tests also change square → Gaussian → trapezoid, rerun into the
same output folder, and compare the saved model, emitted-current history, and
live plot data. Separate tests change the actual RZ and YZ dialogs and run the
full local-mesh cases. Focused field/table edits, failed saves, failed reruns,
old output on model reopening, and repeated unit changes are covered.

Higher-particle local-mesh runs also cover newborn particles crossing a wall
during their fractional emission step. Existing reflection, periodic, axis
and absorption rules are applied before the first local-mesh charge deposit;
absorbed charge is recorded in the existing collection totals. This fixes a
rare out-of-mesh failure without changing emission sampling, pushers, charge
deposition weights or the field equations. Tests cover both ZY and RZ.
