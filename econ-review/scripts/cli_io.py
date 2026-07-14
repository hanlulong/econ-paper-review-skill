"""Portable console configuration for econ-review command-line tools."""

from __future__ import annotations

import sys
from typing import TextIO


def _configure_stream(stream: TextIO | None) -> None:
    """Use UTF-8 when the active stream supports in-place reconfiguration.

    Windows consoles and redirected PowerShell streams may otherwise inherit a
    legacy code page such as CP1252.  ``backslashreplace`` keeps diagnostics
    printable even when a host replaces the stream with an unusual wrapper.
    Test captures and third-party streams that do not expose ``reconfigure``
    are deliberately left untouched.
    """

    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, OSError, ValueError):
        # Closed, detached, or immutable wrappers cannot be changed safely.
        return


def configure_utf8_stdio() -> None:
    """Configure stdout and stderr for Unicode-safe CLI diagnostics."""

    _configure_stream(sys.stdout)
    _configure_stream(sys.stderr)
