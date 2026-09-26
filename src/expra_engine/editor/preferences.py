"""Editor preferences — persisted user settings for the editor shell."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from expra_engine.editor.persistence import atomic_write_text, read_text_or_none

_LOG = logging.getLogger(__name__)
_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class EditorPreferences:
    theme: str = "darkly"
    recent_projects: tuple[str, ...] = ()
    autosave_interval_ms: int = 30_000
    window_geometry: str | None = None
    viewport_camera: dict[str, object] = field(default_factory=dict)
    schema_version: int = _SCHEMA_VERSION


_DEFAULTS = EditorPreferences()


def _prune_recent_projects(recent_projects: tuple[str, ...]) -> tuple[str, ...]:
    """Drop deleted recent-project paths, keeping existing-but-unreadable ones.

    A path that is missing (deleted) is removed from the recent list. A path
    that exists but cannot be stat'd (for example a permission error) is kept,
    so opening it still reports the real cause rather than silently hiding a
    genuine project failure.
    """
    retained: list[str] = []
    for project in recent_projects:
        if not isinstance(project, str) or not project:
            continue
        try:
            Path(project).stat()
        except (FileNotFoundError, NotADirectoryError, ValueError):
            continue
        except OSError:
            retained.append(project)
        else:
            retained.append(project)
    return tuple(dict.fromkeys(retained))[:10]


class PreferencesStore:
    """Load and save ``EditorPreferences`` with atomic writes and safe defaults."""

    def load(self, path: Path) -> EditorPreferences:
        """Return preferences from *path*, falling back to defaults on any error."""
        text = read_text_or_none(path)
        if text is None:
            return EditorPreferences()
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                return EditorPreferences()
            if data.get("schema_version") != _SCHEMA_VERSION:
                return EditorPreferences()
            return EditorPreferences(
                theme=str(data.get("theme", _DEFAULTS.theme)),
                recent_projects=_prune_recent_projects(tuple(data.get("recent_projects", ()))),
                autosave_interval_ms=int(
                    data.get("autosave_interval_ms", _DEFAULTS.autosave_interval_ms)
                ),
                window_geometry=(
                    str(data["window_geometry"])
                    if data.get("window_geometry") is not None
                    else None
                ),
                viewport_camera=(
                    dict(data["viewport_camera"])
                    if isinstance(data.get("viewport_camera"), dict)
                    else {}
                ),
                schema_version=_SCHEMA_VERSION,
            )
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            _LOG.warning("Could not parse preferences from %s: %s", path, error)
            return EditorPreferences()

    def save(self, path: Path, prefs: EditorPreferences) -> None:
        """Atomically write *prefs* to *path*."""
        data = asdict(prefs)
        data["recent_projects"] = list(data["recent_projects"])
        atomic_write_text(path, json.dumps(data, indent=2))
