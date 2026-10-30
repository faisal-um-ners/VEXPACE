# Short pulses, beam injection and velocity distributions

This guide explains how to create **short electron pulses** and choose the **velocity distribution of
emitted electrons** in VEXPACE. All inputs are physical SI quantities (seconds, A/m², C/m², m/s, eV);
nothing in the solver is normalised.

![Three temporal current profiles: square, trapezoidal and Gaussian](images/short_pulse_shapes.svg)

## 1. Where to enter a short pulse

1. Open **File → Examples** and choose a `source_designer_*` or `short_pulse_*` model, or create an
   **electrostatic** diode.
2. Select **Emission** and set **Emission model = beam**.
3. Click **Current pulse…** (recommended) or type **Current density J(t) [A/m²]** as a time expression.
4. Click **Velocity distribution…** to choose the emitted normal-speed law (section 4).
5. In **Study / Solver**, enter the time step **dt** as a number. A pulse needs a fixed dt: with
   automatic dt the model check asks you to enter one, and it warns when the shortest pulse feature
   (rise, fall, FWHM or duration) spans fewer than 20 steps.

**How the emitter samples J(t).** `t` is the simulation time in seconds. In each step (t, t+dt] the
emitter injects the charge

```text
Q = J(t + dt/2) * A * dt          (midpoint rule)
```

so the injected charge of a pulse is centred on the step and the solver's own dt is always used. No
time-shift parameter (such as the former `pic_dt/2` or `sample_dt/2`) belongs in the J(t) expression.
Files written by older versions are converted automatically when they are opened.

## 2. Pulse shapes (Current pulse… dialog)

With τ = t − t₀ (t₀ = start time) and peak current density J_p:

| Shape | J(t) for one pulse | Length T | ∫J dt per pulse |
|---|---|---|---|
| Square | J_p for 0 ≤ τ < T | duration | J_p T |
| Trapezoid | linear rise over t_r, flat top t_h, linear fall t_f | t_r + t_h + t_f | J_p (t_r/2 + t_h + t_f/2) |
| Gaussian | J_p exp(−(τ − T/2)²/2σ²), σ = FWHM / (2√(2 ln 2)) | 2nσ (cut at ±nσ) | J_p σ√(2π) erf(n/√2) |
| sin² | J_p sin²(πτ/T) (smooth edges, FWHM = T/2) | duration | J_p T/2 |
| Table | straight lines through (τ [time unit], relative height) | last time | area of the table × J_p |

* **Strength:** enter either the **peak current density** [A/m²] or the **charge per area** of one
  pulse [C/m²]; the other is computed (Q₁ = J_p ∫shape dτ).
* **Pulse train:** number of pulses N and period P ≥ T; the train carries N Q₁.
* **Units:** ps, ns, µs or s in the dialog; the model stores seconds. Parameter names typed in the
  fields stay as references in the generated expression, so changing a parameter later changes the
  pulse.
* The generated expression and its start/stop times are shown under **Advanced**. A J(t) typed by
  hand remains authoritative.

Example of a generated Gaussian (FWHM 0.1 ns, cut at ±3σ, peak 10 A/m², start 0.1 ns):

```text
(10)*(exp(-0.5*(((t-(1e-10))-(3)*((1e-10)/2.3548200450309493))/((1e-10)/2.3548200450309493))**2))*where(((t-(1e-10))>=0)&((t-(1e-10))<(2*(3)*((1e-10)/2.3548200450309493))),1,0)
```

### Comparing shapes fairly

Keep the **injected charge per area** constant (choose "charge per area" in the dialog). The support
duration is not the FWHM; a Gaussian needs an explicit cutoff. Inspect collected current separately
from injected current.

## 3. Ready-to-run 2025–2026 short-pulse models

These are representative paper-parameter examples, **not exact reproductions of published plots or fitted limiting currents**. Each uses the existing 1D electrostatic PIC solver.

| Model | Pulse | Physical setting |
|---|---|---|
| [2025 diode · Square](../examples/short_pulse_diode_2025_square_1d.pic.json) | Square | 1.5 mm, 30 kV, cold emission |
| [2025 diode · Trapezoidal](../examples/short_pulse_diode_2025_trapezoid_1d.pic.json) | Trapezoid | 1.5 mm, 30 kV, cold emission |
| [2025 diode · Gaussian](../examples/short_pulse_diode_2025_gaussian_1d.pic.json) | Gaussian | 1.5 mm, 30 kV, cold emission |
| [2026 drift · Square](../examples/short_pulse_drift_2026_square_1d.pic.json) | Square | 1 cm drift, grounded plates, 1 keV injection |
| [2026 drift · Trapezoidal](../examples/short_pulse_drift_2026_trapezoid_1d.pic.json) | Trapezoid | 1 cm drift, grounded plates, 1 keV injection |
| [2026 drift · Gaussian](../examples/short_pulse_drift_2026_gaussian_1d.pic.json) | Gaussian | 1 cm drift, grounded plates, 1 keV injection |

These files and the additional assumptions are documented in [SHORT_PULSE_EXAMPLES.md](../examples/SHORT_PULSE_EXAMPLES.md). In particular, the drift cases have unresolved normalization differences relative to the referenced publication; do not describe them as validated exact paper reproductions.

## 4. Velocity distribution of emitted electrons (Velocity distribution… dialog)

![Emission flux laws P(v_n)](images/velocity_distributions.svg)

**Temporal current shape and velocity distribution are separate choices.** A Gaussian current pulse
does not give Gaussian velocities.

For a **beam** emitter the dialog defines the **current-flux distribution P(vₙ)** of the normal speed:
the fraction of the emitted *current* carried by electrons with normal speed vₙ (vₙ ≥ 0, always out of
the surface). This is the quantity used in emission theory; it differs from the density
distribution f by one factor of vₙ (P ∝ vₙ f). The two transverse components are chosen separately.
Speeds are real velocities in m/s; VEXPACE samples v and stores u = γv.

| Law | P(vₙ), vₙ ≥ 0 | Inputs |
|---|---|---|
| Cold | δ(vₙ − v_b), v_b = c√(1 − 1/γ²), γ = 1 + eE/mc² | beam energy E [eV] |
| Maxwellian (thermal flux) | (m/kT) vₙ exp(−m vₙ²/2kT); mean √(πkT/2m). With E > 0: vₙ → √(vₙ² + 2eE/m) | kT [eV], energy offset E [eV] |
| Gaussian (general) | G = exp(−(vₙ − μ)²/2σ²) on v_min ≤ vₙ ≤ v_max; P = G (shape = flux) or P ∝ vₙ G (shape = phase density) | μ [m/s] (blank = v_b), σ, cut-offs v_min ≥ 0, v_max (blank = none), shape |
| Waterbag | uniform on [v₋, v₊]: P = 1/(v₊ − v₋) (flux) or P = 2vₙ/(v₊² − v₋²) (phase density, constant f, e.g. Ignatov 2025) | v₋, v₊ [m/s], shape |
| Trapezoid | linear rise, plateau (fraction p of [v₋, v₊]), linear fall; shape of P or of f | v₋, v₊, p, shape |
| Table | straight lines through (vₙ [m/s], weight); weight = flux P or phase density f | table |

**Shape describes: flux or phase density.** For the Gaussian, waterbag, trapezoid and table laws you
choose whether the shape you enter is the current flux P(vₙ) itself or the phase-space density f(vₙ)
at the surface (then P = vₙ f, because faster particles cross the surface more often). The Maxwellian
is the special case of a Gaussian with μ = 0, σ = √(kT/m) and shape = phase density; a Gaussian with
μ ≠ 0 and shape = phase density is a drifting-Maxwellian flux (WarpX `gaussianflux`).

**Why the cut at vₙ = 0?** An emitter sits on a wall, so only particles moving into the domain can be
emitted; a negative normal speed would put the particle straight back into the wall. Codes therefore
emit only the forward part (WarpX `gaussianflux`, thermionic and beam emitters in XOOPIC/VSim). When
μ ≫ σ the cut changes nothing; when μ ≲ 2σ it matters, and the injected current J is carried by the
forward part only. Use v_min > 0 to also remove slow particles, or v_max to remove a fast tail.

Expressions are allowed, e.g. `speed_eV(1000)` (speed of a 1 keV electron), `speed_eV(1000)-2e5`, or
`speed_eV(E, mp)` for another mass; `energy_eV(v)` converts back.

**Transmission over a barrier.** If space charge forms a potential minimum b volts below the emitter
(a virtual cathode), only electrons with ½ m vₙ² > e b pass. The dialog shows T(b), the transmitted
fraction of the emitted current, for the chosen law, e.g.

```text
Maxwellian:          T = exp(-e b / kT)
Gaussian (flux, cut at 0):  T = [1 - Phi((v_c - mu)/sigma)] / Phi(mu/sigma),   v_c = sqrt(2 e b / m)
uniform flux:               T = clip((v+ - v_c)/(v+ - v-), 0, 1)
```

**Transverse components** (beam emitters): thermal (σ = √(kT/m)), cold, Gaussian, waterbag or
trapezoid of a given width, or a table. They are independent of the normal law.

**Older models.** The previous "offset about the beam speed" inputs could launch particles into the
wall (a waterbag ±w about zero energy sends half the electrons backwards). When such a file is opened
it is converted once: waterbag/trapezoid → speeds max(0, v_b − w) … v_b + w; the old "maxwellian"
(a Gaussian about v_b) → Gaussian (flux, cut at 0) with σ = √(kT/m) and thermal transverse components;
tables → absolute speeds. The **Legacy (older files)** choice keeps the original beam rule unchanged; new models should use
one of the laws above.

### Other sources and loaders

| VEXPACE input | Behaviour |
|---|---|
| **Particle Loading**, temperature kT | Gaussian of σ = √(kT/m) in each component about the drift (Maxwell–Boltzmann speed) |
| **Particle Loading → Velocity distribution…** | cold, Maxwellian, waterbag, trapezoid or table **offsets** about the drift, per component |
| **Emission → thermionic** | flux-weighted half-Maxwellian normal component, thermal transverse components |
| **Emission → photo** | uniform excess energy up to the maximum, Lambertian angles |

The loader temperature is k_B T **in eV**, not kelvin.

## 5. Diagnostic workflow

1. Plot the source input `J(t)` and check the total injected charge before running.
2. Compare **emitted current** and **collected current**; these need not match during particle transit or reflection.
3. Inspect potential, current history, particle snapshots and phase space.
4. Reduce the timestep and increase particles per cell to check numerical convergence.
5. For distributions, plot injected-particle velocity histograms and compare them with the intended P(vₙ) (remember that a histogram of particles in a slab near the emitter shows the density, ∝ P/vₙ). Do not infer the injected PDF from a downstream beam histogram without accounting for acceleration and filtering.

See also the full [VEXPACE user guide](USER_GUIDE.md), [numerical methods](THEORY.md), and [short-pulse verification notes](../examples/SHORT_PULSE_VERIFICATION.json).

**Current density.** The velocity law only shapes the speeds: P(vₙ) is normalised, so the emitted
current is always J(t)·A, with J set in **Current density J(t)** or with **Current pulse…**.
