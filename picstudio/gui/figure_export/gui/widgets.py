"""Reusable widgets: unit-aware number input, toggle switch, chips, cards, flow layout."""
from __future__ import annotations

import math
import re

from PySide6.QtCore import (Property, QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt,
                            Signal)
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QLayout, QLineEdit, QMenu, QPushButton, QScrollArea, QSizePolicy,
                               QStyle, QToolButton, QVBoxLayout, QWidget)

from ..units import QuantityError, format_quantity, parse_quantity
from . import icons
from . import theme as T


def label(text: str = "", obj: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lab = QLabel(text)
    if obj:
        lab.setObjectName(obj)
    lab.setWordWrap(wrap)
    if selectable:
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def hline() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {T.c('border')};")
    return f


def card(obj: str = "card", margins=(16, 14, 16, 14), spacing: int = 8, shadow: bool = False):
    f = QFrame()
    f.setObjectName(obj)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    if shadow:
        add_shadow(f)
    return f, lay


def add_shadow(w: QWidget, blur: int = 24, dy: int = 4, alpha: int = 28):
    eff = QGraphicsDropShadowEffect(w)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(15, 23, 42, alpha))
    w.setGraphicsEffect(eff)


def chip(text: str, accent: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("chipAccent" if accent else "chip")
    return lab


def badge(status: str, text: str | None = None) -> QLabel:
    lab = QLabel(text or status.capitalize())
    lab.setObjectName(f"badge_{status}")
    lab.setAlignment(Qt.AlignCenter)
    return lab


def icon_button(name: str, tip: str = "", obj: str = "ghost", size: int = 18, checkable: bool = False,
                text: str = "") -> QToolButton:
    b = QToolButton()
    b.setObjectName(obj)
    b.setIcon(icons.icon(name, T.c("text2"), size, active_color=T.c("accent")))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    return b


def push(text: str, obj: str | None = None, icon_name: str | None = None, icon_color: str | None = None,
         tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if icon_name:
        col = icon_color or ("#ffffff" if obj in ("primary", "run") else T.c("text2"))
        b.setIcon(icons.icon(icon_name, col, 16))
        b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


# ---------------------------------------------------------------------------
class SegmentedControl(QFrame):
    """A small two-or-more option switch ("Essentials | All settings"). Emits ``changed(index)``."""

    changed = Signal(int)

    def __init__(self, options: list[str], tips: list[str] | None = None, current: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for i, text in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if tips and i < len(tips):
                b.setToolTip(tips[i])
            self.group.addButton(b, i)
            lay.addWidget(b, 1)
            self.buttons.append(b)
        self.buttons[max(0, min(current, len(options) - 1))].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)

    def index(self) -> int:
        return self.group.checkedId()

    def setIndex(self, i: int, emit: bool = False):  # noqa: N802 - Qt naming style
        if 0 <= i < len(self.buttons) and i != self.index():
            self.buttons[i].setChecked(True)
            if emit:
                self.changed.emit(i)


class RunButton(QWidget):
    """The one primary action: a green "Run" button with a small attached menu for the variants
    (test run, parameter sweep). Keeps a single prominent call to action instead of three equal buttons."""

    def __init__(self, text: str = "Run", tip: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.main = push(text, "run", icon_name="play", tip=tip)
        self.main.setProperty("split", True)
        self.more = QPushButton()
        self.more.setObjectName("runMore")
        self.more.setIcon(icons.icon("chevron_down", "#ffffff", 14))
        self.more.setIconSize(QSize(14, 14))
        self.more.setCursor(Qt.PointingHandCursor)
        self.more.setToolTip("More ways to run: test run, parameter sweep")
        self.menu = QMenu(self)
        self.more.clicked.connect(self._popup)
        lay.addWidget(self.main)
        lay.addWidget(self.more)
        self.clicked = self.main.clicked

    def _popup(self):
        self.menu.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def add_action(self, text: str, slot, icon_name: str | None = None, shortcut_hint: str = ""):
        a = self.menu.addAction(text + (f"\t{shortcut_hint}" if shortcut_hint else ""))
        if icon_name:
            a.setIcon(icons.icon(icon_name, T.c("text2"), 16))
        a.triggered.connect(slot)
        return a


# ---------------------------------------------------------------------------
class QuantityEdit(QLineEdit):
    """Line edit for a physical quantity.

    Shows compact engineering notation ("16 pF") and accepts flexible input
    ("16p", "1.6e-11", "16 pF", "inf").  Emits ``committed(float)``.
    """

    committed = Signal(object)

    def __init__(self, unit: str = "", value=None, integer: bool = False, allow_inf: bool = True,
                 allow_none: bool = False, minimum: float | None = None, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.integer = integer
        self.allow_inf = allow_inf
        self.allow_none = allow_none
        self.minimum = minimum
        self._value = value
        self.setMinimumWidth(120)
        self.editingFinished.connect(self._commit)
        self._refresh_text()
        tips = ["Type a number"]
        if unit:
            tips.append(f"Unit: {unit}. SI prefixes work, e.g. 3.5 m{unit}, 16 p{unit}" if unit in
                        ("m", "s", "V", "F", "H", "Ω", "Hz", "J", "A") else f"Unit: {unit}")
        if allow_inf:
            tips.append("'inf' = infinite")
        if allow_none:
            tips.append("leave empty for None")
        self.setPlaceholderText("None" if allow_none else "")
        self._base_tip = " · ".join(tips)

    def value(self):
        return self._value

    def setValue(self, v) -> None:
        self._value = v
        self.setProperty("invalid", False)
        self._repolish()
        self._refresh_text()

    def _fmt(self, v, precise: bool = False) -> str:
        if v is None:
            return ""
        if self.integer:
            try:
                return f"{int(v):,}".replace(",", " ") if not precise else str(int(v))
            except (TypeError, ValueError):
                return str(v)
        if precise:
            if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
                return format_quantity(v, self.unit)
            return format_quantity(v, self.unit, digits=12)
        return format_quantity(v, self.unit, digits=5)

    def _refresh_text(self):
        self.setText(self._fmt(self._value, precise=self.hasFocus()))

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.setText(self._fmt(self._value, precise=True))
        self.selectAll()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if not self.property("invalid"):
            self.setText(self._fmt(self._value))

    def _parse(self, text: str):
        t = text.strip()
        if not t:
            if self.allow_none:
                return None
            raise QuantityError("a value is required")
        if self.integer:
            t2 = t.replace(" ", "").replace("_", "").replace(",", "")
            try:
                v = float(t2)
            except ValueError:
                v = parse_quantity(t, self.unit, allow_inf=False)
            if not math.isfinite(v) or abs(v - round(v)) > 1e-9 * max(1.0, abs(v)):
                raise QuantityError("a whole number is required")
            v = int(round(v))
        else:
            v = parse_quantity(t, self.unit, allow_inf=self.allow_inf)
        if self.minimum is not None and v is not None and v < self.minimum:
            raise QuantityError(f"must be ≥ {self.minimum:g}")
        return v

    def _commit(self):
        try:
            v = self._parse(self.text())
        except (QuantityError, ValueError) as exc:
            self.setProperty("invalid", True)
            self.setToolTip(f"⚠ {exc}\n{self._base_tip}")
            self._repolish()
            return
        self.setProperty("invalid", False)
        self.setToolTip(self._base_tip)
        self._repolish()
        changed = not _same(v, self._value)
        self._value = v
        if not self.hasFocus():
            self.setText(self._fmt(v))
        if changed:
            self.committed.emit(v)

    def _repolish(self):
        self.style().unpolish(self)
        self.style().polish(self)


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    if math.isinf(fa) or math.isinf(fb) or math.isnan(fa) or math.isnan(fb):
        return (fa == fb) or (math.isnan(fa) and math.isnan(fb))
    return math.isclose(fa, fb, rel_tol=1e-13, abs_tol=0.0) or fa == fb


# ---------------------------------------------------------------------------
class ToggleSwitch(QAbstractButton):
    """iOS-style switch; behaves like a checkable button."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = float(v)
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def setChecked(self, on: bool) -> None:  # noqa: N802 - Qt API
        super().setChecked(on)
        self._pos = 1.0 if on else 0.0
        self.update()

    def sizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off = QColor(T.c("border2"))
        on = QColor(T.c("accent"))
        col = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos))
        if not self.isEnabled():
            col.setAlpha(110)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, col)
        d = r.height() - 4
        x = r.left() + 2 + (r.width() - d - 4) * self._pos
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(x, r.top() + 2.6, d, d))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.top() + 2, d, d))
        p.end()


# ---------------------------------------------------------------------------
class ChoiceCombo(QComboBox):
    """Combo box showing friendly labels while storing the raw solver value."""

    committed = Signal(object)

    def __init__(self, choices: list[str], labels: dict[str, str] | None = None, value=None, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(14)
        for ch in choices:
            self.addItem((labels or {}).get(ch, ch), ch)
            self.setItemData(self.count() - 1, f"value: {ch}", Qt.ToolTipRole)
        self.setValue(value)
        self.activated.connect(lambda i: self.committed.emit(self.itemData(i)))

    def value(self):
        return self.currentData()

    def setValue(self, v):
        i = self.findData(v)
        if i < 0 and v is not None:
            self.addItem(str(v), v)
            i = self.count() - 1
        self.blockSignals(True)
        self.setCurrentIndex(max(i, 0))
        self.blockSignals(False)


# ---------------------------------------------------------------------------
class FlowLayout(QLayout):
    """Wrapping layout for chips/checkboxes."""

    def __init__(self, parent=None, hspacing: int = 6, vspacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._h = hspacing
        self._v = vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, w):  # noqa: N802
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):  # noqa: N802
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, r, test):
        x, y, lh = r.x(), r.y(), 0
        for it in self._items:
            sz = it.sizeHint()
            nx = x + sz.width() + self._h
            if nx - self._h > r.right() and lh > 0:
                x = r.x()
                y += lh + self._v
                nx = x + sz.width() + self._h
                lh = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x = nx
            lh = max(lh, sz.height())
        return y + lh - r.y()


# ---------------------------------------------------------------------------
class StatTile(QFrame):
    def __init__(self, title: str, value: str = "–", sub: str = "", icon_name: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("cardFlat")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        if icon_name:
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, T.c("text3"), 14))
            top.addWidget(ic)
        self.t = label(title, "statLabel")
        self.t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.t, 1)
        top.addStretch()
        lay.addLayout(top)
        self.v = label(value, "statValue")
        self.v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.v.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self.v)
        self.s = label(sub, "hint", wrap=True)          # wraps instead of being cut off in narrow tiles
        self.s.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.s.setVisible(bool(sub))
        lay.addWidget(self.s)

    def set(self, value: str, sub: str | None = None):
        self.v.setText(value)
        self.v.setObjectName("statValueSmall" if len(value) > 11 else "statValue")
        self.v.style().unpolish(self.v)
        self.v.style().polish(self.v)
        self.v.setToolTip(value + (f"\n{sub}" if sub else ""))
        if sub is not None:
            self.s.setText(sub)
            self.s.setVisible(bool(sub))


class SectionHeader(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 2)
        lay.setSpacing(8)
        self.lab = label(title.upper(), "sectionTitle")
        lay.addWidget(self.lab)
        line = QFrame()
        line.setFixedHeight(1)
        line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        line.setStyleSheet(f"background: {T.c('border')};")
        lay.addWidget(line, 1)


class Collapsible(QWidget):
    """A titled section that can be folded."""

    def __init__(self, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.btn = QToolButton()
        self.btn.setObjectName("ghost")
        self.btn.setText(title)
        self.btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn.setCheckable(True)
        self.btn.setChecked(expanded)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.toggled.connect(self._toggle)
        v.addWidget(self.btn)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(4, 0, 0, 0)
        self.body_lay.setSpacing(4)
        v.addWidget(self.body)
        self._toggle(expanded)

    def _toggle(self, on):
        self.body.setVisible(on)
        self.btn.setIcon(icons.icon("chevron_down" if on else "chevron_right", T.c("text2"), 14))


def _md_inline(s: str) -> str:
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<i>\1</i>", s)


def md_to_html(md: str) -> str:
    """Small markdown subset (paragraphs, bullet lists with continuation lines, headings, inline code, bold,
    italics) for prose taken from the solver's guides."""
    html, para, items = [], [], []
    p_style = "margin-top:0px; margin-bottom:8px;"

    def flush_para():
        if para:
            html.append(f"<p style='{p_style}'>" + " ".join(_md_inline(x) for x in para) + "</p>")
            para.clear()

    def flush_list():
        if items:
            html.append(f"<ul style='{p_style} -qt-list-indent:1;'>" +
                        "".join(f"<li style='margin-bottom:3px;'>{_md_inline(' '.join(i))}</li>" for i in items) +
                        "</ul>")
            items.clear()

    prev_blank = False
    for ln in md.splitlines():
        st = ln.strip()
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", ln)
        if st.startswith("#"):
            flush_para()
            flush_list()
            head = st.lstrip("#").strip()
            if head and not re.fullmatch(r"[A-Za-z_]\w*", head):   # skip bare class names ("### CircuitConfig")
                html.append(f"<p style='margin-top:6px; margin-bottom:6px;'><b>{_md_inline(head)}</b></p>")
        elif bullet:
            flush_para()
            items.append([bullet.group(1).strip()])
        elif not st:
            flush_para()
        elif items and not prev_blank:
            items[-1].append(st)                                 # continuation of the last bullet
        else:
            flush_list()
            para.append(st)
        prev_blank = not st
    flush_para()
    flush_list()
    return "".join(html)


def wrapping_label(html: str, obj: str | None = "muted") -> QLabel:
    """Rich-text label that always wraps to the width it is given (never widens its parent)."""
    lab = QLabel(html)
    if obj:
        lab.setObjectName(obj)
    lab.setTextFormat(Qt.RichText)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
    lab.setOpenExternalLinks(True)
    lab.setMinimumWidth(40)     # long words/paths must not set the width of the whole page
    return lab


class CodeBlock(QScrollArea):
    """Monospace block (code, ASCII circuit diagrams) that keeps its layout and scrolls sideways
    inside its own box instead of widening the page."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("codeBlock")
        self.setWidgetResizable(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)
        lab = QLabel(text)
        lab.setObjectName("codeText")
        lab.setTextFormat(Qt.PlainText)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        f.setPointSizeF(max(8.0, QFont().pointSizeF() - 1))
        lab.setFont(f)
        lab.setContentsMargins(10, 8, 10, 8)
        lab.adjustSize()
        self.setWidget(lab)
        self._lab = lab
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(40)
        self._fit()

    def _fit(self):
        sb = self.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, self)
        need_bar = self._lab.width() > max(1, self.viewport().width())
        self.setFixedHeight(self._lab.height() + (sb if need_bar else 0) + 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def sizeHint(self):  # noqa: D401
        return QSize(min(self._lab.width(), 400), self._lab.height())

    def minimumSizeHint(self):
        return QSize(40, self._lab.height())


class GuideText(QWidget):
    """Renders a markdown snippet from the solver's guides: prose wraps to the available width,
    fenced code blocks become side-scrolling CodeBlocks."""

    def __init__(self, md: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        text, code, in_code = [], [], False

        def flush_text():
            body = "\n".join(text).strip("\n")
            text.clear()
            if body.strip():
                lay.addWidget(wrapping_label(md_to_html(body)))

        for ln in md.splitlines():
            if ln.strip().startswith("```"):
                if in_code:
                    while code and not code[-1].strip():
                        code.pop()
                    if code:
                        lay.addWidget(CodeBlock("\n".join(code)))
                    code.clear()
                else:
                    flush_text()
                in_code = not in_code
                continue
            (code if in_code else text).append(ln)
        if code:
            lay.addWidget(CodeBlock("\n".join(code)))
        flush_text()


class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None, mode=Qt.ElideMiddle):
        super().__init__(text, parent)
        self._full = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def full_text(self) -> str:
        return self._full

    def setText(self, t):  # noqa: N802
        self._full = t
        self._elide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        fm = self.fontMetrics()
        shown = fm.elidedText(self._full, self._mode, max(10, self.width()))
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


def bold_font(pt_delta: float = 0, weight=QFont.DemiBold) -> QFont:
    f = QFont()
    f.setPointSizeF(max(6.0, f.pointSizeF() + pt_delta))
    f.setWeight(weight)
    return f

