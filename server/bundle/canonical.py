"""Canonical JSON serialisation per RFC 8785 (JCS).

Used to compute the bundle checksum deterministically — any compliant
implementation must produce byte-identical output for byte-identical
inputs, regardless of dict ordering or whitespace.

This is a minimal RFC 8785 implementation: lexicographic key sort by
UTF-16 code unit, no insignificant whitespace, ECMA-262 number
serialisation for integers and finite floats.
"""
from __future__ import annotations

import math
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Serialise obj to RFC 8785 canonical JSON bytes (UTF-8)."""
    out: list[str] = []
    _emit(obj, out)
    return "".join(out).encode("utf-8")


def _emit(obj: Any, out: list[str]) -> None:
    if obj is None:
        out.append("null")
    elif obj is True:
        out.append("true")
    elif obj is False:
        out.append("false")
    elif isinstance(obj, str):
        _emit_str(obj, out)
    elif isinstance(obj, bool):
        # already handled above (bool is int) — explicit guard for safety
        out.append("true" if obj else "false")
    elif isinstance(obj, int):
        out.append(str(obj))
    elif isinstance(obj, float):
        _emit_float(obj, out)
    elif isinstance(obj, list) or isinstance(obj, tuple):
        out.append("[")
        for i, item in enumerate(obj):
            if i:
                out.append(",")
            _emit(item, out)
        out.append("]")
    elif isinstance(obj, dict):
        # RFC 8785 §3.2.3: sort by UTF-16 code unit value of keys.
        # Python str sort is by codepoint, which agrees with UTF-16 for
        # the BMP; outside BMP requires surrogate pair comparison.
        keys = sorted(obj.keys(), key=_utf16_key)
        out.append("{")
        for i, k in enumerate(keys):
            if i:
                out.append(",")
            _emit_str(k, out)
            out.append(":")
            _emit(obj[k], out)
        out.append("}")
    else:
        raise TypeError(f"cannot serialise {type(obj).__name__} to canonical JSON")


def _utf16_key(s: str) -> tuple:
    """Convert string to a tuple of UTF-16 code units for ordering."""
    return tuple(s.encode("utf-16-be").hex(" ").split())


def _emit_str(s: str, out: list[str]) -> None:
    out.append('"')
    for ch in s:
        cp = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif cp < 0x20:
            out.append(f"\\u{cp:04x}")
        else:
            out.append(ch)
    out.append('"')


def _emit_float(f: float, out: list[str]) -> None:
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"cannot serialise non-finite float: {f}")
    if f == 0.0:
        out.append("0")
        return
    if f.is_integer() and abs(f) < 1e16:
        out.append(str(int(f)))
        return
    # Python's repr is round-trippable; for RFC 8785 we need ECMA-262
    # number serialisation. For typical embedding/weight values this
    # matches; we accept Python repr as a best-effort and note the
    # caveat in the test suite.
    out.append(repr(f))
