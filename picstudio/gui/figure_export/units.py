"""Engineering-notation formatting and forgiving parsing of physical quantities.

Examples (unit ``"F"``)::

    format_quantity(1.6e-11, "F")   -> "16 pF"
    parse_quantity("16 pF", "F")    -> 1.6e-11
    parse_quantity("16p", "F")      -> 1.6e-11
    parse_quantity("1.6e-11", "F")  -> 1.6e-11
    parse_quantity("inf", "F")      -> inf
"""
from __future__ import annotations

import math
import re

PREFIXES = [
    ("Y", 1e24), ("Z", 1e21), ("E", 1e18), ("P", 1e15), ("T", 1e12), ("G", 1e9), ("M", 1e6),
    ("k", 1e3), ("", 1.0), ("m", 1e-3), ("µ", 1e-6), ("n", 1e-9), ("p", 1e-12), ("f", 1e-15),
    ("a", 1e-18), ("z", 1e-21), ("y", 1e-24),
]
_PREFIX_VALUE = {p: v for p, v in PREFIXES}
_PREFIX_VALUE.update({"u": 1e-6, "μ": 1e-6, "K": 1e3, "c": 1e-2})
_PREFIX_BY_EXP = {int(round(math.log10(v))): p for p, v in PREFIXES}

# Units that read naturally with SI prefixes (16 pF, 3.5 mm, 70 µs ...)
PREFIXABLE = {"m", "s", "V", "A", "Ω", "F", "H", "Hz", "J", "W", "C", "A/m²", "V/m", "Pa"}

UNIT_ALIASES = {"ohm": "Ω", "Ohm": "Ω", "ohms": "Ω", "Ω": "Ω", "sec": "s", "hz": "Hz"}


def _fmt_number(x: float, digits: int) -> str:
    if x == 0:
        return "0"
    s = f"{x:.{digits}g}"
    if "e" in s:
        mant, exp = s.split("e")
        exp_i = int(exp)
        return f"{mant}e{exp_i}"
    return s


def format_quantity(value, unit: str = "", digits: int = 4, prefix: bool | None = None) -> str:
    """Human-friendly representation of ``value`` expressed in ``unit``."""
    if value is None:
        return "None"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(v):
        return "nan"
    if math.isinf(v):
        return ("−∞" if v < 0 else "∞") + (f" {unit}" if unit else "")
    use_prefix = (unit in PREFIXABLE) if prefix is None else prefix
    if not use_prefix or v == 0:
        if v != 0 and (abs(v) >= 1e5 or abs(v) < 1e-3):
            mant, exp = f"{v:.{digits - 1}e}".split("e")
            mant = mant.rstrip("0").rstrip(".") if "." in mant else mant
            s = f"{mant}e{int(exp)}"
        else:
            s = _fmt_number(v, digits)
        return f"{s} {unit}".strip()
    exp3 = int(math.floor(math.log10(abs(v)) / 3.0)) * 3
    exp3 = max(-24, min(24, exp3))
    if unit == "m" and exp3 > 0:
        exp3 = 0          # never "km" for a discharge gap
    mant = v / 10.0 ** exp3
    if abs(float(_fmt_number(mant, digits))) >= 1000 and exp3 < 24 and not (unit == "m" and exp3 >= 0):
        exp3 += 3
        mant = v / 10.0 ** exp3
    pre = _PREFIX_BY_EXP.get(exp3, "")
    return f"{_fmt_number(mant, digits)} {pre}{unit}".strip()


_NUM_RE = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$")


class QuantityError(ValueError):
    pass


def parse_quantity(text, unit: str = "", allow_inf: bool = True) -> float:
    """Parse ``text`` as a number in ``unit`` (prefixes and unit suffix optional)."""
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace("−", "-").replace(",", "").replace("×10^", "e").replace("x10^", "e")
    if not s:
        raise QuantityError("empty value")
    low = s.lower()
    if low in ("inf", "+inf", "infinity", "∞", "np.inf", "float('inf')"):
        if not allow_inf:
            raise QuantityError("infinity is not allowed here")
        return math.inf
    if low in ("-inf", "-infinity", "-∞", "-np.inf"):
        if not allow_inf:
            raise QuantityError("infinity is not allowed here")
        return -math.inf
    m = _NUM_RE.match(s)
    if not m:
        raise QuantityError(f"'{text}' is not a number")
    num = float(m.group(1))
    rest = m.group(2).strip()
    if not rest:
        return num
    for a, b in UNIT_ALIASES.items():
        if rest.endswith(a):
            rest = rest[: -len(a)] + b
            break
    u = unit or ""
    if u and rest == u:
        return num
    if u and rest.endswith(u):
        pre = rest[: -len(u)].strip()
    elif u == "s" and rest.endswith("sec"):
        pre = rest[:-3].strip()
    else:
        pre = rest
    if pre in _PREFIX_VALUE:
        if pre == "c" and u != "m":
            raise QuantityError(f"unknown prefix in '{text}'")
        return num * _PREFIX_VALUE[pre]
    raise QuantityError(f"could not understand the unit in '{text}' (expected {u or 'a plain number'})")


def si_scale_for(values, unit: str) -> tuple[float, str]:
    """Pick a display scale (divide by it) and a label for an array of values."""
    import numpy as np
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0 or unit not in PREFIXABLE:
        return 1.0, unit
    peak = float(np.max(np.abs(arr)))
    if peak == 0:
        return 1.0, unit
    exp3 = int(math.floor(math.log10(peak) / 3.0)) * 3
    exp3 = max(-18, min(18, exp3))
    scale = 10.0 ** exp3
    return scale, f"{_PREFIX_BY_EXP.get(exp3, '')}{unit}"


def human_bytes(n: float) -> str:
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024.0
    return f"{n:.1f} TB"


def human_duration(sec: float) -> str:
    if sec is None or not math.isfinite(sec):
        return "–"
    sec = max(0.0, float(sec))
    if sec < 1:
        return f"{sec * 1000:.0f} ms"
    if sec < 60:
        return f"{sec:.0f} s"
    if sec < 3600:
        m, s = divmod(int(round(sec)), 60)
        return f"{m} min {s:02d} s"
    h, rem = divmod(int(round(sec)), 3600)
    m = rem // 60
    if h < 48:
        return f"{h} h {m:02d} min"
    return f"{h / 24:.1f} days"

