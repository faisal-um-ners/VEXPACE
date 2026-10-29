"""Real editor -> save -> solver -> same-folder rerun regression coverage."""
import copy
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from picstudio.expr import Evaluator
from picstudio.gui.forms import FieldForm
from picstudio.gui.main_window import MainWindow
from picstudio.model import model as M
from picstudio.sources.pulses import build_pulse


def pulse_model():
    m = M.new_model('1D-Z')
    m['parallel'].update(mode='serial', threads=1)
    m['domain'].update(z_max='1e-3', nz='24')
    m['simulation'].update(dt='1e-12', t_end='3e-10')
    m['diagnostics'].update(output_dir='output', history_every='1', field_every='50',
                            particle_every='50', live_every='5')
    m['species'] = [dict(name='e', preset='electron')]
    settings = dict(shape='square', start='5e-11', duration='1e-10', amount='10')
    p = build_pulse(settings, M.evaluator(m))
    m['emitters'] = [dict(name='beam', species='e', model='beam', energy='100', z0='0',
                          current_density=p['expression'], t_start=p['t_start'], t_stop=p['t_stop'],
                          pulse_builder=dict(settings, generated_expression=p['expression']))]
    return M.complete(m)


def wait_for(app, condition, timeout=30):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(5)
    assert condition(), 'GUI or solver did not finish in time'


@pytest.fixture
def editor(tmp_path):
    app = QApplication.instance() or QApplication([])
    with patch.object(MainWindow, 'draw_geometry'):
        w = MainWindow()
        lastdir = w.settings.value('lastdir')
        path = tmp_path / 'pulse.pic.json'
        M.save(pulse_model(), path)
        w.open_file(str(path))
        w.populate_tree(select=('emitters', 0))
        w.show()
        w.activateWindow()
        app.processEvents()
        yield app, w, path
        if w.proc is not None:
            w.proc.kill()
            wait_for(app, lambda: w.proc is None)
        w.dirty = False
        w.close()
        if lastdir is None:
            w.settings.remove('lastdir')
        else:
            w.settings.setValue('lastdir', lastdir)
        app.processEvents()


def test_run_does_not_use_old_file_if_save_cancelled_or_failed(editor):
    _, w, path = editor
    before = path.read_bytes()
    w.model['emitters'][0]['current_density'] = '999'
    w.dirty = True
    with patch.object(w, 'save', return_value=False), patch.object(w, '_launch') as launch:
        w.run()
    launch.assert_not_called()
    assert path.read_bytes() == before


def test_run_commits_focused_numeric_editor_before_saving(editor):
    app, w, path = editor
    form = w.scroll.widget().findChild(FieldForm)
    edit = form.widgets['energy']
    edit.setFocus()
    app.processEvents()
    edit.selectAll()
    QTest.keyClicks(edit, '250')
    assert w.model['emitters'][0]['energy'] == '100'  # Still being edited.
    with patch.object(w, '_launch') as launch:
        w.run()  # Toolbar/keyboard actions do not necessarily remove editor focus.
    launch.assert_called_once()
    assert M.load(path)['emitters'][0]['energy'] == '250'


def apply_pulse_with_real_dialog(app, form, shape, peak):
    errors = []
    def edit_modal():
        try:
            d = app.activeModalWidget()
            assert d is not None
            d.kind.setCurrentIndex(d.kind.findData(shape))
            for widget, value in ((d.start, '.04'), (d.duration, '.16'), (d.rise, '.03'), (d.amount, str(peak))):
                widget.setFocus()
                widget.selectAll()
                QTest.keyClicks(widget, value)
            assert not d.error.text(), d.error.text()
            QTest.mouseClick(d.buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
        except Exception as exc:
            errors.append(exc)
            if app.activeModalWidget() is not None:
                app.activeModalWidget().reject()
    QTimer.singleShot(0, edit_modal)
    QTest.mouseClick(form.pulse_button, Qt.LeftButton)
    if errors:
        raise errors[0]


def test_actual_shape_changes_reach_repeated_solver_runs_and_live_results(editor):
    app, w, path = editor
    histories = []
    for shape, peak in [('square', 10), ('gaussian', 75), ('trapezoid', 30)]:
        form = w.scroll.widget().findChild(FieldForm)
        previous_live = w.live.data
        previous_results = w.results.res
        apply_pulse_with_real_dialog(app, form, shape, peak)
        assert w.model['emitters'][0]['pulse_builder']['shape'] == shape
        assert w.live.data is previous_live
        assert w.results.res is previous_results
        if previous_live is not None:
            assert not w.live.model_notice.isHidden()
        w.run()
        assert w.live.data is None and w.results.res is None
        wait_for(app, lambda: w.proc is None)
        assert 'Process finished with exit code 0' in w.log.toPlainText()
        saved = M.load(path)
        run_copy = M.load(Path(w.output_dir())/'model.pic.json')
        assert run_copy['emitters'][0]['pulse_builder']['shape'] == shape
        assert run_copy['emitters'][0]['current_density'] == saved['emitters'][0]['current_density']
        hist = np.genfromtxt(Path(w.output_dir())/'history.csv', delimiter=',', names=True)
        t = hist['t']; observed = abs(hist['Iemit_beam'])
        func = M.evaluator(saved).func_t(saved['emitters'][0]['current_density'])
        dt = M.evaluator(saved).num(saved['simulation']['dt'])
        expected = np.array([func(x-dt) for x in t])
        # Do not compare exactly on a hard gate where floating accumulation can
        # place one sample on either side of the endpoint.
        gate = build_pulse(saved['emitters'][0]['pulse_builder'], M.evaluator(saved))
        safe = (abs(t-dt-gate['start']) > dt/10) & (abs(t-dt-gate['start']-gate['duration']) > dt/10) & (t > 0)
        np.testing.assert_allclose(observed[safe], expected[safe], atol=2e-5, rtol=2e-6)
        assert w.live.data is not None
        assert w.live.model_notice.isHidden()
        cols = [str(c) for c in w.live.data['history_columns']]
        live = np.asarray(w.live.data['history'])
        assert np.max(abs(live[:, cols.index('Iemit_beam')])) == pytest.approx(peak, rel=.001)
        histories.append(observed)
    assert not np.array_equal(histories[0], histories[1])
    assert not np.array_equal(histories[1], histories[2])


def test_settings_edits_preserve_last_run_plots_zoom_and_signals(editor):
    app, w, _ = editor
    w.run()
    wait_for(app, lambda: w.proc is None)
    previous_live, previous_results = w.live.data, w.results.res
    axis = w.live.plot.axes[-1]
    axis.set_xlim(4e-11, 2e-10)
    selected = set(w.live.checked)
    with patch.object(w.live, 'clear') as clear, patch.object(w.live, 'redraw') as redraw:
        w.model['emitters'][0]['energy'] = '200'
        w.mark_dirty()
        app.processEvents()
    clear.assert_not_called()
    redraw.assert_not_called()
    assert w.live.data is previous_live and w.results.res is previous_results
    assert w.live.plot.axes[-1] is axis
    assert axis.get_xlim() == (4e-11, 2e-10)
    assert w.live.checked == selected
    assert not w.live.model_notice.isHidden()
    assert not w.results.model_notice.isHidden()


def test_failed_new_run_does_not_reload_previous_history(editor):
    app, w, _ = editor
    w.run()
    wait_for(app, lambda: w.proc is None)
    assert w.live.data is not None and w.results.res is not None
    w._launch(['/definitely/missing/vexpace-solver'], w.output_dir())
    wait_for(app, lambda: w.proc is None)
    assert w.live.data is None and w.results.res is None
    assert 'earlier results were not reloaded' in w.log.toPlainText()


def test_open_changed_model_does_not_present_old_output_as_current(editor):
    app, w, path = editor
    w.run()
    wait_for(app, lambda: w.proc is None)
    old = M.load(path)
    old['emitters'][0]['energy'] = '999'
    M.save(old, path)
    w.open_file(str(path))
    assert w.live.data is None and w.results.res is None
    assert 'earlier model settings' in w.log.toPlainText()


def test_f5_commits_focused_pulse_expression(editor):
    app, w, path = editor
    form = w.scroll.widget().findChild(FieldForm)
    edit = form.widgets['current_density']
    edit.setFocus()
    app.processEvents()
    edit.selectAll()
    expression = '250*gauss(t,1e-10,2e-11)'
    QTest.keyClicks(edit, expression)
    assert w.model['emitters'][0]['current_density'] != expression
    with patch.object(w, '_launch') as launch:
        w.act_run.trigger()
    launch.assert_called_once()
    assert M.load(path)['emitters'][0]['current_density'] == expression


def test_run_commits_parameter_table_cell_before_saving(editor):
    app, w, path = editor
    from PySide6.QtWidgets import QLineEdit
    from picstudio.gui.forms import ParameterTable
    w.model['parameters']['beam_energy'] = '100'
    w.model['emitters'][0]['energy'] = 'beam_energy'
    M.save(w.model, path)
    w.populate_tree(select=('parameters', None))
    app.processEvents()
    panel = w.scroll.widget().findChild(ParameterTable)
    item = panel.table.item(0, 1)
    panel.table.setCurrentItem(item)
    panel.table.editItem(item)
    app.processEvents()
    edit = QApplication.focusWidget()
    assert isinstance(edit, QLineEdit)
    edit.selectAll()
    QTest.keyClicks(edit, '350')
    with patch.object(w, '_launch') as launch:
        w.run()
    launch.assert_called_once()
    assert M.load(path)['parameters']['beam_energy'] == '350'


def test_pulse_reopening_and_unit_changes_preserve_parameters_without_expression_growth(editor):
    app, w, _ = editor
    from picstudio.gui.source_designer import PulseDialog
    spec = copy.deepcopy(w.model['emitters'][0])
    p = spec['pulse_builder']
    p['duration'] = 'duration'
    compiled = build_pulse(p, Evaluator({'duration': '1.6e-10'}))
    p['generated_expression'] = compiled['expression']
    spec.update(current_density=compiled['expression'], t_start=compiled['t_start'], t_stop=compiled['t_stop'])
    first = None
    for _ in range(20):
        d = PulseDialog(spec, dict(parameters={'duration': '1.6e-10'}))
        for unit in ('ps', 'µs', 's', 'ns'):
            d.time_unit.setCurrentIndex(d.time_unit.findText(unit))
        spec = d.result_spec()
        assert spec['pulse_builder']['duration'] == 'duration'
        if first is None:
            first = copy.deepcopy(spec)
        else:
            assert spec == first
        assert len(spec['current_density']) < 1000
        d.close()
    new_ev = Evaluator({'duration': '3.2e-10'})
    assert new_ev.num(spec['t_stop']) == pytest.approx(3.7e-10)
    app.processEvents()


@pytest.mark.parametrize('filename,shape', [('source_designer_pulse_rz', 'square'),
                                          ('source_designer_pulse_zy', 'gaussian')])
def test_actual_2d_dialog_change_reaches_local_mesh_solver(editor, filename, shape):
    app, w, path = editor
    template = Path(__file__).resolve().parents[1]/'examples'/(filename+'.pic.json')
    model = M.load(template)
    model['diagnostics']['output_dir'] = 'output'
    M.save(model, path)
    w.open_file(str(path))
    w.populate_tree(select=('emitters', 0))
    app.processEvents()
    form = w.scroll.widget().findChild(FieldForm)
    apply_pulse_with_real_dialog(app, form, shape, 75)
    w.run()
    wait_for(app, lambda: w.proc is None, timeout=60)
    directory = Path(w.output_dir())
    m = M.load(directory/'model.pic.json')
    assert m['emitters'][0]['pulse_builder']['shape'] == shape
    p = build_pulse(m['emitters'][0]['pulse_builder'], M.evaluator(m))
    hist = np.genfromtxt(directory/'history.csv', delimiter=',', names=True)
    radius = M.evaluator(m).num('R')
    area = np.pi*radius**2 if m['simulation']['geometry']=='2D-RZ' else radius
    q = np.sum(abs(hist['Iemit_pulsed_beam'][1:])*np.diff(hist['t']))
    assert q == pytest.approx(p['charge']*area, rel=.01)
    assert w.live.data is not None and w.results.res is not None
    assert hist['step'][-1] == 1500
    assert hist['N_electrons'][-1] == 0
