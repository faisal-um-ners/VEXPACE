"""Readable labels for additive energy signals; CSV keys remain stable."""

LABELS = {
    'ED_reference_ready': 'Mean-field reference ready',
    'ED_W_push': 'Total electric work to particles',
    'ED_W_dc': 'DC work to particles',
    'ED_W_rf': 'Fluctuating-field work from particles',
    'ED_W_applied': 'Applied-field work to particles',
    'ED_W_grid_particle': 'Yee field work to particle current',
    'ED_W_antenna': 'Antenna work to Yee fields',
    'ED_W_load': 'Total material load loss',
    'ED_W_load_rf': 'Fluctuating-field load loss',
    'ED_W_absorber': 'Absorbing-layer loss',
    'ED_W_voltage': 'Held-voltage source work',
    'ED_W_constraint': 'Conductor correction to Yee energy',
    'ED_K_inserted': 'Inserted particle kinetic energy',
    'ED_K_absorbed': 'Absorbed particle kinetic energy',
    'ED_U_electric': 'Native Yee electric energy',
    'ED_U_magnetic': 'Native Yee magnetic energy',
    'ED_R_particle': 'Particle energy residual',
    'ED_R_work_split': 'DC/fluctuation split residual',
    'ED_R_model': 'Particle plus Yee energy residual',
    'ED_eta_load': 'RF load / source work (after reference)',
    'ED_P_load': 'Material load power',
    'ED_P_load_rf': 'Fluctuating-field load power',
}


def signal_label(key):
    if key.startswith('ED_K_surface_'):
        return 'Impact kinetic energy, surface '+key.removeprefix('ED_K_surface_')
    if key.startswith('ED_P_surface_'):
        return 'Impact power, surface '+key.removeprefix('ED_P_surface_')
    return LABELS.get(key, key)


def signal_unit(key):
    if key == 'ED_eta_load': return '%'
    if key.startswith('ED_P_'): return 'W/m'
    if key.startswith(('ED_W_', 'ED_K_', 'ED_U_', 'ED_R_')): return 'J/m'
    return ''
