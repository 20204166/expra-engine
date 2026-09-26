"""Pure contracts for asynchronous editor asset browsing.

Filesystem enumeration is deliberately injected.  A caller can run
``scan_directory`` in ``AppCoordinator`` and deliver its result through
``TkDeliveryQueue`` without this module owning either lifecycle.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from expra_engine.filesystem import ResourceId


class AssetMode(Enum):
    """Whether a browser interaction opens an existing file or saves one."""

    OPEN = "open"
    SAVE = "save"


class SaveDecision(Enum):
    """Next action required by a save request."""

    SUBMIT = "submit"
    CONFIRM_OVERWRITE = "confirm-overwrite"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AssetEntry:
    """One normalized directory entry exposed to a renderer."""

    path: Path
    name: str
    is_folder: bool
    logical_id: ResourceId | None = None

    @property
    def display_path(self) -> Path:
        """Return the physical path used for display and browser operations."""

        return self.path

    @property
    def kind(self) -> str:
        """Return the canonical editor-facing document or asset kind."""
        if self.is_folder:
            return "Folder"
        suffix = self.path.suffix.casefold()
        name = self.path.name.casefold()
        parts = self.logical_id.path.split("/") if self.logical_id is not None else ()
        if name == "project.json" and self.logical_id is not None:
            return "Project"
        if suffix == ".py":
            return "Script"
        if suffix in {".wav", ".ogg", ".mp3", ".flac", ".m4a"}:
            return "Audio"
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
            return "Image"
        if suffix in {".json", ".pb"} and self.logical_id is not None:
            if name.endswith((".level.json", ".level.pb")) or (parts and parts[0] == "levels"):
                return "Level"
            if name.endswith((".scene.json", ".scene.pb")) or (
                parts and parts[0] in ("scenes", "scene")
            ):
                return "Scene"
        return "File"


@dataclass(frozen=True)
class AssetScanRequest:
    """Immutable input for one background directory scan."""

    directory: Path
    generation: int
    mode: AssetMode = AssetMode.OPEN
    filter_text: str = ""
    cancelled: bool = False
    resource_root: Path | None = None


@dataclass(frozen=True)
class AssetScanResult:
    """Immutable scan output suitable for generation-gated UI delivery."""

    directory: Path
    generation: int
    entries: tuple[AssetEntry, ...]
    error: str | None = None
    cancelled: bool = False


@dataclass
class AssetBrowserState:
    """Renderer-independent selection and navigation state."""

    current_directory: Path
    mode: AssetMode = AssetMode.OPEN
    selected: AssetEntry | None = field(default=None, init=False)

    @property
    def display_path(self) -> Path:
        """Return the selected path, or the current directory when unselected."""

        return self.selected.path if self.selected is not None else self.current_directory

    def select(self, entry: AssetEntry) -> None:
        self.selected = entry

    def navigate(self, entry: AssetEntry) -> None:
        if not entry.is_folder:
            raise ValueError("only folders can be navigated")
        self.current_directory = entry.path
        self.selected = None

    def can_submit(self, value: AssetEntry | str | None) -> bool:
        if self.mode is AssetMode.OPEN:
            return isinstance(value, AssetEntry) and not value.is_folder
        return isinstance(value, str) and bool(value.strip())


def normalize_entries(
    entries: Iterable[AssetEntry], *, filter_text: str = ""
) -> tuple[AssetEntry, ...]:
    """Filter and sort entries with folders first and case-insensitive names."""

    needle = filter_text.casefold().strip()
    visible = (
        entry
        for entry in entries
        if entry.is_folder or not needle or needle in entry.name.casefold()
    )
    return tuple(
        sorted(visible, key=lambda entry: (not entry.is_folder, entry.name.casefold(), entry.name))
    )


def scan_directory(
    request: AssetScanRequest,
    enumerate_directory: Callable[[Path], Iterable[Path]],
) -> AssetScanResult:
    """Enumerate and normalize one directory using an injected worker callable.

    The function performs no scheduling and does not touch Tk.  The injected
    callable is expected to run off the UI thread when used by the editor.
    """

    if request.cancelled:
        return AssetScanResult(request.directory, request.generation, (), cancelled=True)
    try:
        entries = (
            _entry_for_path(path, request.resource_root)
            for path in enumerate_directory(request.directory)
        )
        normalized = normalize_entries(entries, filter_text=request.filter_text)
    except FileNotFoundError:
        return AssetScanResult(request.directory, request.generation, (), error="folder-missing")
    except PermissionError:
        return AssetScanResult(request.directory, request.generation, (), error="folder-permission")
    except OSError:
        return AssetScanResult(request.directory, request.generation, (), error="folder-error")
    return AssetScanResult(request.directory, request.generation, normalized)


def _entry_for_path(path: Path, resource_root: Path | None) -> AssetEntry:
    logical_id = None
    if resource_root is not None:
        try:
            relative_path = path.relative_to(resource_root)
        except ValueError:
            relative_path = path.resolve().relative_to(resource_root.resolve())
        logical_id = ResourceId.from_project_path(relative_path)
    return AssetEntry(path, path.name, path.is_dir(), logical_id)


def accept_scan_result(result: AssetScanResult, *, current_generation: int) -> bool:
    """Return whether a result still belongs to the current browser request."""

    return not result.cancelled and result.generation == current_generation


def build_save_decision(
    path: Path,
    *,
    exists: bool,
    overwrite_confirmed: bool = False,
    cancelled: bool = False,
) -> SaveDecision:
    """Resolve save confirmation without performing filesystem writes."""

    del path  # The path remains part of the caller's save contract, not this decision.
    if cancelled:
        return SaveDecision.CANCELLED
    if exists and not overwrite_confirmed:
        return SaveDecision.CONFIRM_OVERWRITE
    return SaveDecision.SUBMIT
