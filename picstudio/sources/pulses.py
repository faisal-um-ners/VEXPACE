"""GUI pulse presets compiled to the existing current-density expression format.

No solver time integration or emitter current law is changed by this helper.
"""
from __future__ import annotations

import math
import numpy as np
from .distributions import read_points, point_rows


def build_pulse(settings, ev):
    kind = settings.get("shape", "square")
    start = ev.num(settings.get("start", "0"))
    duration = ev.num(settings.get("duration", "1e-9"))
    if not math.isfinite(start) or start < 0:
        raise ValueError("Start time must be finite and at least zero.")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Duration must be finite and positive.")
    mode = settings.get("normalization", "peak")
    if mode not in ("peak", "charge"):
        raise ValueError("Choose peak current density or charge per area.")
    amount = ev.num(settings.get("amount", "1e4"))
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Peak current density / charge per area must be finite and positive.")
    # The optional evaluation shift reproduces the midpoint-sampled short-pulse
    # examples. It is opt-in and never changes the simulation timestep.
    shift = ev.num(settings.get("sample_shift", "0"))
    if not math.isfinite(shift):
        raise ValueError("Sampling offset must be finite.")
    start_src = str(settings.get("start", "0"))
    duration_src = str(settings.get("duration", "1e-9"))
    shift_src = str(settings.get("sample_shift", "0"))
    amount_src = str(settings.get("amount", "1e4"))
    u = f"((t+({shift_src})-({start_src}))/({duration_src}))"
    points = None
    if kind == "square":
        area, area_src, shape = 1.0, "1", "1"
        fraction = lambda x: np.ones_like(x)
    elif kind == "trapezoid":
        rise = ev.num(settings.get("rise", "1e-10"))
        if not math.isfinite(rise) or not 0 < rise <= duration / 2:
            raise ValueError("Each ramp must be positive and no longer than half the duration.")
        r = rise / duration
        area = 1 - r
        r_src = f"(({settings.get('rise', '1e-10')})/({duration_src}))"
        area_src = f"(1-({r_src}))"
        shape = f"max(0,min(1,min({u},1-{u})/({r_src})))"
        fraction = lambda x: np.clip(np.minimum(x, 1 - x) / r, 0, 1)
    elif kind == "gaussian":
        cutoff = ev.num(settings.get("cutoff", "3"))
        if not math.isfinite(cutoff) or cutoff <= math.sqrt(2 * math.log(2)):
            raise ValueError("Gaussian cutoff must exceed 1.178 sigma to retain both half-maximum points.")
        sigma = 1 / (2 * cutoff)
        area = sigma * math.sqrt(2 * math.pi) * math.erf(cutoff / math.sqrt(2))
        sigma_src = f"(1/(2*({settings.get('cutoff', '3')})))"
        area_src = f"({sigma_src}*sqrt(2*pi)*erf(({settings.get('cutoff', '3')})/sqrt(2)))"
        shape = f"exp(-0.5*(({u}-0.5)/({sigma_src}))**2)"
        fraction = lambda x: np.exp(-0.5 * ((x - .5) / sigma) ** 2)
    elif kind == "arbitrary":
        points = read_points(settings.get("points", "0,0\n0.3,1\n0.7,0.5\n1,0"), ev)
        if points[0, 0] != 0 or points[-1, 0] != 1:
            raise ValueError("Pulse positions must start at 0 and end at 1 (the full duration).")
        if len(points) > 64:
            raise ValueError("Use at most 64 pulse points; combine nearby points before importing.")
        points[:, 1] /= points[:, 1].max()
        x, y = points.T
        area = float(np.sum(np.diff(x) * (y[:-1] + y[1:]) / 2))
        rows = point_rows(settings.get("points", "0,0\n0.3,1\n0.7,0.5\n1,0"))
        xs = [f"({row[0]})" for row in rows]
        ys = [f"({row[1]})" for row in rows]
        ymax = "max(" + ",".join(ys) + ")"
        heights = [f"({y}/{ymax})" for y in ys]
        area_src = "(" + "+".join(f"(({xs[i+1]}-{xs[i]})*({heights[i+1]}+{heights[i]})/2)" for i in range(len(x)-1)) + ")"
        shape = heights[-1]
        for i in range(len(x) - 2, -1, -1):
            slope = f"(({heights[i+1]}-{heights[i]})/({xs[i+1]}-{xs[i]}))"
            part = f"({heights[i]}+{slope}*({u}-{xs[i]}))"
            shape = f"where({u}<{xs[i+1]},{part},{shape})"
        fraction = lambda x: np.interp(x, points[:, 0], points[:, 1])
    else:
        raise ValueError(f"Unknown pulse shape '{kind}'.")
    peak = amount if mode == "peak" else amount / (duration * area)
    if not math.isfinite(peak) or peak <= 0:
        raise ValueError("Pulse peak is outside the finite supported range.")
    peak_src = f"({amount_src})" if mode == "peak" else f"(({amount_src})/(({duration_src})*({area_src})))"
    expression = f"({peak_src})*({shape})*where(({u}>=0)&({u}<1),1,0)"
    return dict(expression=expression, t_start=f"({start_src})-({shift_src})",
                t_stop=f"({start_src})+({duration_src})-({shift_src})", start=start, duration=duration,
                peak=peak, charge=peak * duration * area, fraction=fraction, points=points,
                sample_shift=shift)
