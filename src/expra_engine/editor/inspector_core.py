"""Toolkit-independent inspector logic behind the Qt inspector panel.

Owns schema signatures, value coercion, edit handlers, focus-aware refresh and
deferred re-render. Frontends provide the widget construction (sections,
forms, controls) and these small hooks: ``_focused_widget``, ``_schedule_idle``,
``_cancel_idle``, ``_set_header_text``, ``_clear_content`` and ``_show_error``.
Field "variables" only need ``get()``/``set()``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from expra_engine.core.component import Component, TransformComponent, registered_component_types
from expra_engine.core.component_schema import (
    ComponentTypeSpec,
    PropertyDescriptor,
    registered_component_specs,
)
from expra_engine.core.entity import Entity
from expra_engine.core.world import World
from expra_engine.runtime.script_component import ScriptComponent


class InspectorCore:
    def _init_inspector_state(
        self,
        *,
        on_transform_change: Callable[[str, str, float], None] | None,
        on_rename: Callable[[str, str], None] | None,
        on_toggle_enabled: Callable[[str, bool], None] | None,
        on_script_value_change: Callable[[str, int, str, Any], None] | None,
        on_add_component: Callable[[str], None] | None,
        on_component_change: Callable[[str, str, str, Any], None] | None,
        on_remove_component: Callable[[str, str], None] | None,
        on_world_level_placement: Callable[[str, tuple[float, float]], None] | None,
        on_world_set_initial_level: Callable[[str], None] | None,
        on_world_remove_item: Callable[[str], None] | None,
        on_normal_map_preview: Callable[[str, int], None] | None,
        on_normal_map_auto_map: Callable[[], None] | None,
    ) -> None:
        self._on_transform_change = on_transform_change
        self._on_rename = on_rename
        self._on_toggle_enabled = on_toggle_enabled
        self._on_script_value_change = on_script_value_change
        self._on_add_component = on_add_component
        self._on_component_change = on_component_change
        self._on_remove_component = on_remove_component
        self._on_world_level_placement = on_world_level_placement
        self._on_world_set_initial_level = on_world_set_initial_level
        self._on_world_remove_item = on_world_remove_item
        self._on_normal_map_preview = on_normal_map_preview
        self._on_normal_map_auto_map = on_normal_map_auto_map
        self._current_entity_id: str | None = None
        self._current_entity: Entity | None = None
        self._structure_key: tuple[Any, ...] | None = None
        self._has_pending_entity = False
        self._pending_entity: Entity | None = None
        self._pending_render_after_id: Any = None
        self._focus_widgets: set[Any] = set()
        self._name_value = ""
        self._name_var: Any = None
        self._name_entry: Any = None
        self._enabled_var: Any = None
        self._enabled_check: Any = None
        self._transform_vars: dict[str, Any] = {}
        self._transform_values: dict[str, float] = {}
        self._component_vars: dict[tuple[int, str], Any] = {}
        self._component_widgets: dict[tuple[int, str], Any] = {}
        self._script_vars: dict[tuple[int, str], Any] = {}
        self._script_widgets: dict[tuple[int, str], Any] = {}
        self._invalid_value: Any = None
        self._world_render_key: tuple[World, str | None] | None = None
        self._world_origin_x_var: Any = None
        self._world_origin_y_var: Any = None
        self._world_selected_level_id: str | None = None

    # -- frontend hooks -------------------------------------------------

    def _focused_widget(self) -> Any | None:
        raise NotImplementedError

    def _schedule_idle(self, callback: Callable[[], None]) -> Any:
        raise NotImplementedError

    def _cancel_idle(self, handle: Any) -> None:
        raise NotImplementedError

    def _set_header_text(self, text: str) -> None:
        raise NotImplementedError

    def _clear_content(self) -> None:
        raise NotImplementedError

    def _show_error(self, title: str, message: str) -> None:
        raise NotImplementedError

    def _empty_state(self) -> None:
        raise NotImplementedError

    def _entity_section(self, entity: Entity) -> None:
        raise NotImplementedError

    def _add_component_section(self, entity: Entity) -> None:
        raise NotImplementedError

    def _component_section(self, index: int, component: Component) -> None:
        raise NotImplementedError

    def _script_section(self, index: int, component: ScriptComponent) -> None:
        raise NotImplementedError

    # -- shared logic -------------------------------------------

    @staticmethod
    def _world_inspection_values(
        world: World, selection: str | None
    ) -> tuple[tuple[str, str], ...]:
        if selection and selection.startswith("level:"):
            level_id = selection.removeprefix("level:")
            descriptor = next(
                (item for item in world.levels if item.instance_id == level_id), None
            )
            if descriptor is None:
                return (("Level", "missing reference"),)
            return (
                ("Instance ID", descriptor.instance_id),
                ("Resource", descriptor.resource_path),
                ("Origin", repr(descriptor.origin)),
                ("Bounds", repr(descriptor.bounds) if descriptor.bounds is not None else "not set"),
                ("Initial", "yes" if descriptor.instance_id == world.initial_level_id else "no"),
                ("Always loaded", str(descriptor.always_loaded).lower()),
                ("Priority", str(descriptor.priority)),
            )
        if selection and selection.startswith("connection:"):
            connection_id = selection.removeprefix("connection:")
            connection = next(
                (item for item in world.connections if item.connection_id == connection_id), None
            )
            if connection is None:
                return (("Connection", "missing reference"),)
            return (
                ("Connection ID", connection.connection_id),
                (
                    "Route",
                    f"{connection.source_level_id}.{connection.source_anchor_id} → "
                    f"{connection.destination_level_id}.{connection.destination_anchor_id}",
                ),
                ("Transition", connection.transition.value),
                ("Bidirectional", str(connection.bidirectional).lower()),
                ("Preload distance", str(connection.preload_distance)),
                ("Unload distance", str(connection.unload_distance)),
            )
        return (
            ("World ID", world.world_id),
            ("Levels", str(len(world.levels))),
            ("Connections", str(len(world.connections))),
            ("Initial Level", world.initial_level_id or "not set"),
            ("Initial entrance", world.initial_entrance_id or "not set"),
            ("Primary anchor", world.primary_anchor_id or "not set"),
            ("Concurrent loads", str(world.streaming.max_concurrent_loads)),
            ("Resident Level budget", str(world.streaming.max_loaded_levels)),
        )

    def _apply_world_placement(self) -> None:
        if (
            self._on_world_level_placement is None
            or self._world_selected_level_id is None
            or self._world_origin_x_var is None
            or self._world_origin_y_var is None
        ):
            return
        try:
            origin = (float(self._world_origin_x_var.get()), float(self._world_origin_y_var.get()))
            self._on_world_level_placement(self._world_selected_level_id, origin)
        except (TypeError, ValueError) as error:
            self._show_error("World Placement", str(error))

    def render(self, entity: Entity | None) -> None:
        """Reuse controls when the selected entity has the same schema."""
        self._world_render_key = None
        self._set_header_text("INSPECTOR")
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
        self._clear_content()
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

    def _schedule_pending_render(self) -> None:
        if not self._has_pending_entity or self._pending_render_after_id is not None:
            return
        self._pending_render_after_id = self._schedule_idle(self._apply_pending_render)

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
            self._cancel_idle(identifier)

    def _emit_add_component(self, component_name: str) -> None:
        if self._on_add_component is not None:
            self._on_add_component(component_name)

    def _transform_handler(self, field_name: str) -> Callable[[Any], None]:
        def handle(_event: Any = None) -> None:
            self._handle_transform(field_name)

        return handle

    @staticmethod
    def convert_component_value(descriptor: PropertyDescriptor, value: Any, original: Any) -> Any:
        return descriptor.convert(value, original=original)

    @staticmethod
    def format_component_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (tuple, list)):
            return ", ".join(str(part) for part in value)
        return str(value)

    def _emit_normal_map_preview(self, component_index: int) -> None:
        if self._current_entity_id is not None and self._on_normal_map_preview is not None:
            self._on_normal_map_preview(self._current_entity_id, component_index)

    def _emit_normal_map_auto_map(self) -> None:
        if self._on_normal_map_auto_map is not None:
            self._on_normal_map_auto_map()

    def _component_handler(
        self,
        index: int,
        component_name: str,
        field_name: str,
        variable: Any,
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
