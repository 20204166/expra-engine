"""Renderer-neutral semantic design tokens.

These values describe intent, not widget configuration. Backend adapters may
translate them into Tk, OpenGL, SDL, or another renderer's primitives.
"""

SEMANTIC_COLORS: dict[str, str] = {
    "base": "#171B21",
    "surface": "#20262E",
    "panel": "#1C2229",
    "elevated": "#29313B",
    "viewport": "#11161C",
    "line": "#3A4652",
    "ink": "#EDF2F7",
    "ink_muted": "#9CA8B5",
    "ink_subtle": "#74808D",
    "accent": "#55C7D9",
    "accent_active": "#36AABA",
    "selection": "#2C6473",
    "success": "#63C98B",
    "warning": "#E8B85C",
    "danger": "#E06B75",
    "disabled": "#59636E",
}

SPACING_SCALE: dict[str, int] = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
}

TYPOGRAPHY_SCALE: dict[str, dict[str, int | str]] = {
    "body": {"size": 10, "weight": "regular"},
    "label": {"size": 9, "weight": "regular"},
    "section": {"size": 12, "weight": "bold"},
    "title": {"size": 18, "weight": "bold"},
    "mono": {"size": 10, "weight": "regular"},
}

CONTROL_METRICS: dict[str, int] = {
    "button_min_height": 28,
    "primary_button_min_height": 32,
    "border_width": 1,
    "focus_width": 2,
    "corner_radius": 0,
}

PANEL_HIERARCHY: dict[str, int] = {
    "shell": 0,
    "panel": 1,
    "surface": 2,
    "elevated": 3,
}

STATE_STYLES: dict[str, tuple[str, ...]] = {
    "default": (),
    "hover": ("interactive",),
    "selected": ("accent",),
    "focused": ("focus",),
    "disabled": ("muted", "non_interactive"),
}

RESPONSIVE_RULES: dict[str, int] = {
    "min_content_width": 320,
    "safe_area_gutter": 16,
    "density_scale_percent": 100,
}
