"""Hide the eyedropper ("pick a colour from the screen") in the macOS Colors panel.

Picking a colour outside the application with that button can leave the app unresponsive when the panel
is opened from a Qt dialog, and Qt has no option for it on macOS. The rest of the panel (wheel, sliders,
palettes, pencils, favourites) is untouched. The button is found by its action, ``_magnify:``, through
the Objective-C runtime (ctypes only, no extra package). Anywhere else, or if anything is unexpected, this
does nothing.
"""
from __future__ import annotations

import sys

_ACTIONS = {"_magnify:"}


def hide_eyedropper() -> bool:
    """Hide the eyedropper button of the shared NSColorPanel. Returns True if a button was hidden."""
    if sys.platform != "darwin":
        return False
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        ctypes.cdll.LoadLibrary(ctypes.util.find_library("AppKit"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_getName.restype = ctypes.c_char_p
        objc.sel_getName.argtypes = [ctypes.c_void_p]

        def send(obj, sel, *args, restype=ctypes.c_void_p, argtypes=()):
            fn = ctypes.cast(objc.objc_msgSend,
                             ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
            return fn(obj, objc.sel_registerName(sel.encode()), *args)

        panel_cls = objc.objc_getClass(b"NSColorPanel")
        button_cls = objc.objc_getClass(b"NSButton")
        if not panel_cls or not button_cls:
            return False
        panel = send(panel_cls, "sharedColorPanel")
        root = send(panel, "contentView") if panel else None
        if not root:
            return False

        hidden = False
        stack, seen = [root], 0
        while stack and seen < 5000:
            v = stack.pop()
            seen += 1
            if send(v, "isKindOfClass:", button_cls, restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)):
                act = send(v, "action")
                name = objc.sel_getName(act).decode() if act else ""
                if name in _ACTIONS:
                    send(v, "setHidden:", True, restype=None, argtypes=(ctypes.c_bool,))
                    hidden = True
                continue
            subs = send(v, "subviews")
            n = send(subs, "count", restype=ctypes.c_ulong) if subs else 0
            for i in range(n):
                stack.append(send(subs, "objectAtIndex:", i, argtypes=(ctypes.c_ulong,)))
        return hidden
    except Exception:
        return False

