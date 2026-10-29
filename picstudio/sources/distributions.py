"""Opt-in independent component distributions in the engine's u = gamma*v coordinates.

The default paths in loaders/emitters remain unchanged. Table PDFs are linear
between knots; their inverse CDF is analytic within each interval.
"""
from __future__ import annotations

import csv
import io
import numpy as np

KINDS = ("default", "cold", "maxwellian", "waterbag", "trapezoid", "arbitrary")
DEFAULT_PDF = "-100000, 0\n0, 1\n100000, 0"


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
        if not rows and row[0].strip().lower() in ("x", "u", "v", "velocity", "offset", "position", "time", "t"):
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
    x, f = points.T
    # Scaling heights prevents overflow and does not change the normalized PDF.
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
    # Rationalized quadratic inverse; also handles a constant positive density.
    den = f[i] + root
    offset = np.divide(2 * a, den, out=np.zeros_like(a), where=den > 0)
    value = x[i] + np.clip(offset, 0, dx[i])
    return np.where(target >= cdf[-1], x[-1], value)


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
    plateau = ev.num(spec.get("velocity_plateau", "0.5"))
    if not np.isfinite(plateau) or not 0 <= plateau <= 1:
        raise ValueError("Plateau fraction must be between 0 and 1.")
    if plateau == 1:
        return np.array([[-width, 1.0], [width, 1.0]])
    if plateau == 0:
        return np.array([[-width, 0.0], [0.0, 1.0], [width, 0.0]])
    return np.array([[-width, 0.0], [-width * plateau, 1.0],
                     [width * plateau, 1.0], [width, 0.0]])


def validate_distribution(spec, ev):
    kind = spec.get("velocity_distribution", "default")
    if kind not in KINDS:
        raise ValueError(f"Unknown velocity distribution '{kind}'.")
    if kind in ("waterbag", "trapezoid", "arbitrary"):
        for c in range(3):
            p = component_points(spec, ev, c)
            if p is not None:
                table_quantile(p, [0.5])


def sample_offsets(spec, ev, rng, count, *, quiet=False, ppc=1, cells=None, slots=None):
    """Custom cold/bounded/tabulated offsets; thermal/default laws use existing paths."""
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
