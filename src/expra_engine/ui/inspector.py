"""Scrollable, sectioned inspector for the selected entity."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from expra_engine.core.component import Component, TransformComponent, registered_component_types
from expra_engine.core.entity import Entity
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.ui.layout import make_scrollable_frame
from expra_engine.ui.styles import (
    COLORS,
    FONTS,
    SPACING,
    STYLE_CHECKBUTTON,
    STYLE_ENTRY,
)


class InspectorPanel(tk.Frame):
    """Edit the selected entity through presentation callbacks."""

    def __init__(
        self,
        parent: Any,
        *,
        colors: dict[str, str] | None = None,
        on_transform_change: Callable[[str, str, float], None] | None = None,
        on_rename: Callable[[str, str], None] | None = None,
        on_toggle_enabled: Callable[[str, bool], None] | None = None,
        on_script_value_change: Callable[[str, int, str, Any], None] | None = None,
        on_add_component: Callable[[str], None] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])
        self._colors = c
        self._on_transform_change = on_transform_change
        self._on_rename = on_rename
        self._on_toggle_enabled = on_toggle_enabled
        self._on_script_value_change = on_script_value_change
        self._on_add_component = on_add_component
        self._current_entity_id: str | None = None
        self._name_value = ""
        self._transform_vars: dict[str, tk.StringVar] = {}
        self._transform_values: dict[str, float] = {}
        self._invalid_value: tk.Label | None = None

        header = tk.Frame(self, bg=c["panel_bg"])
        header.pack(fill="x", padx=SPACING["card_pad_x"], pady=(SPACING["card_pad_y"], 6))
        tk.Label(
            header,
            text="INSPECTOR",
            font=FONTS["panel_header"],
            bg=c["panel_bg"],
            fg=c["ink"],
        ).pack(side="left")

        body = tk.Frame(self, bg=c["panel_bg"])
        body.pack(fill="both", expand=True, padx=SPACING["card_pad_x"], pady=(0, 4))
        self._scroll_canvas, self._content = make_scrollable_frame(
            body,
            frame_cls=tk.Frame,
            canvas_cls=tk.Canvas,
            scrollbar_cls=ttk.Scrollbar,
        )
        self._scroll_canvas.configure(bg=c["panel_bg"], highlightthickness=0)
        self._content.configure(bg=c["panel_bg"])
        self._bind_mousewheel(self._scroll_canvas)
        self._bind_mousewheel(self._content)

    def _bind_mousewheel(self, widget: Any) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_mousewheel, add="+")

    def _on_mousewheel(self, event: Any) -> str:
        delta = -1 if getattr(event, "num", None) == 5 else 1
        if getattr(event, "delta", 0):
            delta = -1 if event.delta > 0 else 1
        self._scroll_canvas.yview_scroll(delta, "units")
        return "break"

    def render(self, entity: Entity | None) -> None:
        """Render one entity or a useful no-selection state."""
        for child in tuple(self._content.winfo_children()):
            child.destroy()
        self._transform_vars = {}
        self._transform_values = {}
        self._invalid_value = None
        self._current_entity_id = entity.entity_id if entity is not None else None
        if entity is None:
            self._empty_state()
            return

        self._entity_section(entity)
        self._add_component_section(entity)
        for index, component in enumerate(entity.components):
            if isinstance(component, TransformComponent):
                self._transform_section(component)
            elif isinstance(component, ScriptComponent):
                self._script_section(entity, index, component)
            else:
                self._component_section(component)

    def _empty_state(self) -> None:
        c = self._colors
        tk.Label(
            self._content,
            text="No entity selected",
            font=FONTS["section"],
            bg=c["panel_bg"],
            fg=c["ink"],
        ).pack(anchor="w", padx=4, pady=(18, 4))
        tk.Label(
            self._content,
            text="Select an entity in the hierarchy to inspect its components.",
            font=FONTS["body"],
            bg=c["panel_bg"],
            fg=c["ink_2"],
            justify="left",
            wraplength=220,
        ).pack(anchor="w", padx=4)

    def _section_header(self, title: str) -> tk.Frame:
        c = self._colors
        frame = tk.Frame(self._content, bg=c["panel_bg"])
        frame.pack(fill="x", pady=(12, 6))
        ttk.Separator(frame, orient="horizontal").pack(side="bottom", fill="x")
        tk.Label(
            frame,
            text=title.upper(),
            font=FONTS["section"],
            bg=c["panel_bg"],
            fg=c["ink"],
        ).pack(anchor="w", pady=(0, 5))
        return frame

    def _form(self) -> tk.Frame:
        form = tk.Frame(self._content, bg=self._colors["panel_bg"])
        form.pack(fill="x")
        form.grid_columnconfigure(1, weight=1)
        return form

    def _label(self, parent: Any, text: str, row: int) -> None:
        tk.Label(
            parent,
            text=text,
            anchor="w",
            font=FONTS["detail_row"],
            bg=self._colors["panel_bg"],
            fg=self._colors["ink_2"],
        ).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)

    def _entity_section(self, entity: Entity) -> None:
        self._section_header("Entity")
        form = self._form()
        self._label(form, "Name", 0)
        name_var = tk.StringVar(value=entity.name)
        name_entry = ttk.Entry(form, textvariable=name_var, style=STYLE_ENTRY)
        name_entry.grid(row=0, column=1, sticky="ew", pady=3)
        name_entry.bind("<Return>", self._handle_rename)
        name_entry.bind("<FocusOut>", self._handle_rename)
        self._name_var = name_var
        self._name_value = entity.name

        self._label(form, "Enabled", 1)
        enabled_var = tk.BooleanVar(value=entity.enabled)
        ttk.Checkbutton(
            form,
            variable=enabled_var,
            command=self._handle_toggle_enabled,
            style=STYLE_CHECKBUTTON,
        ).grid(row=1, column=1, sticky="w", pady=3)
        self._enabled_var = enabled_var

    def _add_component_section(self, entity: Entity) -> None:
        self._section_header("Components")
        menu_button = ttk.Menubutton(self._content, text="+ Add Component")
        menu = tk.Menu(menu_button, tearoff=0)
        existing = {type(component) for component in entity.components}
        for name, component_type in registered_component_types():
            if component_type in existing:
                continue
            label = name.replace("_", " ").title()
            menu.add_command(
                label=label,
                command=lambda component_name=name: self._emit_add_component(component_name),
            )
        if menu.index("end") is None:
            menu.add_command(label="No components available", state="disabled")
        menu_button["menu"] = menu
        menu_button.pack(anchor="w", pady=(0, 4))

    def _emit_add_component(self, component_name: str) -> None:
        if self._on_add_component is not None:
            self._on_add_component(component_name)

    def _transform_section(self, transform: TransformComponent) -> None:
        self._section_header("Transform")
        form = self._form()
        fields = (
            ("x", "Position X"),
            ("y", "Position Y"),
            ("rotation", "Rotation"),
            ("scale_x", "Scale X"),
            ("scale_y", "Scale Y"),
        )
        for row, (field_name, label) in enumerate(fields):
            self._label(form, label, row)
            variable = tk.StringVar(value=f"{getattr(transform, field_name):g}")
            entry = ttk.Entry(form, textvariable=variable, style=STYLE_ENTRY)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            handler = self._transform_handler(field_name)
            entry.bind("<Return>", handler)
            entry.bind("<FocusOut>", handler)
            self._transform_vars[field_name] = variable
            self._transform_values[field_name] = float(getattr(transform, field_name))

    def _transform_handler(self, field_name: str) -> Callable[[Any], None]:
        def handle(_event: Any = None) -> None:
            self._handle_transform(field_name)

        return handle

    def _component_section(self, component: Component) -> None:
        self._section_header(type(component).__name__.replace("Component", ""))
        tk.Label(
            self._content,
            text="Component data is not editable in this inspector yet.",
            font=FONTS["body"],
            bg=self._colors["panel_bg"],
            fg=self._colors["ink_2"],
            wraplength=220,
            justify="left",
        ).pack(anchor="w", padx=4)

    def _script_section(self, entity: Entity, index: int, component: ScriptComponent) -> None:
        self._section_header(f"Script — {component.behaviour_class}")
        form = self._form()
        for row, (field, value) in enumerate(component.exposed_values.items()):
            self._label(form, field.replace("_", " ").title(), row)
            if isinstance(value, bool):
                variable: Any = tk.BooleanVar(value=value)
                ttk.Checkbutton(
                    form,
                    variable=variable,
                    command=self._script_bool_handler(entity.entity_id, index, field, variable),
                    style=STYLE_CHECKBUTTON,
                ).grid(row=row, column=1, sticky="w", pady=3)
            else:
                variable = tk.StringVar(value=str(value))
                entry = ttk.Entry(form, textvariable=variable, style=STYLE_ENTRY)
                entry.grid(row=row, column=1, sticky="ew", pady=3)
                entry.bind(
                    "<Return>",
                    self._script_text_handler(entity.entity_id, index, field, variable, value),
                )
                entry.bind(
                    "<FocusOut>",
                    self._script_text_handler(entity.entity_id, index, field, variable, value),
                )

    def _script_bool_handler(
        self, entity_id: str, index: int, field: str, variable: Any
    ) -> Callable[[], None]:
        def handle() -> None:
            self._emit_script_value(entity_id, index, field, variable.get())

        return handle

    def _script_text_handler(
        self, entity_id: str, index: int, field: str, variable: Any, old: Any
    ) -> Callable[[Any], None]:
        def handle(_event: Any) -> None:
            self._emit_script_text(entity_id, index, field, variable.get(), old)

        return handle

    def _emit_script_text(
        self, entity_id: str, index: int, field: str, text: str, old: Any
    ) -> None:
        try:
            value: Any = type(old)(text) if not isinstance(old, str) else text
        except (TypeError, ValueError):
            return
        self._emit_script_value(entity_id, index, field, value)

    def _emit_script_value(self, entity_id: str, index: int, field: str, value: Any) -> None:
        if self._on_script_value_change is not None:
            self._on_script_value_change(entity_id, index, field, value)

    def _handle_rename(self, _event: Any = None) -> None:
        if self._current_entity_id is None or self._on_rename is None:
            return
        value = self._name_var.get().strip()
        if not value or value == self._name_value:
            return
        self._name_value = value
        self._on_rename(self._current_entity_id, value)

    def _handle_toggle_enabled(self) -> None:
        if self._current_entity_id is not None and self._on_toggle_enabled is not None:
            self._on_toggle_enabled(self._current_entity_id, self._enabled_var.get())

    def _handle_transform(self, field_name: str) -> None:
        if self._current_entity_id is None or self._on_transform_change is None:
            return
        variable = self._transform_vars.get(field_name)
        if variable is None:
            return
        try:
            value = float(variable.get())
        except ValueError:
            return
        if value == self._transform_values.get(field_name):
            return
        self._transform_values[field_name] = value
        self._on_transform_change(self._current_entity_id, field_name, value)
