"""Compatibility shim: re-exports from the ``tui`` package."""

from __future__ import annotations

from .tui.menu import run_tui

__all__ = ["run_tui"]