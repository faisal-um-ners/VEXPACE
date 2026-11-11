# Optional geometry-object histories

Under **Geometry Objects**, select an object and enable only the histories you need:

- **Record current (I)** adds `I_<name>` to `history.csv`, Live monitor History,
  and saved Results History. Available for conductors, dielectrics and absorbers.
- **Record voltage (V)** adds `V_<name>` to those outputs. Available for conductors.

Both options default to **off**, including when loading a project that does not
yet contain these settings. Explicit selections save/load with the project and
are preserved when an object is duplicated. A many-tooth grating can therefore
retain every physical conductor without creating current/voltage history columns
for each tooth. Domain-boundary histories, species diagnostics, probes, emission
histories and power monitors keep their existing behavior.

Disabling current history skips that object's collected-current histogram work
and accumulator storage; MPI reduces only enabled object-current accumulators.
Disabling voltage history skips its evaluation for the history row. Physical
voltage evaluation, conductor masks, field/circuit solves, absorption, emission
and dielectric surface charging are unchanged. This reduces diagnostic overhead;
it does not remove the cost of solving the physical geometry.

The opt-in magnetron energy diagnostics remain independent: global absorbed
energy, surface impact records and energy balances still include physical impacts
even if these ordinary I/V histories are disabled.

Settings take effect when starting a new run. Existing saved results retain the
columns that were recorded; changing a checkbox does not rewrite old results.
Enable both options for electrodes whose current/voltage histories you want to
use for a later power or efficiency calculation.
