"""Numerical coupling controls persist and appear in the existing GUI forms."""
from PySide6.QtWidgets import QApplication
from picstudio.model import model as M, schema as S
from picstudio.gui.forms import FieldForm
from picstudio.gui.results import LivePanel


def test_coupling_controls_round_trip_and_history_labels(tmp_path):
    app=QApplication.instance() or QApplication([])
    m=M.new_model('2D-ZY','electromagnetic')
    form=FieldForm(S.SIMULATION,m['simulation'])
    assert form.widgets['coupling_tolerance'].isHidden()
    combo=form.widgets['em_coupling']
    combo.setCurrentIndex(combo.findData('work-centered'))
    assert m['simulation']['em_coupling']=='work-centered'
    assert not form.widgets['coupling_tolerance'].isHidden()
    assert form.widgets['particle_pusher'].isHidden()
    path=tmp_path/'centered.pic.json';M.save(m,path)
    assert M.load(path)['simulation']['em_coupling']=='work-centered'
    panel=LivePanel();panel._rebuild_signal_menu(['t','ED_R_exchange','ED_coupling_iterations'])
    labels=[a.text() for a in panel.sig_menu.actions()]
    assert 'Particle minus native-grid self-field work [J/m]' in labels
    assert 'Work-centered solve iterations' in labels
    panel.close();form.close()
