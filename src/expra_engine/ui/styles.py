"""Design tokens and ttk style registration for the editor UI.

Adapted from System Analyzer maintenance/ui/styles.py.

Removed SA-specific layout names (dashboard_description_wrap, etc.).
Design tokens (colours, fonts, spacing, control) preserved.
``configure_app_styles`` registers all ttk styles used by the editor.
"""

from typing import Any

from expra_engine.design.tokens import SEMANTIC_COLORS, SPACING_SCALE

Font = tuple[Any, ...]

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
    "accent_active": "#36AABA",
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
}

SPACING: dict[str, int] = {
    "page_x": SPACING_SCALE["lg"],
    "page_y": SPACING_SCALE["md"],
    "section_gap": SPACING_SCALE["md"],
    "row_gap": SPACING_SCALE["sm"],
    "control_gap": 10,
    "card_pad_x": SPACING_SCALE["md"],
    "card_pad_y": 10,
    "dialog_pad_x": 20,
    "dialog_pad_y": 18,
    "button_gap": 6,
    "panel_gap": SPACING_SCALE["xs"],
    "toolbar_pad_x": SPACING_SCALE["md"],
    "toolbar_pad_y": 6,
    "scrollbar_gutter": 6,
}

CONTROL: dict[str, int] = {
    "button_pad_x": 10,
    "button_pad_y": 6,
    "primary_button_pad_x": 14,
    "primary_button_pad_y": 8,
    "spinbox_pad": 4,
    "card_border_width": 1,
}

FONTS: dict[str, Font] = {
    "ui": ("Helvetica",),
    "title": ("Helvetica", 18, "bold"),
    "section": ("Helvetica", 12, "bold"),
    "body": ("Helvetica", 10),
    "button": ("Helvetica", 10, "bold"),
    "danger_button": ("Helvetica", 10, "bold"),
    "status": ("Helvetica", 9, "bold"),
    "mono": ("Courier", 10),
    "panel_header": ("Helvetica", 11, "bold"),
    "detail_row": ("Helvetica", 10),
    "toolbar_label": ("Helvetica", 9),
}

STYLE_APP_FRAME = "App.TFrame"
STYLE_PANEL_FRAME = "Panel.TFrame"
STYLE_TITLE = "Title.TLabel"
STYLE_SECTION = "Section.TLabel"
STYLE_DESCRIPTION = "Description.TLabel"
STYLE_PRIMARY_BUTTON = "Primary.TButton"
STYLE_NEUTRAL_BUTTON = "Neutral.TButton"
STYLE_DANGER_BUTTON = "Danger.TButton"
STYLE_STATUS_READY = "Ready.Status.TLabel"
STYLE_STATUS_BUSY = "Busy.Status.TLabel"
STYLE_PLAY_BUTTON = "Play.TButton"
STYLE_STOP_BUTTON = "Stop.TButton"
STYLE_ENTRY = "Editor.TEntry"
STYLE_TREEVIEW = "Editor.Treeview"
STYLE_CHECKBUTTON = "Editor.TCheckbutton"
STYLE_SEPARATOR = "Editor.TSeparator"

DEFAULT_APPEARANCE = "cyan"

ACCENT_THEMES: dict[str, dict[str, str]] = {
    "cyan": {
        "accent": "#55C7D9",
        "accent_active": "#36AABA",
        "primary_disabled": "#365863",
        "primary_disabled_text": "#9CA8B5",
    },
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


def configure_app_styles(
    style: Any,
    colors: dict[str, str] | None = None,
    fonts: dict[str, Font] | None = None,
) -> None:
    """Register every ttk style used by the editor."""

    c = COLORS if colors is None else colors
    f = FONTS if fonts is None else fonts

    style.configure(STYLE_APP_FRAME, background=c["background"])
    style.configure(STYLE_PANEL_FRAME, background=c["panel_bg"])
    style.configure(STYLE_TITLE, background=c["background"], foreground=c["text"], font=f["title"])
    style.configure(STYLE_SECTION, background=c["panel_bg"], foreground=c["text"], font=f["section"])
    style.configure(STYLE_DESCRIPTION, background=c["background"], foreground=c["secondary"], font=f["body"])
    style.configure(
        STYLE_PRIMARY_BUTTON,
        background=c["accent"],
        foreground=c["accent_ink"],
        font=f["button"],
        padding=(CONTROL["primary_button_pad_x"], CONTROL["primary_button_pad_y"]),
        borderwidth=0,
        focusthickness=2,
        focuscolor=c["accent"],
    )
    style.map(
        STYLE_PRIMARY_BUTTON,
        background=[("active", c["accent_active"]), ("disabled", c["primary_disabled"])],
        foreground=[("disabled", c["primary_disabled_text"])],
    )
    style.configure(
        STYLE_DANGER_BUTTON,
        background=c["danger"],
        foreground=c["accent_ink"],
        font=f["danger_button"],
        padding=(CONTROL["button_pad_x"], CONTROL["button_pad_y"]),
        borderwidth=0,
        focusthickness=2,
        focuscolor=c["danger"],
    )
    style.map(
        STYLE_DANGER_BUTTON,
        background=[("active", c["danger_active"]), ("disabled", c["disabled"])],
    )
    style.configure(
        STYLE_NEUTRAL_BUTTON,
        background=c["button_bg"],
        foreground=c["text"],
        font=f["danger_button"],
        padding=(CONTROL["button_pad_x"], CONTROL["button_pad_y"]),
        borderwidth=0,
        focusthickness=2,
        focuscolor=c["accent"],
    )
    style.map(
        STYLE_NEUTRAL_BUTTON,
        background=[("active", c["button_bg_active"]), ("disabled", c["disabled"])],
        foreground=[("disabled", c["muted_text"])],
    )
    style.configure(
        STYLE_STATUS_READY,
        background=c["background"],
        foreground=c["success"],
        font=f["status"],
    )
    style.configure(
        STYLE_STATUS_BUSY,
        background=c["background"],
        foreground=c["warning"],
        font=f["status"],
    )
    style.configure(
        STYLE_PLAY_BUTTON,
        background=c["success"],
        foreground=c["accent_ink"],
        font=f["button"],
        padding=(CONTROL["button_pad_x"], CONTROL["button_pad_y"]),
        borderwidth=0,
        focusthickness=2,
        focuscolor=c["success"],
    )
    style.configure(
        STYLE_STOP_BUTTON,
        background=c["danger"],
        foreground=c["accent_ink"],
        font=f["button"],
        padding=(CONTROL["button_pad_x"], CONTROL["button_pad_y"]),
        borderwidth=0,
        focusthickness=2,
        focuscolor=c["danger"],
    )
    style.map(
        STYLE_STOP_BUTTON,
        background=[("active", c["danger_active"]), ("disabled", c["disabled"])],
        foreground=[("disabled", c["ink_3"])],
    )
    style.configure(
        STYLE_ENTRY,
        fieldbackground=c["surface"],
        foreground=c["ink"],
        bordercolor=c["line"],
        lightcolor=c["line"],
        darkcolor=c["line"],
        insertcolor=c["accent"],
        padding=(6, 4),
    )
    style.map(
        STYLE_ENTRY,
        fieldbackground=[("disabled", c["panel_bg"])],
        foreground=[("disabled", c["ink_3"])],
        bordercolor=[("focus", c["accent"])],
    )
    style.configure(
        STYLE_TREEVIEW,
        background=c["surface"],
        fieldbackground=c["surface"],
        foreground=c["ink"],
        borderwidth=0,
        rowheight=26,
        font=f["body"],
    )
    style.map(
        STYLE_TREEVIEW,
        background=[("selected", c["selection"])],
        foreground=[("selected", c["ink"])],
    )
    style.configure(
        STYLE_CHECKBUTTON,
        background=c["panel_bg"],
        foreground=c["ink"],
        font=f["body"],
    )
    style.map(
        STYLE_CHECKBUTTON,
        background=[("active", c["panel_bg"])],
        foreground=[("disabled", c["ink_3"])],
    )
    style.configure(STYLE_SEPARATOR, background=c["line"])
