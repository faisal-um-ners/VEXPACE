"""Energy controls/signals and white exports with either application theme."""
from unittest.mock import patch
import numpy as np
import pytest
import matplotlib as mpl
from matplotlib.colors import to_rgba
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog
from picstudio.gui import theme
from picstudio.gui.main_window import MainWindow
from picstudio.gui.results import LivePanel, ResultsPanel
from picstudio.gui.forms import FieldForm
from picstudio.gui.canvas import PlotWidget
from picstudio.gui.figure_export import bridge
from picstudio.gui.figure_export.gui import export_dialog as E
from picstudio.model import model as M, schema as S
from picstudio.post import plotting as P


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_white_default_retains_explicit_theme_toggle(app,tmp_path):
    settings=QSettings(str(tmp_path/'theme.ini'),QSettings.IniFormat)
    settings.setValue('theme','dark') # legacy preference must not retain the old default
    with patch('picstudio.gui.main_window.QSettings',return_value=settings),patch.object(MainWindow,'draw_geometry'):
        w=MainWindow()
        assert w.theme=='light'
        assert w.live.plot._style=='dark'
        dark=theme.matplotlib_rc('dark')['axes.facecolor']
        np.testing.assert_allclose(w.geo_plot.fig.get_facecolor(),to_rgba('white'))
        for name in ('dark','light'):
            w.set_theme(name);assert w.theme==name
            for ax in w.live.plot.axes:
                np.testing.assert_allclose(ax.get_facecolor(),to_rgba(dark))
        spec,view=bridge.snapshot_spec(w.live.plot.fig)
        opts=E.ExportOptions(panels=E.defaults_from_spec(spec,view))
        with mpl.rc_context(E.export_rc(opts)):
            fig,axes=bridge.render_snapshot(E.build_spec(spec,opts),opts,100)
        for ax in axes:np.testing.assert_allclose(ax.get_facecolor(),to_rgba('white'))
        w.dirty=False;w.close()


def test_diagnostic_controls_round_trip_and_visibility(app,tmp_path):
    m=M.new_model('2D-ZY','electromagnetic')
    form=FieldForm(S.DIAGNOSTICS,m['diagnostics'])
    assert form.widgets['energy_reference_time'].isHidden()
    form.widgets['energy_enabled'].setChecked(True)
    assert m['diagnostics']['energy_enabled']
    assert not form.widgets['energy_reference_time'].isHidden()
    m['diagnostics']['energy_hub_y']='.002'
    p=tmp_path/'new.pic.json';M.save(m,p)
    assert M.load(p)['diagnostics']['energy_hub_y']=='.002'
    form.close()


def test_energy_history_menu_and_staggered_current_display(app):
    panel=LivePanel()
    panel._rebuild_signal_menu(['t','ED_W_dc','ED_P_load_rf'])
    assert any('DC work to particles [J/m]'==a.text() for a in panel.sig_menu.actions())
    d=dict(z=np.arange(3),y=np.arange(4),Jy=np.zeros((3,4)),native_Jy=np.zeros((3,3)))
    assert P.field_names(d)==['Jy']
    panel.checked={'ED_W_dc'};panel.sig_names=['ED_W_dc']
    panel._history(panel.plot.axes[-1],dict(history=np.array([[0,0],[1,2]]),
        history_columns=['t','ED_W_dc'],history_units=['s','J/m']))
    panel.plot.canvas.draw()
    assert 'J/m' in panel.plot.axes[-1].get_ylabel()
    panel.close()


@pytest.mark.parametrize('stored_style',['publication','dark','screen'])
def test_white_export_from_dark_geometry_preserves_source(app,stored_style):
    app.setStyleSheet(theme.stylesheet('dark'))
    with mpl.rc_context(theme.matplotlib_rc('dark')):
        p=PlotWidget();m=M.new_model('2D-ZY')
        P.plot_geometry(p.axes[0],m)
        p.fig._export_as_is=True
        p.canvas.draw()
        original=p.axes[0].patches[0].get_facecolor()
        spec,view=bridge.snapshot_spec(p.fig)
        opts=E.ExportOptions(style=stored_style,panels=E.defaults_from_spec(spec,view))
        with mpl.rc_context(E.export_rc(opts)):
            fig,axes=bridge.render_snapshot(E.build_spec(spec,opts),opts,100)
        np.testing.assert_allclose(fig.get_facecolor(),to_rgba('white'))
        np.testing.assert_allclose(axes[0].get_facecolor(),to_rgba('white'))
        np.testing.assert_allclose(axes[0].patches[0].get_facecolor(),to_rgba('white'))
        np.testing.assert_array_equal(p.axes[0].patches[0].get_facecolor(),original)
        with patch.object(bridge.ExportDialog,'exec',return_value=QDialog.Rejected):p.export_figure()
        p.close()
    app.setStyleSheet('')


def test_white_field_mask_export_preserves_actual_field_colormap(app):
    with mpl.rc_context(theme.matplotlib_rc('dark')):
        p=PlotWidget();a=p.axes[0]
        data=dict(z=np.linspace(0,1,4),y=np.linspace(0,1,4),Ez=np.arange(16).reshape(4,4),
                  cell_mat=np.array([[1,0,0],[0,0,0],[0,0,0]]))
        field=P.plot_field(a,data,'Ez');p.canvas.draw()
        spec,view=bridge.snapshot_spec(p.fig)
        opts=E.ExportOptions(panels=E.defaults_from_spec(spec,view))
        with mpl.rc_context(E.export_rc(opts)):
            fig,axes=bridge.render_snapshot(E.build_spec(spec,opts),opts,100)
            fig.canvas.draw()
        mask=next(c for c in axes[0].collections if c.get_gid()=='vexpace-background-mask')
        np.testing.assert_allclose(mask.get_cmap()(0),to_rgba('white'))
        assert axes[0].images[0].get_cmap().name==field.get_cmap().name
        p.close()
