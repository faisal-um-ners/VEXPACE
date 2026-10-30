"""Draw docs/images/velocity_distributions.svg: the emission current-flux laws P(v_n) of VEXPACE.

    python docs/make_velocity_distributions.py

The curves come from the solver's own functions (picstudio.sources.distributions), so the figure
shows exactly what the emitter samples.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from picstudio import constants as C  # noqa: E402
from picstudio.expr import Evaluator  # noqa: E402
from picstudio.sources.distributions import normal_pdf_curve, transmission  # noqa: E402

INK, INK2, GRID = "#1f2328", "#57606a", "#d8dee4"
COL = ["#2a6fdb", "#d1495b", "#2e9e6b", "#8a5cd1", "#e08a1e", "#3a9fb5"]
ev = Evaluator()


def curve(spec):
    v, p = normal_pdf_curve(spec, ev, C.me, 801)
    return v / 1e3, p * 1e3          # km/s and 1/(km/s)


CASES = [
    ("Maxwellian flux\nkT = 0.2 eV", dict(velocity_distribution="maxwellian", temperature="0.2", energy="0"),
     r"$P=\frac{m}{kT}v_n e^{-mv_n^2/2kT}$"),
    ("Truncated Gaussian\nμ = 300 km/s, σ = 100 km/s",
     dict(velocity_distribution="gaussian", velocity_mean="3e5", velocity_spread="1e5"),
     r"$P\propto e^{-(v_n-\mu)^2/2\sigma^2},\ v_n\geq 0$"),
    ("Half-Gaussian\nμ = 0, σ = 200 km/s",
     dict(velocity_distribution="gaussian", velocity_mean="0", velocity_spread="2e5"),
     r"$P=\frac{2}{\sqrt{2\pi}\sigma}e^{-v_n^2/2\sigma^2}$"),
    ("Waterbag: uniform flux\n100–400 km/s",
     dict(velocity_distribution="waterbag", velocity_min="1e5", velocity_max="4e5"),
     r"$P=1/(v_+-v_-)$"),
    ("Waterbag: uniform phase density\n100–400 km/s",
     dict(velocity_distribution="waterbag_phase", velocity_min="1e5", velocity_max="4e5"),
     r"$P=2v_n/(v_+^2-v_-^2)$"),
    ("Trapezoid\n100–400 km/s, plateau 0.5",
     dict(velocity_distribution="trapezoid", velocity_min="1e5", velocity_max="4e5", velocity_plateau="0.5"),
     "linear edges, flat top"),
]


def main():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID,
                         "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                         "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlecolor": INK,
                         "svg.fonttype": "none"})
    fig = plt.figure(figsize=(12.4, 6.2), layout="constrained")
    gs = fig.add_gridspec(2, 4, width_ratios=[1, 1, 1, 1.15])
    for k, (title, spec, eq) in enumerate(CASES):
        ax = fig.add_subplot(gs[k // 3, k % 3])
        v, p = curve(spec)
        ax.fill_between(v, p, color=COL[k], alpha=0.12, linewidth=0)
        ax.plot(v, p, color=COL[k], linewidth=2)
        ax.set_title(title, loc="left")
        ax.text(0.97, 0.95, eq, transform=ax.transAxes, ha="right", va="top", color=INK, fontsize=10)
        ax.set_xlim(0, 800)
        ax.set_ylim(0, p.max() * 1.35)
        ax.set_xlabel("normal speed $v_n$ (km/s)")
        if k % 3 == 0:
            ax.set_ylabel("$P(v_n)$ (1/(km/s))")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    ax = fig.add_subplot(gs[:, 3])
    b = np.linspace(0, 0.8, 321)
    for k, (title, spec, _) in enumerate(CASES):
        T = [transmission(spec, ev, C.me, x) for x in b]
        ax.plot(b, T, color=COL[k], linewidth=2, label=title.split("\n")[0])
    ax.set_title("Transmission over a barrier b", loc="left")
    ax.set_xlabel("barrier depth b (V)")
    ax.set_ylabel("transmitted fraction of current T(b)")
    ax.set_xlim(0, 0.8)
    ax.set_ylim(0, 1.02)
    ax.grid(True, color=GRID, linewidth=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    ax.text(0.40, 0.55, r"passes if $\frac{1}{2}mv_n^2 > eb$", transform=ax.transAxes, color=INK2)
    fig.suptitle("Emitted current-flux distributions P(vₙ), vₙ ≥ 0 (electrons, SI units)",
                 x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK)
    out = ROOT / "docs" / "images" / "velocity_distributions.svg"
    fig.savefig(out, facecolor="white")
    print("wrote", out)


if __name__ == "__main__":
    main()
