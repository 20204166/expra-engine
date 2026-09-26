"""Scrollable, sectioned inspector for the selected entity."""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from expra_engine.core.component import Component, TransformComponent, registered_component_types
from expra_engine.core.component_schema import (
    ComponentTypeSpec,
    PropertyDescriptor,
    registered_component_specs,
)
from expra_engine.core.entity import Entity
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.ui.layout import make_scrollable_frame
from expra_engine.ui.styles import (
    COLORS,
    FONTS,
    SPACING,
    STYLE_CHECKBUTTON,
    STYLE_ENTRY,
    STYLE_NEUTRAL_BUTTON,
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
        on_component_change: Callable[[str, str, str, Any], None] | None = None,
        on_remove_component: Callable[[str, str], None] | None = None,
    ) -> None:
        c = colors or COLORS
        super().__init__(parent, bg=c["panel_bg"])
        self._colors = c
        self._on_transform_change = on_transform_change
        self._on_rename = on_rename
        self._on_toggle_enabled = on_toggle_enabled
        self._on_script_value_change = on_script_value_change
        self._on_add_component = on_add_component
        self._on_component_change = on_component_change
        self._on_remove_component = on_remove_component
        self._current_entity_id: str | None = None
        self._current_entity: Entity | None = None
        self._structure_key: tuple[Any, ...] | None = None
        self._has_pending_entity = False
        self._pending_entity: Entity | None = None
        self._pending_render_after_id: str | None = None
        self._focus_widgets: set[Any] = set()
        self._name_value = ""
        self._name_var: tk.StringVar | None = None
        self._name_entry: ttk.Entry | None = None
        self._enabled_var: tk.BooleanVar | None = None
        self._enabled_check: ttk.Checkbutton | None = None
        self._transform_vars: dict[str, tk.StringVar] = {}
        self._transform_values: dict[str, float] = {}
        self._component_vars: dict[tuple[int, str], tk.StringVar] = {}
        self._component_widgets: dict[tuple[int, str], ttk.Entry] = {}
        self._script_vars: dict[tuple[int, str], tk.Variable] = {}
        self._script_widgets: dict[tuple[int, str], tk.Widget] = {}
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

    def render(self, entity: Entity | None) -> None:
        """Reuse controls when the selected entity has the same schema."""
        signature = self._schema_signature(entity)
        if self._has_focused_control() and (
            (entity.entity_id if entity is not None else None) != self._current_entity_id
            or signature != self._structure_key
        ):
            self._pending_entity = entity
            self._has_pending_entity = True
            return

        self._cancel_pending_render()
        if signature != self._structure_key:
            self._rebuild_structure(entity, signature)
        self._current_entity = entity
        self._current_entity_id = entity.entity_id if entity is not None else None
        self._refresh_values(entity)

    def _schema_signature(self, entity: Entity | None) -> tuple[Any, ...]:
        if entity is None:
            return ("empty",)
        # Register built-ins before resolving specs; custom component specs use
        # the same registry and therefore follow the same signature path.
        registered_component_types()
        components: list[tuple[Any, ...]] = []
        for index, component in enumerate(entity.components):
            if isinstance(component, ScriptComponent):
                script_fields = tuple(
                    (name, type(value)) for name, value in component.exposed_values.items()
                )
                components.append(("script", index, component.behaviour_class, script_fields))
                continue
            spec = self._component_spec(component)
            if spec is None:
                components.append(
                    (
                        "unknown",
                        index,
                        type(component),
                        getattr(component, "component_type", None),
                    )
                )
                continue
            component_fields: tuple[tuple[Any, ...], ...] = tuple(
                (
                    field.name,
                    field.label,
                    field.value_type,
                    field.editable,
                    tuple(repr(value) for value in field.enum_values),
                )
                for field in spec.fields
            )
            components.append(("component", index, spec.name, component_fields))
        return ("entity", tuple(components))

    @staticmethod
    def _component_spec(component: Component) -> ComponentTypeSpec | None:
        return next(
            (spec for spec in registered_component_specs() if isinstance(component, spec.cls)),
            None,
        )

    def _rebuild_structure(self, entity: Entity | None, signature: tuple[Any, ...]) -> None:
        for child in tuple(self._content.winfo_children()):
            child.destroy()
        self._transform_vars = {}
        self._transform_values = {}
        self._component_vars = {}
        self._component_widgets = {}
        self._script_vars = {}
        self._script_widgets = {}
        self._focus_widgets = set()
        self._name_var = None
        self._name_entry = None
        self._enabled_var = None
        self._enabled_check = None
        self._invalid_value = None
        self._current_entity = entity
        self._current_entity_id = entity.entity_id if entity is not None else None
        self._structure_key = signature
        if entity is None:
            self._empty_state()
            return

        self._entity_section(entity)
        self._add_component_section(entity)
        for index, component in enumerate(entity.components):
            if isinstance(component, ScriptComponent):
                self._script_section(index, component)
            else:
                self._component_section(index, component)

    def _refresh_values(self, entity: Entity | None) -> None:
        if entity is None:
            return
        self._refresh_string_value(self._name_var, self._name_entry, entity.name)
        if self._name_entry is None or self._focused_widget() is not self._name_entry:
            self._name_value = entity.name
        if self._enabled_var is not None and self._enabled_check is not None:
            self._refresh_boolean_value(self._enabled_var, self._enabled_check, entity.enabled)

        for field_name in self._transform_vars:
            transform = entity.get_component(TransformComponent)
            if transform is None:
                continue
            value = float(getattr(transform, field_name))
            self._transform_values[field_name] = value
            # The normal component-schema path currently renders Transform as
            # generic component fields; retain this adapter for compatibility.
            self._transform_vars[field_name].set(f"{value:g}")

        for index, component in enumerate(entity.components):
            if isinstance(component, ScriptComponent):
                for field_name, value in component.exposed_values.items():
                    key = (index, field_name)
                    variable = self._script_vars.get(key)
                    widget = self._script_widgets.get(key)
                    if variable is None or widget is None:
                        continue
                    if isinstance(value, bool):
                        self._refresh_boolean_value(variable, widget, value)
                    else:
                        self._refresh_string_value(variable, widget, str(value))
                continue
            spec = self._component_spec(component)
            if spec is None:
                continue
            for descriptor in spec.fields:
                key = (index, descriptor.name)
                variable = self._component_vars.get(key)
                widget = self._component_widgets.get(key)
                if variable is not None and widget is not None:
                    self._refresh_string_value(
                        variable,
                        widget,
                        self.format_component_value(getattr(component, descriptor.name)),
                    )

    def _focused_widget(self) -> Any | None:
        try:
            return self.focus_get()
        except tk.TclError:
            return None

    def _has_focused_control(self) -> bool:
        return self._focused_widget() in self._focus_widgets

    def _refresh_string_value(self, variable: Any, widget: Any, value: str) -> None:
        if variable is None or widget is None or variable.get() == value:
            return
        if self._focused_widget() is widget:
            return
        variable.set(value)

    def _refresh_boolean_value(self, variable: Any, widget: Any, value: bool) -> None:
        value = bool(value)
        if variable.get() == value or self._focused_widget() is widget:
            return
        variable.set(value)

    def _bind_focus_out(self, widget: Any, callback: Callable[[Any], Any]) -> None:
        def handle(event: Any) -> Any:
            try:
                return callback(event)
            finally:
                self._schedule_pending_render()

        widget.bind("<FocusOut>", handle)

    def _schedule_pending_render(self) -> None:
        if not self._has_pending_entity or self._pending_render_after_id is not None:
            return
        try:
            self._pending_render_after_id = self.after_idle(self._apply_pending_render)
        except tk.TclError:
            self._pending_render_after_id = None

    def _apply_pending_render(self) -> None:
        self._pending_render_after_id = None
        if not self._has_pending_entity or self._has_focused_control():
            return
        entity = self._pending_entity
        self._pending_entity = None
        self._has_pending_entity = False
        self.render(entity)

    def _cancel_pending_render(self) -> None:
        identifier = self._pending_render_after_id
        self._pending_render_after_id = None
        self._pending_entity = None
        self._has_pending_entity = False
        if identifier is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(identifier)

    def destroy(self) -> None:
        self._cancel_pending_render()
        super().destroy()

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
        self._bind_focus_out(name_entry, self._handle_rename)
        self._name_var = name_var
        self._name_entry = name_entry
        self._focus_widgets.add(name_entry)
        self._name_value = entity.name

        self._label(form, "Enabled", 1)
        enabled_var = tk.BooleanVar(value=entity.enabled)
        enabled_check = ttk.Checkbutton(
            form,
            variable=enabled_var,
            command=self._handle_toggle_enabled,
            style=STYLE_CHECKBUTTON,
        )
        enabled_check.grid(row=1, column=1, sticky="w", pady=3)
        self._enabled_var = enabled_var
        self._enabled_check = enabled_check
        self._focus_widgets.add(enabled_check)
        enabled_check.bind("<FocusOut>", lambda _event: self._schedule_pending_render(), add="+")

    def _add_component_section(self, entity: Entity) -> None:
        self._section_header("Components")
        search = ttk.Entry(self._content, style=STYLE_ENTRY)
        search.insert(0, "")
        search.pack(fill="x", pady=(0, 4))
        self._focus_widgets.add(search)
        self._bind_focus_out(search, lambda _event: None)
        menu_button = ttk.Menubutton(self._content, text="+ Add Component")
        menu = tk.Menu(menu_button, tearoff=0)
        existing = {type(component) for component in entity.components}

        def rebuild(_event: Any = None) -> None:
            query = search.get().strip().lower()
            menu.delete(0, "end")
            for name, component_type in registered_component_types():
                if component_type in existing or query not in name.lower():
                    continue
                label = name.replace("_", " ").title()

                def add_component(component_name: str = name) -> None:
                    self._emit_add_component(component_name)

                menu.add_command(
                    label=label,
                    command=add_component,
                )
            if menu.index("end") is None:
                menu.add_command(label="No components available", state="disabled")

        search.bind("<KeyRelease>", rebuild)
        rebuild()
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

    @staticmethod
    def convert_component_value(descriptor: PropertyDescriptor, value: Any, original: Any) -> Any:
        return descriptor.convert(value, original=original)

    @staticmethod
    def format_component_value(value: Any) -> str:
        if isinstance(value, (tuple, list)):
            return ", ".join(str(part) for part in value)
        return str(value)

    def _component_section(self, index: int, component: Component) -> None:
        spec = self._component_spec(component)
        if spec is None:
            self._section_header(type(component).__name__.replace("Component", ""))
            return
        header = self._section_header(spec.name.replace("_", " "))
        if self._on_remove_component is not None:

            def remove_current_component(name: str = spec.name) -> None:
                self._emit_remove_component(name)

            ttk.Button(
                header,
                text="Remove",
                style=STYLE_NEUTRAL_BUTTON,
                command=remove_current_component,
            ).pack(side="right")
        form = self._form()
        for row, descriptor in enumerate(spec.fields):
            self._label(form, descriptor.label, row)
            original = getattr(component, descriptor.name)
            variable = tk.StringVar(value=self.format_component_value(original))
            entry = ttk.Entry(form, textvariable=variable, style=STYLE_ENTRY)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            if not descriptor.editable:
                entry.configure(state="disabled")
            key = (index, descriptor.name)
            self._component_vars[key] = variable
            self._component_widgets[key] = entry
            if descriptor.editable:
                self._focus_widgets.add(entry)
            handler = self._component_handler(index, spec.name, descriptor.name, variable)
            entry.bind("<Return>", handler)
            self._bind_focus_out(entry, handler)

    def _component_handler(
        self,
        index: int,
        component_name: str,
        field_name: str,
        variable: tk.StringVar,
    ) -> Callable[[Any], None]:
        def handle(_event: Any = None) -> None:
            entity = self._current_entity
            if entity is None or index >= len(entity.components):
                return
            component = entity.components[index]
            spec = self._component_spec(component)
            if spec is None or spec.name != component_name:
                return
            descriptor = next((field for field in spec.fields if field.name == field_name), None)
            if descriptor is None or self._on_component_change is None:
                return
            original = getattr(component, field_name)
            converted = self.convert_component_value(descriptor, variable.get(), original)
            if converted != original:
                self._on_component_change(entity.entity_id, component_name, field_name, converted)

        return handle

    def _emit_remove_component(self, component_type: str) -> None:
        if self._current_entity_id is not None and self._on_remove_component is not None:
            self._on_remove_component(self._current_entity_id, component_type)

    def _script_section(self, index: int, component: ScriptComponent) -> None:
        self._section_header(f"Script — {component.behaviour_class}")
        form = self._form()
        for row, (field, value) in enumerate(component.exposed_values.items()):
            self._label(form, field.replace("_", " ").title(), row)
            key = (index, field)
            control: tk.Widget
            if isinstance(value, bool):
                variable: Any = tk.BooleanVar(value=value)
                control = ttk.Checkbutton(
                    form,
                    variable=variable,
                    command=self._script_bool_handler(index, field),
                    style=STYLE_CHECKBUTTON,
                )
                control.grid(row=row, column=1, sticky="w", pady=3)
                control.bind(
                    "<FocusOut>",
                    lambda _event: self._schedule_pending_render(),
                    add="+",
                )
                self._focus_widgets.add(control)
            else:
                variable = tk.StringVar(value=str(value))
                entry = ttk.Entry(form, textvariable=variable, style=STYLE_ENTRY)
                control = entry
                control.grid(row=row, column=1, sticky="ew", pady=3)
                handler = self._script_text_handler(index, field, variable)
                control.bind("<Return>", handler)
                self._bind_focus_out(control, handler)
                self._focus_widgets.add(control)
            self._script_vars[key] = variable
            self._script_widgets[key] = control

    def _script_bool_handler(self, index: int, field: str) -> Callable[[], None]:
        def handle() -> None:
            entity = self._current_entity
            if entity is None or index >= len(entity.components):
                return
            component = entity.components[index]
            if isinstance(component, ScriptComponent) and field in component.exposed_values:
                variable = self._script_vars.get((index, field))
                if variable is not None:
                    self._emit_script_value(entity.entity_id, index, field, bool(variable.get()))

        return handle

    def _script_text_handler(self, index: int, field: str, variable: Any) -> Callable[[Any], None]:
        def handle(_event: Any) -> None:
            entity = self._current_entity
            if entity is None or index >= len(entity.components):
                return
            component = entity.components[index]
            if not isinstance(component, ScriptComponent) or field not in component.exposed_values:
                return
            original = component.exposed_values[field]
            try:
                value: Any = (
                    type(original)(variable.get())
                    if not isinstance(original, str)
                    else variable.get()
                )
            except (TypeError, ValueError):
                return
            self._emit_script_value(entity.entity_id, index, field, value)

        return handle

    def _emit_script_value(self, entity_id: str, index: int, field: str, value: Any) -> None:
        if self._on_script_value_change is not None:
            self._on_script_value_change(entity_id, index, field, value)

    def _handle_rename(self, _event: Any = None) -> None:
        if self._current_entity_id is None or self._name_var is None or self._on_rename is None:
            return
        value = self._name_var.get().strip()
        if not value or value == self._name_value:
            return
        self._name_value = value
        self._on_rename(self._current_entity_id, value)

    def _handle_toggle_enabled(self) -> None:
        if (
            self._current_entity_id is not None
            and self._enabled_var is not None
            and self._on_toggle_enabled is not None
        ):
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
