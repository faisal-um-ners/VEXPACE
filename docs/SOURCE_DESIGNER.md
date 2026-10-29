# Design a velocity distribution or current pulse

Open **Particle Loading** or select a **beam** under **Emission**. The top of
the settings panel now offers **Velocity distribution…**. Beam and photo
emitters also offer **Current pulse…**. Both dialogs update their figure as
you edit. **Apply to model** saves the choice; **Cancel** leaves the model alone.

See the [five checked vacuum pulse examples](PULSE_EXAMPLES.md) for three 1D
shapes and locally refined RZ and YZ problems. Changing settings clears the old
result display; press Run to calculate the changed pulse.

Try **Examples > source_designer_beam_1d** for a ready-to-edit Gaussian pulse
with a waterbag velocity spread. This is an illustrative setup, not a benchmark.

## Velocity: how different are the initial particle speeds?

The drift in Particle Loading, or the energy in beam Emission, sets the central
speed. The distribution adds a spread around it. The plot shows this **offset**,
not the final speed after fields accelerate the particles.

| Choice | Meaning | Main input |
|---|---|---|
| Keep existing energy / temperature law | Preserve the previous loading or beam rule | Temperature, in eV |
| Cold | No random spread | None |
| Maxwellian | Each component has a Gaussian bell-shaped distribution | Temperature kT, in eV |
| Waterbag | Offsets within a bounded range are equally likely | Half-width for each component, in m/s |
| Trapezoid | A flat central region with linearly decreasing edges | Half-widths and plateau fraction |
| Custom | A probability density joined by straight lines between your points | A two-column table for each component |

A half-width of 100000 means offsets range from −100000 to +100000 m/s.
A half-width of zero means cold in that component. Trapezoid plateau fraction
0 gives a triangle; 1 gives a waterbag. A custom table can be asymmetric or have
several peaks. Heights are relative, must be nonnegative, and are normalized
automatically. Coordinates must increase. For example:

```csv
offset,height
-100000,0
0,1
100000,0
```

**Import CSV…** also accepts tab- or semicolon-separated data. You can edit the
table directly, add points, or remove selected points. Parameter expressions
are allowed in cells.

Components are independent: these are Cartesian component waterbags, not a
uniform sphere in velocity space. Loading uses the geometry's z, y/r, x/theta
components. Beam emission uses normal, along-surface, and out-of-plane
components before rotation into the geometry. The engine convention is
u = gamma*v (m/s); at low speeds this equals v. Existing species motion
constraints still apply. In 1D emission the along-surface component is zeroed
as before. Arbitrary component tables describe offsets, so their mean need
not be zero.

The Maxwellian standard deviation is sqrt(kT/m). This is a Gaussian for each
component; the three-dimensional speed magnitude has a different distribution.
Thermionic emission retains its flux-weighted outward normal law and Gaussian
transverse components. Photoemission retains its excess-energy and cosine
angular law. Custom velocity choices apply to initial loading and prescribed
beam emission, not to those model-specific laws or SCL emission.

## Pulse: when are particles injected?

Open **Current pulse…** and choose:

- **Square:** constant current during the selected duration.
- **Trapezoid:** a linear rise, flat top, and equal linear fall.
- **Gaussian:** a bell curve truncated at its specified cutoff.
- **Custom:** a two-column table of relative time positions and heights.

Choose ps, ns, microseconds, or seconds; enter a start time and the **full on-window**
duration. Choose whether to set the **peak current density** in A/m² or the
**charge per area** in C/m². The other quantity is calculated automatically.
Changing this entry mode preserves the current pulse's strength.

For a trapezoid, each ramp must fit within half the full duration. For a Gaussian,
the full duration spans both cutoffs; its FWHM is displayed separately. A cutoff
of 3 means three standard deviations on each side. For a custom pulse, position
0 is the start and 1 is the end:

```csv
position,height
0,0
0.3,1
0.7,0.5
1,0
```

The highest point sets relative height 1. At most 64 pulse points are supported.
An existing expression is initially preserved and can be previewed over a chosen
time window. Choosing a preset and applying replaces J(t) and the emitter's start
and stop times. It does not change the simulation timestep or end time. The
generated formula is available under **Advanced: evaluation and expression**.
Parameter references remain in that formula and in the time gates. Reopening
the dialog or changing time units preserves those references and does not add
repeated unit-conversion expressions.

The displayed charge is the continuous integral of J(t), for spatial profile 1;
an actual simulation samples J at timesteps, and the spatial profile multiplies
the emitted current. Use enough timesteps across the pulse and check convergence.
The existing short-pulse examples use an explicit sample_dt/2 evaluation offset;
the Advanced offset preserves this convention when selected. Zero remains the
default for new pulses. Existing examples are never rewritten just by opening
the editor, and manually edited current expressions remain authoritative.

## Compatibility

Existing JSON models receive `velocity_distribution: "default"`, which takes
the original sampling path with the original random-number sequence. The new
bounded/table distributions are opt-in. Both structured and local triangular
particle loaders support them, including quiet-start quantiles. Beam emission
uses the same charge, weight, time, surface and acceleration rules as before.
No Poisson, electromagnetic, deposition, gather, pusher, or thermionic/photo/SCL
current law is changed. The expression helper adds `erf` for exact truncated
Gaussian charge normalization.
