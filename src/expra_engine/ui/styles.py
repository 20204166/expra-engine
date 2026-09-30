"""Editor colour roles and accent themes, derived from the renderer-neutral design tokens.

Adapted from System Analyzer maintenance/ui/styles.py.
"""

from expra_engine.design.tokens import SEMANTIC_COLORS

COLOR_ROLES: dict[str, str] = {
    **SEMANTIC_COLORS,
    "ink_2": SEMANTIC_COLORS["ink_muted"],
    "ink_3": SEMANTIC_COLORS["ink_subtle"],
    "accent_ink": "#10171C",
    "focus": SEMANTIC_COLORS["accent"],
}

COLORS: dict[str, str] = {
    **COLOR_ROLES,
    "background": COLOR_ROLES["base"],
    "card": COLOR_ROLES["surface"],
    "text": COLOR_ROLES["ink"],
    "secondary": COLOR_ROLES["ink_2"],
    "accent": COLOR_ROLES["accent"],
    "border": COLOR_ROLES["line"],
    "success": COLOR_ROLES["success"],
    "warning": COLOR_ROLES["warning"],
    "danger": COLOR_ROLES["danger"],
    "danger_active": "#B84D59",
    "disabled": COLOR_ROLES["disabled"],
    "primary_disabled": "#365863",
    "primary_disabled_text": "#9CA8B5",
    "bar_trough": "#2A333D",
    "button_bg": "#29313B",
    "button_bg_active": "#33404C",
    "muted_text": COLOR_ROLES["ink_3"],
    "panel_bg": "#1C2229",
    "elevated": "#29313B",
    "viewport_bg": "#11161C",
    "grid_minor": "#202A33",
    "grid_major": "#30404B",
    "camera": "#A8B5FF",
    "camera_active": "#D7DCFF",
    "player": "#F2A65A",
    "player_active": "#FFD09A",
}

# Toolbar roles the editor's toolbars resolve to a style name.
STYLE_NEUTRAL_BUTTON = "Neutral.TButton"
STYLE_PLAY_BUTTON = "Play.TButton"
STYLE_STOP_BUTTON = "Stop.TButton"

DEFAULT_APPEARANCE = "cyan"

EDITOR_ENTITY_MARKERS: dict[str, str] = {
    "camera": "CAM",
    "camera_compact": "CAM",
    "player": "PLY",
    "player_compact": "PLY",
}


def editor_entity_kind(name: str) -> str | None:
    """Return an editor-only visual role for well-known scene entities."""
    normalized = name.strip().casefold()
    if normalized in {"camera marker", "camera gizmo"}:
        return "camera_compact"
    if normalized == "camera" or normalized.startswith("camera "):
        return "camera"
    if normalized in {"player marker", "player gizmo"}:
        return "player_compact"
    if normalized == "player" or normalized.startswith("player "):
        return "player"
    return None


def _default_cyan_theme() -> dict[str, str]:
    return {
        "accent": SEMANTIC_COLORS["accent"],
        "accent_active": SEMANTIC_COLORS["accent_active"],
        "primary_disabled": "#365863",
        "primary_disabled_text": "#9CA8B5",
    }


ACCENT_THEMES: dict[str, dict[str, str]] = {
    "cyan": _default_cyan_theme(),
    "indigo": {
        "accent": "#4F46E5",
        "accent_active": "#4338CA",
        "primary_disabled": "#A5B4FC",
        "primary_disabled_text": "#EEF2FF",
    },
    "emerald": {
        "accent": "#047857",
        "accent_active": "#065F46",
        "primary_disabled": "#A7F3D0",
        "primary_disabled_text": "#ECFDF5",
    },
    "rose": {
        "accent": "#E11D48",
        "accent_active": "#BE123C",
        "primary_disabled": "#FDA4AF",
        "primary_disabled_text": "#FFF1F2",
    },
}


def accent_theme_colors(
    theme: str,
    *,
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    tokens = ACCENT_THEMES.get(theme, ACCENT_THEMES[DEFAULT_APPEARANCE])
    colors = dict(COLORS if base is None else base)
    colors.update(tokens)
    colors["focus"] = colors["accent"]
    colors.setdefault("accent_ink", COLOR_ROLES["accent_ink"])
    return colors


_STYLE_BY_ROLE = {
    "neutral": STYLE_NEUTRAL_BUTTON,
    "play": STYLE_PLAY_BUTTON,
    "stop": STYLE_STOP_BUTTON,
}


def toolbar_style_for_role(style_role: str) -> str:
    """Resolve a semantic toolbar role to its style name."""
    try:
        return _STYLE_BY_ROLE[style_role]
    except KeyError as error:
        raise ValueError(f"Unknown toolbar style role: {style_role}") from error
