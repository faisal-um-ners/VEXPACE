# Design a velocity distribution or current pulse

Open **Particle Loading** or select a **beam** under **Emission**. The top of the settings panel
offers **Velocity distribution…**; beam and photo emitters also offer **Current pulse…**. Both
dialogs redraw their figure as you edit. **Apply to model** saves the choice; **Cancel** leaves the
model alone. All inputs are physical SI values; nothing is normalised.

See the [checked vacuum pulse examples](PULSE_EXAMPLES.md) (three 1D shapes and locally refined RZ
and ZY problems) and the equations in [BEAM_PULSES_DISTRIBUTIONS.md](BEAM_PULSES_DISTRIBUTIONS.md).
Changing settings keeps the last run visible with a notice; press Run to calculate the change.

## Velocity of emitted electrons (beam emitters)

The dialog defines the **current-flux distribution P(vₙ)** of the normal speed, vₙ ≥ 0, i.e. which
fraction of the emitted current has normal speed vₙ. Every law emits only out of the surface.

| Choice | P(vₙ) | Inputs |
|---|---|---|
| Keep existing energy / temperature law | beam speed + isotropic Gaussian of √(kT/m) (older models) | energy, temperature |
| Cold | all at the beam speed v_b of the beam energy | energy [eV] |
| Maxwellian (thermal flux) | (m/kT) vₙ exp(−m vₙ²/2kT), shifted by the energy offset | kT [eV], energy [eV] |
| Truncated Gaussian | Gaussian of mean μ and σ, cut at vₙ = 0 and renormalised | μ [m/s] (blank = v_b), σ [m/s] |
| Waterbag (uniform flux) | constant on [v₋, v₊] | v₋, v₊ [m/s] |
| Waterbag (uniform phase density) | ∝ vₙ on [v₋, v₊] (constant f) | v₋, v₊ [m/s] |
| Trapezoid | linear rise, plateau fraction p, linear fall on [v₋, v₊] | v₋, v₊, p |
| Table | straight lines through your (vₙ, weight) points | table, weight = flux or phase density |

The figure shows P(vₙ) in km/s with its mean, the speed range and the corresponding energy range.
Enter a **barrier** depth b [V] to see the transmitted fraction T(b) of the current (electrons with
½ m vₙ² > e b). The transverse components are chosen separately: thermal, cold, Gaussian, waterbag,
trapezoid or table, with widths in m/s.

Fields accept expressions, e.g. `speed_eV(1000)-2e5` … `speed_eV(1000)+2e5` for a waterbag of
±200 km/s about the speed of a 1 keV electron. A table can be imported from CSV (comma, tab or
semicolon); speeds must increase and weights be nonnegative:

```csv
speed,weight
1e5,0
3e5,1
5e5,0
```

The engine samples real velocities and stores u = γv; v ≥ c is rejected. In 1D the transverse
components are zeroed as before. Thermionic, photo, Fowler–Nordheim and SCL emitters keep their own
laws.

## Velocity of loaded particles (Particle Loading)

For a loader the distribution is an **offset about the drift velocity** in each component: cold,
Maxwellian (σ = √(kT/m)), waterbag (±w), trapezoid (half-width w, plateau fraction) or a table of
offsets. Components are independent (Cartesian waterbags, not a sphere in velocity space). Both the
structured and the local triangular loaders support them, including quiet-start quantiles.

## Pulse: when are particles injected?

Open **Current pulse…** and choose **Square**, **Trapezoid** (rise, flat top, fall), **Gaussian**
(FWHM and cutoff n σ), **sin²**, or a **Table** of (time, relative height). Choose ps, ns, µs or s,
the start time, and either the **peak current density** [A/m²] or the **charge per area** [C/m²]
of one pulse; the other is computed. A **pulse train** repeats the pulse N times with a period P.

```csv
time_ns,height
0,0
0.1,1
0.2,0.5
0.3,0
```

Applying the dialog writes J(t) and the emitter's start/stop times; it does not change the
simulation dt or end time. Parameter names stay as references in the generated formula (shown under
**Advanced**), and reopening the dialog or changing units does not grow the expression.

**Time step.** The emitter evaluates J at the middle of each step, Q = J(t + dt/2)·A·dt, with the
solver's own dt, so no time-step parameter or shift is part of the pulse. The pulse needs a numeric
**Study / Solver → dt**; if dt is automatic the dialog and the model check ask you to enter one, and
the model check warns when the shortest pulse feature spans fewer than 20 steps.

The displayed charge is the continuous integral of J(t) for spatial profile 1. Use enough steps
across the pulse and check convergence.

## Compatibility

Models from earlier versions open unchanged in physics where possible:

* `velocity_distribution: "default"` keeps the original sampling path and random sequence.
* Old offset-type emitter distributions are converted once to absolute normal speeds (a waterbag
  ±w about the beam speed becomes max(0, v_b − w) … v_b + w; the old "maxwellian" becomes a truncated
  Gaussian with σ = √(kT/m)). Offsets that pointed into the wall are therefore no longer emitted.
* Old pulse-builder settings (duration + equal ramps, Gaussian cutoff only, normalised tables, and
  the `pic_dt/2` / `sample_dt/2` sampling shift) are converted to the new inputs; with midpoint
  sampling the injected charge per step is the same as before.
