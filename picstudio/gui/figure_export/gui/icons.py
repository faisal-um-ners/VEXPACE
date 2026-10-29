"""Vector icon set (drawn for PASCHEN-1D Studio; 24×24 stroke icons, recolourable)."""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_S = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
      'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')

PATHS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h5v-6h4v6h5V9.5"/>',
    "model": '<path d="M12 2.8 3.5 7.4v9.2L12 21.2l8.5-4.6V7.4z"/><path d="M3.8 7.6 12 12l8.2-4.4M12 12v9"/>',
    "play": '<path d="M7 4.5v15l12.5-7.5z" fill="{c}"/>',
    "run": '<path d="M7 4.5v15l12.5-7.5z"/>',
    "pause": '<rect x="6" y="5" width="4" height="14" rx="1" fill="{c}"/><rect x="14" y="5" width="4" height="14" rx="1" fill="{c}"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="{c}"/>',
    "results": '<path d="M3.5 20.5h17"/><path d="M4 16.5 9 11l4 3.5 7-8.5"/><circle cx="9" cy="11" r="1.2" fill="{c}"/><circle cx="13" cy="14.5" r="1.2" fill="{c}"/>',
    "chart": '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M7 15.5l3-4 3 2 4-5.5"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 1 1 3.4 2.4c-.7.3-1 .9-1 1.6v.4"/><circle cx="12" cy="17" r=".6" fill="{c}"/>',
    "book": '<path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H11v16H5.5A1.5 1.5 0 0 0 4 20.5z"/><path d="M20 4.5A1.5 1.5 0 0 0 18.5 3H13v16h5.5a1.5 1.5 0 0 1 1.5 1.5z"/>',
    "sweep": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2.2"/><circle cx="10" cy="17" r="2.2"/><path d="M4 12h6M14 12h6"/><circle cx="12" cy="12" r="2.2"/>',
    "new": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>',
    "wizard": '<path d="m4 20 10.5-10.5M13 5l1-2 1 2 2 1-2 1-1 2-1-2-2-1zM19 11l.6-1.2L21 9l-1.4-.8L19 7l-.6 1.2L17 9l1.4.8zM16 8l-2 2"/>',
    "open": '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5V18a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 18z"/>',
    "folder": '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5V18a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 18z"/>',
    "save": '<path d="M5 3.5h11l3.5 3.5v12A1.5 1.5 0 0 1 18 20.5H6A1.5 1.5 0 0 1 4.5 19V5A1.5 1.5 0 0 1 5 3.5z"/><path d="M8 3.5v5h7v-5M8 20.5v-6h8v6"/>',
    "check": '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.9 7.5-9.5V6z"/><path d="m8.8 12 2.2 2.2 4.4-4.6"/>',
    "ok": '<circle cx="12" cy="12" r="9"/><path d="m8 12.3 2.6 2.6L16.2 9.3"/>',
    "warning": '<path d="M12 3.5 2.8 19.5h18.4z"/><path d="M12 10v4.5"/><circle cx="12" cy="17" r=".6" fill="{c}"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.8" r=".6" fill="{c}"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
    "export": '<path d="M12 15V3.5M7.5 8 12 3.5 16.5 8"/><path d="M5 13.5V19a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 19v-5.5"/>',
    "download": '<path d="M12 3.5V15M7.5 10.5 12 15l4.5-4.5"/><path d="M5 17v2a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 19v-2"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.3-4.6L4 8.5M4 13a8 8 0 0 0 14.3 4.6l1.7-2.1"/><path d="M4 4v4.5h4.5M20 20v-4.5h-4.5"/>',
    "trash": '<path d="M4 6.5h16M9.5 6.5V4h5v2.5M6.5 6.5l1 13.5h9l1-13.5M10 10.5v6M14 10.5v6"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "reset": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/><path d="M3.5 3.5v5h5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "grid": '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M3.5 9.2h17M3.5 14.8h17M9.2 3.5v17M14.8 3.5v17"/>',
    "gap": '<path d="M5 3.5v17M19 3.5v17"/><path d="M8 12h8M8 12l2-2M8 12l2 2M16 12l-2-2M16 12l-2 2"/>',
    "gas": '<circle cx="7" cy="8" r="2"/><circle cx="16" cy="6.5" r="2.5"/><circle cx="11" cy="15" r="2.6"/><circle cx="18" cy="16" r="1.6"/><circle cx="5.5" cy="17.5" r="1.3"/>',
    "atom": '<circle cx="12" cy="12" r="1.6" fill="{c}"/><ellipse cx="12" cy="12" rx="9.5" ry="3.8"/><ellipse cx="12" cy="12" rx="9.5" ry="3.8" transform="rotate(60 12 12)"/><ellipse cx="12" cy="12" rx="9.5" ry="3.8" transform="rotate(120 12 12)"/>',
    "electron": '<circle cx="12" cy="12" r="7.5"/><path d="M8.5 12h7"/>',
    "ion": '<circle cx="12" cy="12" r="7.5"/><path d="M8.5 12h7M12 8.5v7"/>',
    "alpha": '<path d="M18.5 7c-1.5 6-3 10-5.2 10-2.6 0-4.3-1.9-4.3-5S10.9 7 13.4 7c2.3 0 3.4 3.5 5.6 10"/>',
    "nu": '<path d="M6 7l4.5 10.5c3.5-3 6.5-7 7.5-10.5"/>',
    "recomb": '<circle cx="7" cy="12" r="3"/><circle cx="17" cy="12" r="3"/><path d="M10 12h4"/>',
    "wave": '<path d="M2.5 12c2-6 4-6 6 0s4 6 6 0 4-6 6 0"/>',
    "circuit": '<path d="M3 12h3l1.5-3 2 6 2-6 2 6 1.5-3H18"/><path d="M18 9v6M21 10v4"/>',
    "boundary": '<rect x="3.5" y="4" width="4" height="16" rx="1"/><rect x="16.5" y="4" width="4" height="16" rx="1"/><path d="M10 9h4M10 15h4"/>',
    "emission": '<path d="M4 3.5v17"/><path d="M8 7l4 2M8 12h5M8 17l4-2"/><path d="M15 6.5 20 4M16 12h5M15 17.5l5 2.5"/>',
    "output": '<path d="M4 6h16M4 12h10M4 18h7"/><path d="M17 15v6M14.5 18.5 17 21l2.5-2.5"/>',
    "table": '<rect x="3.5" y="4" width="17" height="16" rx="2"/><path d="M3.5 9h17M3.5 14.5h17M10 9v11"/>',
    "film": '<rect x="3.5" y="4" width="17" height="16" rx="2"/><path d="M7.5 4v16M16.5 4v16M3.5 8h4M3.5 12h4M3.5 16h4M16.5 8h4M16.5 12h4M16.5 16h4"/>',
    "compare": '<path d="M4 18 9 11l4 4 7-9"/><path d="M4 14l5-3 4 1 7-4" stroke-dasharray="2 2.4"/>',
    "map": '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M3.5 15c3-1 4-6 7-6s4 7 10 4"/>',
    "profile": '<path d="M3.5 20.5h17M3.5 3.5v17"/><path d="M5 18c3-12 7-12 9-6s4 4 6 2"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="5" cy="6" r="1" fill="{c}"/><circle cx="5" cy="12" r="1" fill="{c}"/><circle cx="5" cy="18" r="1" fill="{c}"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M12.5 15H17"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
    "quote": '<path d="M5 18c2.5-1 4-3.5 4-7V7H4.5v5H8M15 18c2.5-1 4-3.5 4-7V7h-4.5v5H18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "chevron_right": '<path d="m9 6 6 6-6 6"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6"/>',
    "chevron_up": '<path d="m6 15 6-6 6 6"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M8 14.2h8"/>',
    "file": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5M8.5 13h7M8.5 16.5h5"/>',
    "dot": '<circle cx="12" cy="12" r="4" fill="{c}" stroke="none"/>',
    "skip_back": '<path d="M18 5 9 12l9 7z" fill="{c}"/><path d="M6 5v14"/>',
    "skip_fwd": '<path d="m6 5 9 7-9 7z" fill="{c}"/><path d="M18 5v14"/>',
    "step_back": '<path d="m15 6-6 6 6 6"/>',
    "step_fwd": '<path d="m9 6 6 6-6 6"/>',
    "zoom": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5M8 10.5h5M10.5 8v5"/>',
    "pan": '<path d="M12 3v18M3 12h18M12 3l-2.5 2.5M12 3l2.5 2.5M12 21l-2.5-2.5M12 21l2.5-2.5M3 12l2.5-2.5M3 12l2.5 2.5M21 12l-2.5-2.5M21 12l-2.5 2.5"/>',
    "fit": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "log": '<path d="M4 20h16M4 4v16"/><path d="M6 17c2-8 4-11 13-12"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="9.5" r="1.6"/><path d="m4 17 5-5 4 4 2.5-2.5L20 18"/>',
    "csv": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5M8 13h8M8 16.5h8M11 11v8.5"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "bolt": '<path d="M13 2.5 4.5 13.5H12l-1 8 8.5-11H12z"/>',
    "flask": '<path d="M9.5 3h5M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/><path d="M7.5 15h9"/>',
    "github": '<path d="M9 19c-4 1.3-4-2-6-2.5m12 5v-3.5a3 3 0 0 0-.9-2.4c3-.3 6.1-1.5 6.1-6.6a5.1 5.1 0 0 0-1.4-3.6 4.8 4.8 0 0 0-.1-3.6s-1.1-.3-3.7 1.4a12.6 12.6 0 0 0-6.6 0C5.8 1.9 4.7 2.2 4.7 2.2a4.8 4.8 0 0 0-.1 3.6 5.1 5.1 0 0 0-1.4 3.6c0 5 3.1 6.3 6.1 6.6a3 3 0 0 0-.9 2.4V22"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/><path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
    "queue": '<rect x="3.5" y="4" width="17" height="4.5" rx="1.5"/><rect x="3.5" y="10" width="17" height="4.5" rx="1.5"/><path d="M3.5 18.5h10"/>',
    "pin": '<path d="M12 17v4.5M8 3.5h8l-1 6 3 3.5H6l3-3.5z"/>',
    "star": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    "logo": '',
}


def svg(name: str, color: str = "#334155", width: float = 1.8) -> str:
    body = PATHS.get(name, PATHS["dot"]).replace("{c}", color)
    return _S.format(c=color, w=width, body=body)


@lru_cache(maxsize=512)
def pixmap(name: str, color: str = "#334155", size: int = 20, width: float = 1.8, dpr: float = 2.0) -> QPixmap:
    data = QByteArray(svg(name, color, width).encode("utf-8"))
    r = QSvgRenderer(data)
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = "#334155", size: int = 20, active_color: str | None = None,
         width: float = 1.8) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size, width), QIcon.Normal, QIcon.Off)
    if active_color:
        ic.addPixmap(pixmap(name, active_color, size, width), QIcon.Normal, QIcon.On)
        ic.addPixmap(pixmap(name, active_color, size, width), QIcon.Active, QIcon.Off)
        ic.addPixmap(pixmap(name, active_color, size, width), QIcon.Selected, QIcon.Off)
    return ic


LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs>
 <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="#3b82f6"/><stop offset="0.55" stop-color="#6366f1"/><stop offset="1" stop-color="#a855f7"/>
 </linearGradient>
 <radialGradient id="glow" cx="0.5" cy="0.5" r="0.5">
  <stop offset="0" stop-color="#ffffff" stop-opacity="0.95"/><stop offset="0.45" stop-color="#e9d5ff" stop-opacity="0.55"/>
  <stop offset="1" stop-color="#e9d5ff" stop-opacity="0"/>
 </radialGradient>
</defs>
<rect x="2" y="2" width="60" height="60" rx="15" fill="url(#g)"/>
<rect x="12" y="13" width="6" height="38" rx="2" fill="#ffffff" opacity="0.95"/>
<rect x="46" y="13" width="6" height="38" rx="2" fill="#ffffff" opacity="0.95"/>
<ellipse cx="32" cy="32" rx="12" ry="17" fill="url(#glow)"/>
<path d="M19 32c3-6 5-6 7 0s4 6 6 0 4-6 6 0 4 6 6 0" fill="none" stroke="#ffffff" stroke-width="2.4" stroke-linecap="round"/>
</svg>"""


@lru_cache(maxsize=8)
def logo_pixmap(size: int = 64, dpr: float = 2.0) -> QPixmap:
    r = QSvgRenderer(QByteArray(LOGO_SVG.encode("utf-8")))
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 32, 64, 128, 256):
        ic.addPixmap(logo_pixmap(s, 1.0))
    return ic


_CHECK_FILE = {"path": None}


def check_icon_file() -> str:
    """Path of a white check-mark SVG for QCheckBox indicators in the style sheet."""
    if _CHECK_FILE["path"] and os.path.exists(_CHECK_FILE["path"]):
        return _CHECK_FILE["path"]
    d = os.path.join(tempfile.gettempdir(), "paschen_studio_icons")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "check_white.svg")
    with open(p, "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#ffffff" '
                'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>')
    _CHECK_FILE["path"] = p.replace("\\", "/")
    return _CHECK_FILE["path"]


_UI_SVGS = {
    "chev_down": '<path d="m6 9 6 6 6-6" stroke="{c}" stroke-width="2.4" fill="none" stroke-linecap="round" '
                 'stroke-linejoin="round"/>',
    "chev_up": '<path d="m6 15 6-6 6 6" stroke="{c}" stroke-width="2.4" fill="none" stroke-linecap="round" '
               'stroke-linejoin="round"/>',
    "radio_dot": '<circle cx="12" cy="12" r="5" fill="{c}"/>',
}


def ui_asset_file(name: str, color: str) -> str:
    """Write a tiny SVG used by the style sheet (arrows, radio dot) and return its path."""
    d = os.path.join(tempfile.gettempdir(), "paschen_studio_icons")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{name}_{color.strip('#')}.svg")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                    + _UI_SVGS[name].replace("{c}", color) + "</svg>")
    return p.replace("\\", "/")

