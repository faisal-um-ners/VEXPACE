"""Velocity distributions of loaded and emitted particles, in SI units.

Two different objects are described here, and they must not be mixed:

* **Particle Loading (volume)** - the phase-space density f(v) of a plasma or beam that already
  fills a region.  Each component is the drift plus an independent offset (cold, Maxwellian =
  Gaussian, waterbag, trapezoid or a table).  The engine stores u = gamma*v; offsets are added to
  the drift in u, as for the drift itself.

* **Emission (beam emitter)** - the injected current-flux distribution P(v_n) of the velocity
  NORMAL to the emitting surface, defined for v_n >= 0 only (particles always leave the
  surface).  P is the distribution of the particles crossing the surface per unit time; for a
  one-directional phase density f(v_n), P(v_n) is proportional to v_n f(v_n).  The two
  transverse components (along the surface, out of plane) are independent and symmetric.
  Speeds are sampled as real velocities v and converted to u = gamma*v.

  Normal-velocity laws (Z = normalised position is never used; all inputs are SI):

  ======================  =========================================================  ==================
  kind                    P(v_n), v_n >= 0                                           inputs
  ======================  =========================================================  ==================
  cold                    delta(v_n - v_b),  v_b = speed of the beam energy          energy [eV]
  maxwellian              (m/kT) v exp(-m v^2 / 2kT); with an energy offset E the    temperature [eV],
                          normal energy is raised by eE (v -> sqrt(v^2 + 2eE/m))      energy [eV]
  gaussian                exp(-(v-mu)^2 / 2 sigma^2) / norm, truncated at v = 0      mean [m/s] (blank:
                                                                                     beam speed), sigma
  waterbag                1/(v+ - v-) on v- <= v <= v+   (uniform current flux)      v-, v+ [m/s]
  waterbag_phase          2v/(v+^2 - v-^2) on [v-, v+]   (uniform phase density)     v-, v+ [m/s]
  trapezoid               flat on the central plateau of [v-, v+], linear edges      v-, v+, plateau
  arbitrary               table of (v [m/s], weight); weight = P (flux) or f         table, meaning
                          (phase density, sampled as v f)
  ======================  =========================================================  ==================

  Transmission over a potential barrier phi_min = -b V (needs v_n > sqrt(2 e b V / m)):
  maxwellian T = exp(-e b V / kT); gaussian T = [1 - Phi((v_c - mu)/sigma)] / Phi(mu/sigma);
  waterbag T = clip((v+ - v_c)/(v+ - v-), 0, 1).  ``transmission`` evaluates these.
"""
from __future__ import annotations

import csv
import io
import math

import numpy as np

from .. import constants as C

# Particle Loading: offsets about the drift
KINDS = ("default", "cold", "maxwellian", "waterbag", "trapezoid", "arbitrary")
# Emission: normal component is a current-flux distribution on v_n >= 0
EMISSION_KINDS = ("default", "cold", "maxwellian", "gaussian", "waterbag", "waterbag_phase",
                  "trapezoid", "arbitrary")
TRANSVERSE_KINDS = ("thermal", "cold", "gaussian", "waterbag", "trapezoid", "arbitrary")
TABLE_MEANINGS = ("flux", "phase_density")
DEFAULT_PDF = "-100000, 0\n0, 1\n100000, 0"
DEFAULT_SPEED_PDF = "0, 0\n1e5, 1\n2e5, 1\n3e5, 0"
VERSION = 2            # emitter velocity fields: absolute normal speeds (v_n >= 0)


# --------------------------------------------------------------------------------------------
# tables
def point_rows(text):
    rows = []
    for line in str(text).strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        delimiter = next((d for d in (",", ";", "\t") if d in line), None)
        row = next(csv.reader(io.StringIO(line), delimiter=delimiter)) if delimiter else line.split()
        if len(row) != 2:
            raise ValueError("Each row needs two columns: coordinate, relative height.")
        if not rows and row[0].strip().lower() in ("x", "u", "v", "velocity", "speed", "offset",
                                                   "position", "time", "t"):
            continue
        rows.append(row)
    return rows


def read_points(text, ev):
    """Two columns, comma/semicolon/tab/whitespace separated, optionally with a header."""
    points = [[ev.num(x), ev.num(y)] for x, y in point_rows(text)]
    a = np.asarray(points, dtype=float)
    if a.ndim != 2 or a.shape[0] < 2:
        raise ValueError("Enter at least two points.")
    if not np.isfinite(a).all():
        raise ValueError("All coordinates and heights must be finite.")
    if np.any(np.diff(a[:, 0]) <= 0):
        raise ValueError("Coordinates must increase from one row to the next.")
    if np.any(a[:, 1] < 0) or not np.any(a[:, 1] > 0):
        raise ValueError("Heights must be nonnegative, with at least one positive value.")
    return a


def table_quantile(points, probability):
    """Inverse CDF of the piecewise-linear density through ``points`` (exact within intervals)."""
    x, f = np.asarray(points, float).T
    f = f / f.max()
    dx = np.diff(x)
    areas = dx * (f[:-1] + f[1:]) / 2
    cdf = np.r_[0.0, np.cumsum(areas)]
    if not np.isfinite(cdf[-1]) or cdf[-1] <= 0:
        raise ValueError("The distribution must have a finite positive area.")
    target = np.clip(np.asarray(probability, float), 0, 1) * cdf[-1]
    i = np.clip(np.searchsorted(cdf, target, side="right") - 1, 0, len(dx) - 1)
    a = target - cdf[i]
    slope = (f[i + 1] - f[i]) / dx[i]
    root = np.sqrt(np.maximum(0.0, f[i] ** 2 + 2 * slope * a))
    den = f[i] + root
    offset = np.divide(2 * a, den, out=np.zeros_like(a), where=den > 0)
    value = x[i] + np.clip(offset, 0, dx[i])
    return np.where(target >= cdf[-1], x[-1], value)


def _trapezoid_points(lo, hi, plateau):
    if not np.isfinite(plateau) or not 0 <= plateau <= 1:
        raise ValueError("Plateau fraction must be between 0 and 1.")
    mid, half = 0.5 * (lo + hi), 0.5 * (hi - lo)
    if plateau == 1:
        return np.array([[lo, 1.0], [hi, 1.0]])
    if plateau == 0:
        return np.array([[lo, 0.0], [mid, 1.0], [hi, 0.0]])
    return np.array([[lo, 0.0], [mid - half * plateau, 1.0], [mid + half * plateau, 1.0], [hi, 0.0]])


def _clip_positive(points):
    """Restrict a speed table to v >= 0 (inserting the value at v = 0)."""
    x, f = points.T
    if x[0] >= 0:
        return points
    if x[-1] <= 0:
        raise ValueError("The normal-speed table has no positive speeds: emitted particles must leave "
                         "the surface (v_n > 0).")
    f0 = float(np.interp(0.0, x, f))
    keep = x > 0
    out = np.vstack([[0.0, f0], points[keep]])
    if not np.any(out[:, 1] > 0):
        raise ValueError("The normal-speed table has zero weight at positive speeds.")
    return out


def _flux_from_density(points, refine=16):
    """P(v) = v f(v) for a piecewise-linear phase density f (refined so the product stays accurate)."""
    x, f = points.T
    xs = np.unique(np.concatenate([np.linspace(a, b, refine + 1) for a, b in zip(x[:-1], x[1:])]))
    return np.column_stack([xs, np.abs(xs) * np.interp(xs, x, f)])


# --------------------------------------------------------------------------------------------
# Particle Loading (offsets about the drift)
def component_points(spec, ev, component):
    kind = spec.get("velocity_distribution", "default")
    if kind == "arbitrary":
        return read_points(spec.get(f"velocity_pdf_{component}", DEFAULT_PDF), ev)
    width = ev.num(spec.get("velocity_width", ["1e5"] * 3)[component])
    if not np.isfinite(width) or width < 0:
        raise ValueError("Half-widths must be finite and at least zero.")
    if width == 0:
        return None
    if kind == "waterbag":
        return np.array([[-width, 1.0], [width, 1.0]])
    return _trapezoid_points(-width, width, ev.num(spec.get("velocity_plateau", "0.5")))


def validate_distribution(spec, ev, emitter=False):
    """Raise ValueError if the distribution of a loader (or a beam emitter) cannot be sampled."""
    kind = spec.get("velocity_distribution", "default")
    if emitter:
        if kind not in EMISSION_KINDS:
            raise ValueError(f"Unknown emission velocity distribution '{kind}'.")
        normal_points(spec, ev)
        for c in (1, 2):
            transverse_points(spec, ev, c)
        return
    if kind not in KINDS:
        raise ValueError(f"Unknown velocity distribution '{kind}'.")
    if kind in ("waterbag", "trapezoid", "arbitrary"):
        for c in range(3):
            p = component_points(spec, ev, c)
            if p is not None:
                table_quantile(p, [0.5])


def sample_offsets(spec, ev, rng, count, *, quiet=False, ppc=1, cells=None, slots=None):
    """Particle Loading: cold / bounded / tabulated offsets (thermal laws use the loader's sampler)."""
    kind = spec.get("velocity_distribution", "default")
    validate_distribution(spec, ev)
    out = np.zeros((3, count))
    if kind == "cold":
        return out
    if kind not in ("waterbag", "trapezoid", "arbitrary"):
        raise ValueError("Thermal velocities must use the existing Maxwellian sampler.")
    quiet = quiet and ppc >= 16 and cells is not None and slots is not None
    if quiet:
        _, block = np.unique(cells, return_inverse=True)
        nb = int(block.max()) + 1 if count else 0
        quant = (np.arange(ppc) + 0.5) / ppc
    for c in range(3):
        points = component_points(spec, ev, c)
        if points is None:
            continue
        if quiet:
            perm = np.argsort(rng.random((nb, ppc)), axis=1)
            prob = quant[perm[block, slots]]
        else:
            prob = rng.random(count)
        out[c] = table_quantile(points, prob)
    return out


# --------------------------------------------------------------------------------------------
# Emission (normal component = current-flux distribution on v_n >= 0)
def species_mass(spec_species, ev):
    from ..particles.species import Species
    return Species(spec_species, ev).m


def beam_speed(spec, ev, m):
    """Speed [m/s] of the beam energy (eV) of an emitter."""
    E = ev.num(str(spec.get("energy", "")).strip() or "0")     # blank = 0 eV
    if not math.isfinite(E) or E < 0:
        raise ValueError("Beam energy must be finite and at least zero.")
    gam = 1.0 + E * C.e / (m * C.c ** 2)
    return C.c * math.sqrt(max(1.0 - 1.0 / gam ** 2, 0.0))


def _num(spec, ev, key, default, name, minimum=None):
    v = ev.num(spec.get(key, default) if str(spec.get(key, "")).strip() != "" else default)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite.")
    if minimum is not None and v < minimum:
        raise ValueError(f"{name} must be at least {minimum:g}.")
    return v


def _bounds(spec, ev):
    lo = _num(spec, ev, "velocity_min", "0", "Lowest normal speed v-", 0.0)
    hi = _num(spec, ev, "velocity_max", "2e5", "Highest normal speed v+", 0.0)
    if hi <= lo:
        raise ValueError("The highest normal speed v+ must exceed the lowest v-.")
    return lo, hi


def normal_points(spec, ev, m=C.me):
    """Piecewise-linear current-flux table P(v_n) for the table-based laws, or None for the
    analytic ones (cold, maxwellian, gaussian, default)."""
    kind = spec.get("velocity_distribution", "default")
    if kind in ("default", "cold"):
        return None
    if kind == "maxwellian":
        _num(spec, ev, "temperature", "0", "Temperature", 0.0)
        return None
    if kind == "gaussian":
        _num(spec, ev, "velocity_spread", "1e5", "Speed spread sigma", 0.0)
        if str(spec.get("velocity_mean", "")).strip():
            _num(spec, ev, "velocity_mean", "0", "Mean normal speed")
        return None
    if kind == "waterbag":
        lo, hi = _bounds(spec, ev)
        return np.array([[lo, 1.0], [hi, 1.0]])
    if kind == "waterbag_phase":
        lo, hi = _bounds(spec, ev)
        return np.array([[lo, lo], [hi, hi]]) if lo > 0 else np.array([[0.0, 0.0], [hi, hi]])
    if kind == "trapezoid":
        lo, hi = _bounds(spec, ev)
        return _trapezoid_points(lo, hi, ev.num(spec.get("velocity_plateau", "0.5")))
    if kind == "arbitrary":
        pts = read_points(spec.get("velocity_pdf_0", DEFAULT_SPEED_PDF), ev)
        pts = _clip_positive(pts)
        if spec.get("velocity_table_kind", "flux") == "phase_density":
            pts = _flux_from_density(pts)
        if not np.any(pts[:, 1] > 0):
            raise ValueError("The normal-speed table has zero weight.")
        return pts
    raise ValueError(f"Unknown emission velocity distribution '{kind}'.")


def transverse_points(spec, ev, component):
    """Offset table of a transverse component (1 = along the surface, 2 = out of plane), or None
    for the analytic (thermal, gaussian) and cold laws."""
    kind = spec.get("transverse_distribution", "thermal")
    if kind not in TRANSVERSE_KINDS:
        raise ValueError(f"Unknown transverse distribution '{kind}'.")
    if kind in ("thermal", "cold"):
        if kind == "thermal":
            _num(spec, ev, "temperature", "0", "Temperature", 0.0)
        return None
    if kind == "arbitrary":
        return read_points(spec.get(f"velocity_pdf_{component}", DEFAULT_PDF), ev)
    widths = spec.get("transverse_width", ["0", "0"])
    w = ev.num(widths[component - 1])
    if not math.isfinite(w) or w < 0:
        raise ValueError("Transverse widths must be finite and at least zero.")
    if w == 0 or kind == "gaussian":
        return None
    if kind == "waterbag":
        return np.array([[-w, 1.0], [w, 1.0]])
    return _trapezoid_points(-w, w, ev.num(spec.get("velocity_plateau", "0.5")))


def sample_normal(spec, ev, rng, n, m):
    """Normal speeds v_n >= 0 [m/s] distributed as the current flux P(v_n)."""
    kind = spec.get("velocity_distribution", "default")
    if kind == "cold":
        return np.full(n, beam_speed(spec, ev, m))
    if kind == "maxwellian":
        kT = _num(spec, ev, "temperature", "0", "Temperature", 0.0) * C.e
        v2 = -2.0 * kT / m * np.log(1.0 - rng.random(n))          # Rayleigh: P ~ v exp(-mv^2/2kT)
        E = _num(spec, ev, "energy", "0", "Energy offset", 0.0)
        if E > 0:                                                   # accelerated by e*E normal to the surface
            K = 0.5 * m * v2 + E * C.e
            gam = 1.0 + K / (m * C.c ** 2)
            return C.c * np.sqrt(1.0 - 1.0 / gam ** 2)
        return np.sqrt(v2)
    if kind == "gaussian":
        from scipy.special import ndtr, ndtri
        sig = _num(spec, ev, "velocity_spread", "1e5", "Speed spread sigma", 0.0)
        mu = (_num(spec, ev, "velocity_mean", "0", "Mean normal speed")
              if str(spec.get("velocity_mean", "")).strip() else beam_speed(spec, ev, m))
        if sig == 0:                       # cold: all at the mean speed (at rest if the mean is <= 0)
            return np.full(n, max(mu, 0.0))
        p0 = ndtr(-mu / sig)                                       # probability mass below v = 0
        if p0 > 1 - 1e-12:
            raise ValueError("The Gaussian has (almost) no weight at positive speeds; raise the mean.")
        return np.maximum(mu + sig * ndtri(p0 + rng.random(n) * (1 - p0)), 0.0)
    if kind == "waterbag_phase":
        lo, hi = _bounds(spec, ev)
        return np.sqrt(lo ** 2 + rng.random(n) * (hi ** 2 - lo ** 2))
    pts = normal_points(spec, ev, m)
    if pts is None:
        raise ValueError(f"Distribution '{kind}' has no normal-speed table.")
    return table_quantile(pts, rng.random(n))


def sample_transverse(spec, ev, rng, n, m, component):
    kind = spec.get("transverse_distribution", "thermal")
    if kind == "cold":
        return np.zeros(n)
    if kind == "thermal":
        T = _num(spec, ev, "temperature", "0", "Temperature", 0.0)
        return np.sqrt(T * C.e / m) * rng.standard_normal(n) if T > 0 else np.zeros(n)
    if kind == "gaussian":
        w = ev.num(spec.get("transverse_width", ["0", "0"])[component - 1])
        return w * rng.standard_normal(n)
    pts = transverse_points(spec, ev, component)
    return np.zeros(n) if pts is None else table_quantile(pts, rng.random(n))


def sample_emission(spec, ev, rng, n, m):
    """(u_n, u_t, u_o) = gamma * (v_n, v_t, v_o) of n emitted particles."""
    vn = sample_normal(spec, ev, rng, n, m)
    vt = sample_transverse(spec, ev, rng, n, m, 1)
    vo = sample_transverse(spec, ev, rng, n, m, 2)
    v2 = vn ** 2 + vt ** 2 + vo ** 2
    if np.any(v2 >= C.c ** 2):
        raise ValueError("A sampled velocity reaches the speed of light; check the speeds and widths "
                         "(they are velocities v in m/s, not gamma*v).")
    gam = 1.0 / np.sqrt(1.0 - v2 / C.c ** 2)
    return gam * vn, gam * vt, gam * vo


def normal_pdf_curve(spec, ev, m, npts=601):
    """(v, P(v)) of the normal current-flux distribution for plots (area 1); cold -> (v_b, None)."""
    kind = spec.get("velocity_distribution", "default")
    if kind in ("cold", "default"):
        return np.array([beam_speed(spec, ev, m)]), None
    if kind == "maxwellian":
        kT = _num(spec, ev, "temperature", "0", "Temperature", 0.0) * C.e
        E = _num(spec, ev, "energy", "0", "Energy offset", 0.0)
        if kT == 0:
            return np.array([beam_speed(spec, ev, m)]), None
        s = math.sqrt(kT / m)
        w = np.linspace(0, 6 * s, npts)                       # thermal speed before acceleration
        p = w / s ** 2 * np.exp(-w ** 2 / (2 * s ** 2))
        if E > 0:                                             # v = sqrt(w^2 + 2eE/m): P(v) = P(w) dw/dv = P(w) v/w
            v = np.sqrt(w ** 2 + 2 * E * C.e / m)
            p = v / s ** 2 * np.exp(-w ** 2 / (2 * s ** 2))
            return v, p / np.trapezoid(p, v)
        return w, p
    if kind == "gaussian":
        from scipy.special import ndtr
        sig = _num(spec, ev, "velocity_spread", "1e5", "Speed spread sigma", 0.0)
        mu = (_num(spec, ev, "velocity_mean", "0", "Mean normal speed")
              if str(spec.get("velocity_mean", "")).strip() else beam_speed(spec, ev, m))
        if sig == 0:
            return np.array([max(mu, 0.0)]), None
        v = np.linspace(max(0.0, mu - 5 * sig), mu + 5 * sig, npts)
        p = np.exp(-0.5 * ((v - mu) / sig) ** 2) / (math.sqrt(2 * math.pi) * sig * ndtr(mu / sig))
        return v, p
    if kind == "waterbag_phase":
        lo, hi = _bounds(spec, ev)
        v = np.linspace(lo, hi, npts)
        return v, 2 * v / (hi ** 2 - lo ** 2)
    pts = normal_points(spec, ev, m)
    x, f = pts.T
    f = f / np.trapezoid(f, x)
    return x, f


def transmission(spec, ev, m, barrier_eV):
    """Fraction of the emitted current with enough normal energy to cross a potential minimum
    -barrier_eV (volts) below the emitter: v_n > v_c = sqrt(2 e b / m)."""
    if barrier_eV <= 0:
        return 1.0
    vc = math.sqrt(2 * barrier_eV * C.e / m)
    v, p = normal_pdf_curve(spec, ev, m, 4001)
    if p is None:
        return float(v[0] > vc)
    cdf = np.concatenate([[0.0], np.cumsum(np.diff(v) * (p[1:] + p[:-1]) / 2)])
    return float(np.clip(1.0 - np.interp(vc, v, cdf / cdf[-1]), 0.0, 1.0))


# --------------------------------------------------------------------------------------------
# files written before the emission laws were defined as current fluxes (version < 2)
def migrate_emitter(spec, mass_expr):
    """Convert the old offset-about-the-beam-speed emitter fields to absolute normal speeds.

    Old files added symmetric offsets to the beam speed, so a waterbag of half-width w around a
    beam speed v_b emitted speeds v_b - w ... v_b + w, some of them negative (into the wall).  The
    same intent is the waterbag max(0, v_b - w) ... v_b + w; the old 'maxwellian' (a Gaussian of
    sigma = sqrt(kT/m) about v_b in every component) becomes a truncated Gaussian normal speed
    with thermal transverse components."""
    d = dict(spec)
    if str(d.get("velocity_version", "1")) == str(VERSION):
        return d
    d["velocity_version"] = VERSION
    if d.get("model", "beam") != "beam":
        return d
    kind = d.get("velocity_distribution", "default")
    vb = f"speed_eV(({d.get('energy', '0')}), ({mass_expr}))"
    widths = list(d.get("velocity_width", ["1e5"] * 3)) + ["0"] * 3
    if kind in ("waterbag", "trapezoid"):
        w0 = widths[0]
        d["velocity_min"] = f"max(0, {vb} - ({w0}))"
        d["velocity_max"] = f"{vb} + ({w0})"
        nonzero = any(str(w).strip() not in ("0", "0.0", "") for w in widths[1:3])
        d["transverse_distribution"] = kind if nonzero else "cold"
        d["transverse_width"] = [widths[1], widths[2]]
    elif kind == "arbitrary":
        rows = point_rows(d.get("velocity_pdf_0", DEFAULT_PDF))
        d["velocity_pdf_0"] = "\n".join(f"{vb} + ({x.strip()}), {y.strip()}" for x, y in rows)
        d["velocity_table_kind"] = "flux"
        d["transverse_distribution"] = "arbitrary"
    elif kind == "maxwellian":
        T = d.get("temperature", "0")
        d["velocity_distribution"] = "gaussian"
        d["velocity_mean"] = ""
        d["velocity_spread"] = f"sqrt(({T})*e/({mass_expr}))"
        d["transverse_distribution"] = "thermal"
    elif kind == "cold":
        d["transverse_distribution"] = "cold"
    return d
