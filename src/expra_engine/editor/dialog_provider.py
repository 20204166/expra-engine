"""Dialog provider protocol — keeps editor workflows independent of dialog presentation.

The editor's implementation is ``QtDialogProvider`` (``editor/qt/dialogs.py``); tests
substitute recording fakes so ``ProjectWorkflow`` and the action mixins run headless.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DialogProvider(Protocol):
    """Ask questions and show messages without exposing a GUI toolkit."""

    def ask_open_file(
        self,
        title: str,
        *,
        filetypes: Sequence[tuple[str, str]] = (),
        multiple: bool = False,
        initialdir: str = "",
        parent: Any = None,
    ) -> str | list[str]:
        """Return a path (or list of paths when ``multiple=True``) or empty string."""
        ...

    def ask_open_dir(self, title: str, *, initialdir: str = "", parent: Any = None) -> str:
        """Return the selected directory path, or empty string if cancelled."""
        ...

    def ask_save_file(
        self,
        title: str,
        *,
        filetypes: Sequence[tuple[str, str]] = (),
        defaultextension: str = "",
        initialfile: str = "",
        initialdir: str = "",
        parent: Any = None,
    ) -> str:
        """Return the selected save path, or empty string if cancelled."""
        ...

    def ask_string(
        self,
        title: str,
        prompt: str,
        *,
        initial_value: str = "",
        parent: Any = None,
    ) -> str | None:
        """Return user input, or None if cancelled."""
        ...

    def show_error(self, title: str, message: str, *, parent: Any = None) -> None: ...

    def show_warning(self, title: str, message: str, *, parent: Any = None) -> None: ...

    def show_info(self, title: str, message: str, *, parent: Any = None) -> None: ...

    def ask_yes_no(self, title: str, message: str, *, parent: Any = None) -> bool: ...

    def ask_yes_no_cancel(
        self, title: str, message: str, *, parent: Any = None
    ) -> bool | None:
        """Return True (yes), False (no), or None (cancel)."""
        ...
