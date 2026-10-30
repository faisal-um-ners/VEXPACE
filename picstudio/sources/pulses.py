"""Current pulses J(t) for beam and photo emitters, built from physical inputs in SI units.

Every time is in seconds (counted from t = 0 of the simulation), the strength is either the peak
current density [A/m^2] or the charge per area [C/m^2] of one pulse, and the result is written as
an ordinary J(t) expression that the emitter evaluates at the middle of each time step
(Q = J(t + dt/2) A dt).  No time shift or time-step parameter is needed in the expression.

Shapes (tau = t - start inside one pulse):

    square      J = Jp                                   for 0 <= tau < T
    trapezoid   linear rise (t_r), flat top (t_h), linear fall (t_f);  T = t_r + t_h + t_f
    gaussian    J = Jp exp(-(tau - T/2)^2 / 2 sigma^2),  sigma = FWHM / (2 sqrt(2 ln 2)),
                truncated at +-n sigma:  T = 2 n sigma
    sin2        J = Jp sin^2(pi tau / T)                 (smooth; FWHM = T/2)
    arbitrary   piecewise-linear table of (tau [s], relative height)

A pulse train repeats the pulse N times with period P >= T.  The charge per area of one pulse is
Q1 = Jp * integral of the shape; the train carries N * Q1.
"""
from __future__ import annotations

import math

import numpy as np

from .distributions import point_rows, read_points

SHAPES = ("square", "trapezoid", "gaussian", "sin2", "arbitrary")
FWHM_PER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))
DEFAULT_TABLE = "0, 0\n1e-10, 1\n2e-10, 0.5\n3e-10, 0"


def _finite(ev, src, name, positive=False, nonnegative=False):
    v = ev.num(src)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite.")
    if positive and v <= 0:
        raise ValueError(f"{name} must be positive.")
    if nonnegative and v < 0:
        raise ValueError(f"{name} must be at least zero.")
    return v


def _p(src):
    return f"({str(src).strip()})"


def normalized_settings(settings):
    """Fill new keys from settings written by older versions (duration + equal ramps, Gaussian
    cutoff only, table positions 0..1, sample_shift) without changing the pulse."""
    s = dict(settings)
    kind = s.get("shape", "square")
    dur = s.get("duration", "1e-9")
    if kind == "trapezoid" and not str(s.get("hold", "")).strip():
        rise = s.get("rise", "1e-10")
        s.setdefault("fall", rise)
        if not str(s.get("fall", "")).strip():
            s["fall"] = rise
        s["hold"] = f"{_p(dur)}-{_p(rise)}-{_p(s['fall'])}"
    if kind == "gaussian" and not str(s.get("fwhm", "")).strip():
        s["fwhm"] = f"{_p(dur)}*{FWHM_PER_SIGMA!r}/(2*{_p(s.get('cutoff', '3'))})"
    if str(s.get("table_units", "")) != "seconds":
        if "points" in s or kind == "arbitrary":
            rows = point_rows(s.get("points", "0,0\n0.3,1\n0.7,0.5\n1,0"))
            s["points"] = "\n".join(f"{_p(x)}*{_p(dur)}, {y.strip()}" for x, y in rows)
        s["table_units"] = "seconds"
    s.pop("sample_shift", None)
    s.setdefault("repeat", "1")
    s.setdefault("period", "")
    return s


def build_pulse(settings, ev):
    """Compile the pulse settings to a J(t) expression (strings keep parameter references)."""
    s = normalized_settings(settings)
    kind = s.get("shape", "square")
    if kind not in SHAPES:
        raise ValueError(f"Unknown pulse shape '{kind}'.")
    start_src = str(s.get("start", "0")).strip() or "0"
    start = _finite(ev, start_src, "Start time", nonnegative=True)
    tau = "TAU"                      # placeholder, replaced below (single pulse or train)
    points = None
    if kind == "square":
        T_src = str(s.get("duration", "1e-9"))
        T = _finite(ev, T_src, "Duration", positive=True)
        area, area_src = T, _p(T_src)
        shape = "1"
        fraction = lambda x: np.where((x >= 0) & (x < T), 1.0, 0.0)
        resolve = T
        fwhm = T
    elif kind == "trapezoid":
        tr_src, th_src, tf_src = (str(s.get(k, "1e-10")) for k in ("rise", "hold", "fall"))
        tr = _finite(ev, tr_src, "Rise time", positive=True)
        th = _finite(ev, th_src, "Flat-top time", nonnegative=True)
        tf = _finite(ev, tf_src, "Fall time", positive=True)
        T = tr + th + tf
        T_src = f"({_p(tr_src)}+{_p(th_src)}+{_p(tf_src)})"
        area = 0.5 * tr + th + 0.5 * tf
        area_src = f"(0.5*{_p(tr_src)}+{_p(th_src)}+0.5*{_p(tf_src)})"
        shape = (f"min({tau}/{_p(tr_src)},1,({T_src}-{tau})/{_p(tf_src)})")
        fraction = lambda x: np.clip(np.minimum(np.minimum(x / tr, 1.0), (T - x) / tf), 0, 1) * ((x >= 0) & (x < T))
        resolve = min(tr, tf) if th == 0 else min(tr, tf, th)
        fwhm = th + 0.5 * (tr + tf)
    elif kind == "gaussian":
        fwhm_src, n_src = str(s.get("fwhm", "1e-10")), str(s.get("cutoff", "3"))
        fwhm = _finite(ev, fwhm_src, "FWHM", positive=True)
        n = _finite(ev, n_src, "Gaussian cutoff")
        if n <= math.sqrt(2 * math.log(2)):
            raise ValueError("Gaussian cutoff must exceed 1.178 sigma to keep both half-maximum points.")
        sig = fwhm / FWHM_PER_SIGMA
        T = 2 * n * sig
        sig_src = f"({_p(fwhm_src)}/{FWHM_PER_SIGMA!r})"
        T_src = f"(2*{_p(n_src)}*{sig_src})"
        area = sig * math.sqrt(2 * math.pi) * math.erf(n / math.sqrt(2))
        area_src = f"({sig_src}*sqrt(2*pi)*erf({_p(n_src)}/sqrt(2)))"
        shape = f"exp(-0.5*(({tau}-{_p(n_src)}*{sig_src})/{sig_src})**2)"
        fraction = lambda x: np.exp(-0.5 * ((x - n * sig) / sig) ** 2) * ((x >= 0) & (x < T))
        resolve = fwhm
    elif kind == "sin2":
        T_src = str(s.get("duration", "1e-9"))
        T = _finite(ev, T_src, "Duration", positive=True)
        area, area_src = 0.5 * T, f"(0.5*{_p(T_src)})"
        shape = f"sin(pi*{tau}/{_p(T_src)})**2"
        fraction = lambda x: np.sin(np.pi * x / T) ** 2 * ((x >= 0) & (x < T))
        resolve = 0.5 * T
        fwhm = 0.5 * T
    else:                                                    # arbitrary table in seconds
        text = s.get("points", DEFAULT_TABLE)
        pts = read_points(text, ev)
        if pts[0, 0] != 0:
            raise ValueError("The first table time must be 0 (the pulse start).")
        if len(pts) > 200:
            raise ValueError("Use at most 200 table points.")
        pts[:, 1] /= pts[:, 1].max()
        points = pts
        T = float(pts[-1, 0])
        rows = point_rows(text)
        xs = "[" + ",".join(_p(r[0]) for r in rows) + "]"
        ys_raw = [_p(r[1]) for r in rows]
        ymax = "max(" + ",".join(ys_raw) + ")" if len(ys_raw) > 1 else ys_raw[0]
        ys = "[" + ",".join(f"{y}/{ymax}" for y in ys_raw) + "]"
        T_src = _p(rows[-1][0])
        area = float(np.sum(np.diff(pts[:, 0]) * (pts[1:, 1] + pts[:-1, 1]) / 2))
        # keep the area as an expression so 'charge per area' follows later parameter changes
        terms = [f"({_p(rows[i + 1][0])}-{_p(rows[i][0])})*({ys_raw[i]}+{ys_raw[i + 1]})"
                 for i in range(len(rows) - 1)]
        area_src = f"(({'+'.join(terms)})/(2*{ymax}))"
        shape = f"interp({tau},{xs},{ys})"
        fraction = lambda x: np.interp(x, pts[:, 0], pts[:, 1], left=0, right=0)
        dx = np.diff(pts[:, 0])
        resolve = float(dx[dx > 0].min())
        half = pts[:, 1] >= 0.5
        fwhm = float(pts[half, 0].max() - pts[half, 0].min()) if half.sum() > 1 else resolve
    mode = s.get("normalization", "peak")
    if mode not in ("peak", "charge"):
        raise ValueError("Choose peak current density or charge per area.")
    amount_src = str(s.get("amount", "1e4"))
    amount = _finite(ev, amount_src, "Peak J / charge per area", positive=True)
    peak = amount if mode == "peak" else amount / area
    peak_src = _p(amount_src) if mode == "peak" else f"({_p(amount_src)}/{area_src})"
    nrep = int(round(_finite(ev, s.get("repeat", "1") or "1", "Number of pulses", positive=True)))
    period_src = str(s.get("period", "")).strip()
    if nrep > 1:
        if not period_src:
            raise ValueError("A pulse train needs a period.")
        period = _finite(ev, period_src, "Period", positive=True)
        if period < T * (1 - 1e-12):
            raise ValueError(f"The period ({period:.4g} s) must be at least the pulse length ({T:.4g} s).")
        rel = f"(t-{_p(start_src)})"
        tau_expr = f"({rel}%{_p(period_src)})"
        window = f"where(({rel}>=0)&({rel}<{nrep}*{_p(period_src)})&({tau_expr}<{T_src}),1,0)"
    else:
        period = T
        tau_expr = f"(t-{_p(start_src)})"
        window = f"where(({tau_expr}>=0)&({tau_expr}<{T_src}),1,0)"
    expression = f"{peak_src}*({shape.replace(tau, tau_expr)})*{window}"
    total = T + (nrep - 1) * period
    t_stop_src = (f"{_p(start_src)}+{T_src}" if nrep == 1
                  else f"{_p(start_src)}+({nrep}-1)*{_p(period_src)}+{T_src}")

    def train(t):
        t = np.asarray(t, float) - start
        if nrep > 1:
            k = np.floor(t / period)
            x = t - k * period
            on = (k >= 0) & (k < nrep)
        else:
            x, on = t, t >= 0
        return peak * np.where(on, fraction(x), 0.0)

    return dict(expression=expression, t_start=start_src, t_stop=t_stop_src, start=start, duration=T,
                total=total, peak=peak, charge=peak * area, charge_total=peak * area * nrep,
                fraction=fraction, train=train, points=points, fwhm=fwhm, resolve=resolve,
                repeat=nrep, period=period, settings=s)
