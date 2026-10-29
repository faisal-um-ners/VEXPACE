# Interactive figure export

The **Results → Save figure** button and every plot toolbar's **Save** icon
open the same interactive **Export figure** window. This includes geometry,
live monitor, saved results, pulse previews, and velocity previews.

The window uses the PASCHEN Studio exporter at commit
`ced9e63f38abaaf591e85998f2e6d26eb1f36a63`, with its original controls and defaults:

- **Output:** PNG, PDF, SVG, EPS or TIFF; publication, presentation or screen
  appearance; size presets, width, height and resolution.
- **Text:** fonts, math/LaTeX support, font and line sizes, ticks and grid.
- **Axes:** panel selection, titles, labels, scales, ranges, ticks, and colour
  map/bar labels where the plot has a colour map.
- **Lines:** curve labels, colours, styles, widths, markers and palettes.
- **Legend:** position, columns, frame, size and spacing.

The preview updates as controls change. **Reset to plot**, **Copy** and
**Save…** follow the original PASCHEN workflow. A copy of the current figure
keeps meshes, particles, colour bars, geometry patches and FFT insets; edits
in the exporter do not change the source plot or model. Axis ranges and tick
positions use the units displayed on screen, such as ns or mm.

The reference code and its license/attribution are included under
`picstudio/gui/figure_export/`. The VEXPACE adapter supplies plot data without
adding controls to the export window. Animation and numerical-data exports
retain their existing workflows.
