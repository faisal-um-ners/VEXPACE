"""Generate the Source Designer teaching examples (pulses + emission velocity distributions).

    python examples/make_source_designer_examples.py

Writes only these files (no other example is touched):
    source_designer_beam_1d      Gaussian pulse, truncated-Gaussian normal-speed flux (1D)
    source_designer_square_1d    square pulse, uniform-flux waterbag (1D)
    source_designer_trapezoid_1d trapezoid pulse, trapezoid normal-speed flux (1D)
    source_designer_pulse_rz     Gaussian pulse, Maxwellian (Rayleigh) flux from a small disk (2D RZ)
    source_designer_pulse_zy     trapezoid pulse, waterbag flux + transverse waterbag (2D ZY)
    Gaussian_VD_Barrier          half-Gaussian flux into a space-charge barrier (1D)

All inputs are physical SI values.  The time step is the simulation dt itself (no extra
parameter): the emitter samples J at the middle of every step, Q = J(t + dt/2) A dt.
"""
from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from picstudio.model.model import new_model, complete, evaluator, validate  # noqa: E402
from picstudio.sources.pulses import build_pulse  # noqa: E402

GUIDE = ("Select Emission > {em} > Current pulse to change the pulse, and Velocity distribution to change "
         "the emitted normal-speed flux; click Apply, then Run. Old results are cleared when model settings "
         "change. Illustrative source/transport example, not a published benchmark.")


def pulse_emitter(m, settings, **emitter):
    p = build_pulse(settings, evaluator(m))
    e = dict(name="pulsed_beam", species="electrons", model="beam", surface="segment", normal="+z",
             current_density=p["expression"], t_start=p["t_start"], t_stop=p["t_stop"],
             pulse_builder=dict(p["settings"], generated_expression=p["expression"]), velocity_version="2")
    e.update(emitter)
    m["emitters"] = [e]
    return p


def vacuum(m, z0, z1, y0, y1, name="vacuum gap"):
    """Vacuum geometry object over the gap (first in the list: it never carves electrodes)."""
    m["objects"] = [dict(name=name, shape="rectangle", material="vacuum", z0=z0, z1=z1, y0=y0, y1=y1)]


def base(geometry, name, description, parameters):
    m = new_model(geometry, "electrostatic", name)
    m["description"] = description
    m["parameters"] = parameters
    m["species"] = [dict(name="electrons", preset="electron")]
    m["parallel"].update(mode="serial", threads=1)
    m["simulation"].update(relativistic=True, smoothing=0, seed=12345)
    return m


def finish(m, stem):
    m["diagnostics"].update(output_dir="output_" + stem, history_every="1", field_every="50",
                            particle_every="50", max_dump_particles="10000", live_every="20")
    m = complete(m)
    errors = [msg for lvl, msg in validate(m) if lvl == "error"]
    if errors:
        raise ValueError(f"{stem}: {errors}")
    (HERE / f"{stem}.pic.json").write_text(json.dumps(m, indent=2) + "\n")
    print("wrote", stem + ".pic.json")
    return m


def drift_1d(stem, title, settings, dist, note):
    m = base("1D-Z", title,
             f"Finite electron pulse drifting through a grounded 15 mm vacuum gap (no applied field). {note} "
             + GUIDE.format(em="pulsed_beam"),
             {"D": "15e-3", "beam_energy": "1000", "run_end": "1.5e-9"})
    m["domain"].update(z_min="0", z_max="D", nz="120")
    for s in ("z_min", "z_max"):
        m["boundaries"][s].update(field="conductor", voltage="0", particles="absorb")
    m["simulation"].update(dt="1e-12", t_end="run_end")
    pulse_emitter(m, settings, z0="0", z1="0", y0="0", y1="0", energy="beam_energy", temperature="0",
                  particles_per_cell="8", **dist)
    return finish(m, stem)


def main():
    v = "speed_eV(beam_energy)"                    # beam speed [m/s] of beam_energy [eV]
    drift_1d("source_designer_beam_1d", "Gaussian pulse: 1D vacuum drift",
             dict(shape="gaussian", start="1e-10", fwhm="1e-10", cutoff="3", normalization="peak", amount="10"),
             dict(velocity_distribution="gaussian", velocity_mean="", velocity_spread="2e5",
                  transverse_distribution="cold"),
             "Gaussian J(t): FWHM 0.1 ns, truncated at +-3 sigma (0.255 ns), peak 10 A/m^2, start 0.1 ns. "
             "Normal speed: truncated-Gaussian current flux about the 1 keV beam speed (sigma 2e5 m/s).")
    drift_1d("source_designer_square_1d", "Square pulse: 1D vacuum drift",
             dict(shape="square", start="1e-10", duration="3e-10", normalization="peak", amount="10"),
             dict(velocity_distribution="waterbag", velocity_min=f"{v}-2e5", velocity_max=f"{v}+2e5",
                  transverse_distribution="cold"),
             "Square J(t): 10 A/m^2 for 0.3 ns from 0.1 ns. Normal speed: uniform-flux waterbag "
             "v_b-2e5 ... v_b+2e5 m/s (v_b = 1 keV beam speed).")
    drift_1d("source_designer_trapezoid_1d", "Trapezoid pulse: 1D vacuum drift",
             dict(shape="trapezoid", start="1e-10", rise="6e-11", hold="1.8e-10", fall="6e-11",
                  normalization="peak", amount="10"),
             dict(velocity_distribution="trapezoid", velocity_min=f"{v}-2e5", velocity_max=f"{v}+2e5",
                  velocity_plateau="0.5", transverse_distribution="cold"),
             "Trapezoid J(t): rise 0.06 ns, flat top 0.18 ns, fall 0.06 ns, peak 10 A/m^2. Normal speed: "
             "trapezoid flux on v_b-2e5 ... v_b+2e5 m/s with a 50 % plateau.")

    # --- 2D RZ: small thermionic-like disk emitter in a 10 kV gap -------------------------------
    m = base("2D-RZ", "Gaussian pulse: 2D RZ small-disk emitter",
             "Gaussian electron pulse from a small disk (radius R = 0.1 mm) at the cathode of a 10 mm, 10 kV "
             "planar gap. Emission: Maxwellian (Rayleigh) current flux of a 0.2 eV cathode, P(v) ~ v exp(-mv^2/2kT), "
             "with thermal transverse velocities. J(t): FWHM 0.1 ns, +-3 sigma, peak 1e4 A/m^2 (below the "
             "planar Child-Langmuir value 2.3e4 A/m^2). The local triangle mesh is refined along the "
             "emission region and the expanding beam. " + GUIDE.format(em="pulsed_beam"),
             {"D": "10e-3", "R": "0.1e-3", "V0": "10e3", "run_end": "1.5e-9"})
    m["domain"].update(z_min="0", z_max="D", nz="40", y_min="0", y_max="20*R", ny="8")
    m["boundaries"]["z_min"].update(name="cathode", field="conductor", voltage="0", particles="absorb")
    m["boundaries"]["z_max"].update(name="anode", field="conductor", voltage="V0", particles="absorb")
    m["boundaries"]["y_min"].update(field="axis", particles="reflect")
    m["boundaries"]["y_max"].update(field="neumann", particles="absorb")
    vacuum(m, "0", "D", "0", "20*R")
    m["mesh_refinements"] = [
        dict(name="prescribed expanding pulse envelope", enabled=True, axis="local 2D", region_shape="polygon",
             points="0,0; D,0; D,5*R; 0,1.5*R", buffer=".4*R", size="R/2", growth="1.2"),
        dict(name="fine along emission region", enabled=True, axis="local 2D", region_shape="rectangle",
             z0="0", z1="D/10", y0="0", y1="1.2*R", buffer="R/5", size="R/6", growth="1.2")]
    m["simulation"].update(dt="1e-12", t_end="run_end")
    pulse_emitter(m, dict(shape="gaussian", start="5e-11", fwhm="1e-10", cutoff="3", normalization="peak",
                          amount="1e4"),
                  z0="0", z1="0", y0="0", y1="R", energy="0", temperature="0.2", particles_per_cell="16",
                  velocity_distribution="maxwellian", transverse_distribution="thermal")
    m["diagnostics"]["field_every"] = "100"
    finish(m, "source_designer_pulse_rz")

    # --- 2D ZY: sheet beam drifting in a grounded gap -------------------------------------------
    m = base("2D-ZY", "Trapezoid pulse: 2D ZY vacuum drift",
             "Trapezoid sheet-beam pulse (half-width R = 1.5 mm, 1 keV) drifting through a grounded 15 mm gap; "
             "y = 0 is a symmetry plane. Emission: uniform-flux waterbag normal speed v_b-2e5 ... v_b+2e5 m/s and "
             "a transverse waterbag of half-width 2e5 m/s. J(t): rise 0.06 ns, flat top 0.18 ns, fall 0.06 ns, "
             "peak 100 A/m^2. " + GUIDE.format(em="pulsed_beam"),
             {"D": "15e-3", "R": "1.5e-3", "beam_energy": "1000", "run_end": "1.5e-9"})
    m["domain"].update(z_min="0", z_max="D", nz="40", y_min="0", y_max="4*R", ny="24")
    for s in ("z_min", "z_max"):
        m["boundaries"][s].update(field="conductor", voltage="0", particles="absorb")
    m["boundaries"]["y_min"].update(field="neumann", particles="reflect")
    m["boundaries"]["y_max"].update(field="neumann", particles="absorb")
    vacuum(m, "0", "D", "0", "4*R", name="drift region")
    m["mesh_refinements"] = [
        dict(name="prescribed expanding pulse envelope", enabled=True, axis="local 2D", region_shape="polygon",
             points="0,0; D,0; D,3*R; .65*D,2.5*R; .25*D,1.6*R; 0,R", buffer=".4*R", size="R/8", growth="1.2"),
        dict(name="fine injection region", enabled=True, axis="local 2D", region_shape="rectangle",
             z0="0", z1="D/12", y0="0", y1="1.2*R", buffer="R/5", size="R/12", growth="1.2")]
    m["simulation"].update(dt="1e-12", t_end="run_end")
    pulse_emitter(m, dict(shape="trapezoid", start="1e-10", rise="6e-11", hold="1.8e-10", fall="6e-11",
                          normalization="peak", amount="100"),
                  z0="0", z1="0", y0="0", y1="R", energy="beam_energy", temperature="0", particles_per_cell="32",
                  velocity_distribution="waterbag", velocity_min=f"{v}-2e5", velocity_max=f"{v}+2e5",
                  transverse_distribution="waterbag", transverse_width=["2e5", "0"])
    m["diagnostics"]["field_every"] = "100"
    finish(m, "source_designer_pulse_zy")

    # --- user's barrier case: strongly over-injected 1D diode -----------------------------------
    m = base("1D-Z", "Half-Gaussian velocity flux into a space-charge barrier (1D)",
             "Electrons are injected at 1e5 A/m^2 into a 15 mm gap with the collector at +100 V. This is far "
             "above the space-charge limit of the gap (Child-Langmuir 10.4 A/m^2 at 100 V; with the injection "
             "speeds, only a fraction can cross), so a potential minimum (virtual cathode / barrier) forms in "
             "front of the emitter and reflects most electrons. Injected normal speed: truncated Gaussian "
             "current flux with mean 0 and sigma 2e5 m/s (a half-Gaussian, v_n >= 0, kT-equivalent "
             "m sigma^2/e = 0.23 eV). The Velocity distribution dialog shows the transmission T(b) of a barrier b "
             "for this flux. J(t) is a constant 1e5 A/m^2 (square pulse longer than the run). "
             + GUIDE.format(em="pulsed_beam"),
             {"D": "15e-3", "V_collector": "100", "J_inj": "1e5"})
    m["domain"].update(z_min="0", z_max="D", nz="512")
    m["boundaries"]["z_min"].update(name="emitter", field="conductor", voltage="0", particles="absorb")
    m["boundaries"]["z_max"].update(name="collector", field="conductor", voltage="V_collector", particles="absorb")
    m["simulation"].update(dt="1e-12", t_end="50e-9")
    pulse_emitter(m, dict(shape="square", start="0", duration="100e-9", normalization="peak", amount="J_inj"),
                  z0="0", z1="0", y0="0", y1="0", energy="0", temperature="0", particles_per_cell="32",
                  velocity_distribution="gaussian", velocity_mean="0", velocity_spread="2e5",
                  transverse_distribution="cold")
    m["line_probes"] = [dict(name="phi_axis", quantity="phi", extremum="min", along="z", y="0", z="0",
                             start="0", end="D")]
    finish(m, "Gaussian_VD_Barrier")


if __name__ == "__main__":
    main()
