"""Shared Tk-availability probe for headless test environments."""

from __future__ import annotations

import tkinter as tk


def display_available() -> bool:
    """Return True if a Tk root window can be created in this environment."""
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True
