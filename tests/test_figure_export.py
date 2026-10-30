"""Reference export UI parity and complete VEXPACE Matplotlib export coverage."""
import ast
import copy
import hashlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLineEdit

from picstudio.gui.canvas import PlotWidget, ExportToolbar
from picstudio.gui.figure_export import bridge
from picstudio.gui.figure_export.gui import export_dialog as E
from picstudio.post.ticks import unit_axes


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def line_plot(app):
    p = PlotWidget()
    ax = p.axes[0]
    ax.plot([0,1e-9,2e-9],[0,100,0],color='#0072B2',label='emission',lw=1.25)
    ax.set_title('Current history');ax.set_xlabel('time');ax.set_ylabel('current')
    unit_axes(ax,'s','A')
    ax.set_xlim(0,2e-9);ax.legend()
    p.canvas.draw()
    return p


def options(spec, view):
    return E.ExportOptions(w=6,h=4,dpi=100,panels=E.defaults_from_spec(spec,view))


def test_export_dialog_class_is_identical_to_requested_upstream():
    source=Path(E.__file__).read_text()
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='ExportDialog')
    text=''.join(source.splitlines(True)[node.lineno-1:node.end_lineno])
    # upstream class + panel-gap (wspace/hspace) controls added for multi-panel figures
    assert hashlib.sha256(text.encode()).hexdigest()=='07facea02cc4ea67ec46df91a03ae074b2ca407a3b225ca38a10a4eb493a2e45'
    assert [value for label,value in E.FORMATS]==['png','pdf','svg','eps','tiff']


@pytest.mark.parametrize('fmt',['png','pdf','svg','eps','tiff'])
def test_all_reference_formats_and_source_plot_unchanged(app,tmp_path,fmt):
    p=line_plot(app)
    source_limits=p.axes[0].get_xlim()
    source_color=p.axes[0].lines[0].get_color()
    spec,view=bridge.snapshot_spec(p.fig)
    opts=options(spec,view);opts.fmt=fmt
    opts.panels[0].xlabel='edited time (ns)'
    opts.panels[0].curves[0].color='#D55E00'
    path=tmp_path/('figure.'+fmt)
    E.export_figure(spec,opts,str(path))
    assert path.stat().st_size>500
    assert p.axes[0].get_title()=='Current history'
    assert p.axes[0].get_xlim()==source_limits
    assert p.axes[0].lines[0].get_color()==source_color
    if fmt=='svg':
        assert 'edited time (ns)' in path.read_text()
    p.close()


def test_limits_and_manual_ticks_use_the_units_shown_on_screen(app):
    p=line_plot(app);spec,view=bridge.snapshot_spec(p.fig)
    assert view[0][0]==pytest.approx((0,2))  # ns, rather than hidden SI values.
    opts=options(spec,view)
    opts.panels[0].xlim=(.25,1.75)
    opts.panels[0].xticks='0.5, 1, 1.5';opts.panels[0].xticks_auto=False
    png,ticks=E.preview_png(spec,opts,100,with_ticks=True)
    assert png.startswith(b'\x89PNG')
    np.testing.assert_allclose(ticks[0][0],[.5,1,1.5])
    edited=E.build_spec(spec,opts)
    with __import__('matplotlib').rc_context(E.export_rc(opts)):
        fig,axes=bridge.render_snapshot(edited,opts,100)
    assert axes[0].get_xlim()==pytest.approx((.25e-9,1.75e-9))
    assert not any(line.get_visible() for line in axes[0].get_xgridlines())
    p.close()


def test_particle_series_starts_as_points_and_can_connect_them(app):
    p=PlotWidget();p.axes[0].scatter([0,1,2],[0,2,1],s=9,label='electrons')
    p.axes[0].legend()
    spec,view=bridge.snapshot_spec(p.fig);opts=options(spec,view)
    assert opts.panels[0].curves[0].style=='none'
    curve=opts.panels[0].curves[0];curve.style='--';curve.marker='none'
    with __import__('matplotlib').rc_context(E.export_rc(opts)):
        fig,axes=bridge.render_snapshot(E.build_spec(spec,opts),opts,100)
    assert len(axes[0].lines)==1
    np.testing.assert_array_equal(axes[0].lines[0].get_ydata(),[0,2,1])
    assert not axes[0].collections[0].get_visible()
    assert len(axes[0].get_legend().get_texts())==1
    p.close()


def test_mesh_scatter_colorbar_patches_and_inset_survive_export(app,tmp_path):
    p=PlotWidget(nrows=2,ncols=2)
    x,y=np.meshgrid(np.linspace(0,1,8),np.linspace(0,1,6))
    a,b,c,d=p.axes
    mesh=a.pcolormesh(x,y,x+y,shading='auto',cmap='viridis')
    p.fig.colorbar(mesh,ax=a,label='potential (V)')
    points=b.scatter([.2,.5,.8],[.1,.6,.3],c=['red','green','blue'],s=[4,9,16])
    c.triplot([0,1,0,1],[0,0,1,1],[[0,1,2],[1,2,3]],lw=.8)
    c.add_patch(Rectangle((.1,.1),.3,.2,fill=False))
    d.plot([0,1,2],[0,1,0],label='pulse');d.fill_between([0,1,2],[0,1,0],alpha=.2)
    inset=d.inset_axes([.55,.55,.35,.35]);inset.plot([0,1],[1,0]);inset.set_title('FFT')
    p.canvas.draw()
    spec,view=bridge.snapshot_spec(p.fig)
    assert len(spec.axes)==5  # Four panels and inset; colour bar is not a panel.
    opts=options(spec,view);opts.panels[0].cmap='plasma';opts.panels[0].clabel='edited potential'
    before=[(len(ax.lines),len(ax.collections),len(ax.patches)) for ax in bridge._all_axes(p.fig)]
    edited=E.build_spec(spec,opts)
    with __import__('matplotlib').rc_context(E.export_rc(opts)):
        fig,axes=bridge.render_snapshot(edited,opts,100)
    after=[(len(ax.lines),len(ax.collections),len(ax.patches)) for ax in bridge._all_axes(fig)]
    assert before==after
    np.testing.assert_array_equal(axes[1].collections[0].get_offsets(),points.get_offsets())
    np.testing.assert_array_equal(axes[1].collections[0].get_sizes(),[4,9,16])
    assert axes[0].collections[0].get_cmap().name=='plasma'
    assert mesh.get_cmap().name=='viridis'
    assert axes[0].collections[0].colorbar.ax.get_ylabel()=='edited potential'
    E.export_figure(spec,opts,str(tmp_path/'all-panels.svg'))
    assert (tmp_path/'all-panels.svg').stat().st_size>5000
    p.close()


def test_original_tabs_edit_preview_reset_and_reopen_state(app,tmp_path):
    p=line_plot(app);spec,view=bridge.snapshot_spec(p.fig)
    settings=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    with patch.object(E,'QSettings',return_value=settings):
        dialog=E.ExportDialog(p,spec,view)
        assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]==['Output','Text','Axes','Lines','Legend']
        dialog._update_preview()
        assert not dialog.err.text()
        before=dialog._pixmap.cacheKey() if hasattr(dialog,'_pixmap') else None
        dialog.w.setValue(7)
        dialog._update_preview()
        assert not dialog.preview.pixmap().isNull()
        assert not dialog.err.text()
        state=dialog.state()
        reopened=E.ExportDialog(p,spec,view,state=state)
        assert reopened.state()==state
        dialog._reset_all();dialog._update_preview()
        assert not dialog.err.text()
        dialog.reject();reopened.reject()
    p.close()


def test_all_plot_toolbars_and_results_figure_button_use_shared_exporter(app):
    from picstudio.gui.results import ResultsPanel
    p=PlotWidget()
    assert isinstance(p.toolbar,ExportToolbar)
    with patch.object(p,'export_figure') as exported:
        p.toolbar.save_figure()
        exported.assert_called_once()
    panel=ResultsPanel()
    with patch.object(panel.plot,'export_figure') as exported:
        panel.export_fig()
        exported.assert_called_once()
    p.close();panel.close()


def test_original_text_curve_legend_controls_render_and_copy(app,tmp_path):
    p=line_plot(app);spec,view=bridge.snapshot_spec(p.fig)
    settings=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    with patch.object(E,'QSettings',return_value=settings):
        d=E.ExportDialog(p,spec,view)
        d.dpi.setValue(100)
        d.p_title.setText('Edited pulse');d.p_x.setText('Time (ns)')
        d.font_size.setValue(12);d.family.setCurrentIndex(3)
        d.grid.setChecked(True);d.minor.setChecked(False)
        d.lg_pos.setCurrentIndex(10);d.lg_frame.setChecked(True)
        d.lg_ncol.setValue(2);d.lg_scale.setValue(110)
        d._store_panel()
        d.panels[0].curves[0].label='Edited emission'
        d.panels[0].curves[0].color='#D55E00'
        d.panels[0].curves[0].style='--'
        d.panels[0].curves[0].marker='s'
        d.panels[0].curves[0].msize=6
        d._load_panel(0)
        opts=d.options()
        edited=E.build_spec(spec,opts)
        with __import__('matplotlib').rc_context(E.export_rc(opts)):
            fig,axes=bridge.render_snapshot(edited,opts,100)
            fig.canvas.draw()
        ax=axes[0]
        assert ax.get_title()=='Edited pulse'
        assert ax.get_xlabel()=='Time (ns)'
        assert ax.xaxis.label.get_fontsize()==12
        assert ax.lines[0].get_linestyle()=='--'
        assert ax.lines[0].get_marker()=='s'
        assert ax.lines[0].get_color().lower()=='#d55e00'
        assert ax.get_legend().get_texts()[0].get_text()=='Edited emission'
        assert ax.get_legend().get_frame_on()
        assert any(line.get_visible() for line in ax.get_xgridlines())
        # Capture the clipboard payload without touching the user's clipboard.
        with patch.object(E.QGuiApplication,'clipboard') as clipboard:
            d._copy()
            payload=clipboard.return_value.setMimeData.call_args.args[0]
            assert payload.hasImage() and not payload.imageData().isNull()
        assert d.size_lab.text()=='Copied to the clipboard'
        d.reject()
    p.close()


def test_shared_export_workflow_save_cancel_and_reopen(app,tmp_path):
    from PySide6.QtWidgets import QDialog
    p=line_plot(app)
    path=tmp_path/'saved-without-extension'
    def accept(dialog):
        dialog.fmt.setCurrentIndex(2) # SVG
        dialog.p_x.setText('Edited axis')
        return QDialog.Accepted
    with patch.object(bridge.ExportDialog,'exec',accept), \
         patch.object(bridge.QFileDialog,'getSaveFileName',return_value=(str(path),'')):
        p.export_figure()
    saved=path.with_suffix('.svg')
    assert saved.exists() and 'Edited axis' in saved.read_text()
    assert p._export_state
    with patch.object(bridge.ExportDialog,'exec',return_value=QDialog.Rejected), \
         patch.object(bridge.QFileDialog,'getSaveFileName') as save_dialog:
        p.export_figure()
        save_dialog.assert_not_called()
    p.close()
