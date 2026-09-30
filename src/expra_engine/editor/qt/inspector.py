"""Qt inspector.

Schema signatures, value coercion, edit handlers, focus-aware refresh and the
deferred re-render all live in the shared ``InspectorCore``. This module only
builds Qt widgets: text fields are ``QLineEdit`` plus a ``get``/``set`` adapter,
toggles are ``QCheckBox`` plus an adapter, the add-component menu is a
``QToolButton`` with a ``QMenu``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from expra_engine.core.component import Component, TransformComponent, registered_component_types
from expra_engine.core.entity import Entity
from expra_engine.core.world import World
from expra_engine.editor.inspector_core import InspectorCore
from expra_engine.editor.qt.field_vars import BooleanVar, StringVar
from expra_engine.runtime.material_component import MaterialComponent
from expra_engine.runtime.script_component import ScriptComponent
from expra_engine.ui.styles import COLORS


class _Entry(QLineEdit):
    """QLineEdit reporting focus loss (the commit-on-blur trigger for field edits)."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.on_focus_out: Callable[..., Any] | None = None

    def focusOutEvent(self, event: Any) -> None:
        super().focusOutEvent(event)
        if self.on_focus_out is not None:
            self.on_focus_out()


class _Check(QCheckBox):
    def __init__(self) -> None:
        super().__init__()
        self.on_focus_out: Callable[..., Any] | None = None

    def focusOutEvent(self, event: Any) -> None:
        super().focusOutEvent(event)
        if self.on_focus_out is not None:
            self.on_focus_out()


class InspectorPanel(InspectorCore, QWidget):
    """Edit the selected entity through presentation callbacks."""

    def __init__(
        self,
        parent: Any = None,
        *,
        colors: dict[str, str] | None = None,
        on_transform_change: Callable[[str, str, float], None] | None = None,
        on_rename: Callable[[str, str], None] | None = None,
        on_toggle_enabled: Callable[[str, bool], None] | None = None,
        on_script_value_change: Callable[[str, int, str, Any], None] | None = None,
        on_add_component: Callable[[str], None] | None = None,
        on_component_change: Callable[[str, str, str, Any], None] | None = None,
        on_remove_component: Callable[[str, str], None] | None = None,
        on_world_level_placement: Callable[[str, tuple[float, float]], None] | None = None,
        on_world_set_initial_level: Callable[[str], None] | None = None,
        on_world_remove_item: Callable[[str], None] | None = None,
        on_normal_map_preview: Callable[[str, int], None] | None = None,
        on_normal_map_auto_map: Callable[[], None] | None = None,
    ) -> None:
        QWidget.__init__(self, parent)
        self._colors = colors or COLORS
        self._init_inspector_state(
            on_transform_change=on_transform_change,
            on_rename=on_rename,
            on_toggle_enabled=on_toggle_enabled,
            on_script_value_change=on_script_value_change,
            on_add_component=on_add_component,
            on_component_change=on_component_change,
            on_remove_component=on_remove_component,
            on_world_level_placement=on_world_level_placement,
            on_world_set_initial_level=on_world_set_initial_level,
            on_world_remove_item=on_world_remove_item,
            on_normal_map_preview=on_normal_map_preview,
            on_normal_map_auto_map=on_normal_map_auto_map,
        )
        outer = QVBoxLayout(self)
        self._header_label = QLabel("INSPECTOR")
        outer.addWidget(self._header_label)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        outer.addWidget(self._scroll)
        self._new_content()

    # -- content container ---------------------------------------------

    def _new_content(self) -> None:
        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._content)

    def _clear_content(self) -> None:
        """Destroy the content's children but keep the container (and its scroll position)."""
        self._clear_layout(self._layout)

    def _clear_layout(self, layout: Any) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                self._clear_layout(child)
                child.deleteLater()

    # -- frontend hooks for InspectorCore -------------------------------

    def _focused_widget(self) -> Any | None:
        return QApplication.focusWidget()

    def _schedule_idle(self, callback: Callable[[], None]) -> Any:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.start(0)
        return timer

    def _cancel_idle(self, handle: Any) -> None:
        handle.stop()

    def _set_header_text(self, text: str) -> None:
        self._header_label.setText(text)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def _bind_focus_out(self, widget: Any, callback: Callable[..., Any]) -> None:
        def handle() -> None:
            try:
                callback()
            finally:
                self._schedule_pending_render()

        widget.on_focus_out = handle

    # -- widget construction (sections) -------------------

    def _empty_state(self) -> None:
        title = QLabel("No entity selected")
        body = QLabel("Select an entity in the hierarchy to inspect its components.")
        body.setWordWrap(True)
        self._layout.addWidget(title)
        self._layout.addWidget(body)

    def _section_header(self, title: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(title.upper()))
        row.addStretch(1)
        self._layout.addLayout(row)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        self._layout.addWidget(line)
        return row

    def _form(self) -> QGridLayout:
        form = QGridLayout()
        form.setColumnStretch(1, 1)
        self._layout.addLayout(form)
        return form

    def _label(self, form: QGridLayout, text: str, row: int) -> None:
        form.addWidget(QLabel(text), row, 0)

    def _entity_section(self, entity: Entity) -> None:
        self._section_header("Entity")
        form = self._form()
        self._label(form, "Name", 0)
        name_entry = _Entry(entity.name)
        form.addWidget(name_entry, 0, 1)
        name_entry.returnPressed.connect(self._handle_rename)
        self._bind_focus_out(name_entry, self._handle_rename)
        self._name_var = StringVar(name_entry)
        self._name_entry = name_entry
        self._focus_widgets.add(name_entry)
        self._name_value = entity.name

        self._label(form, "Enabled", 1)
        enabled_check = _Check()
        enabled_check.setChecked(entity.enabled)
        enabled_check.clicked.connect(lambda *_a: self._handle_toggle_enabled())
        form.addWidget(enabled_check, 1, 1)
        self._enabled_var = BooleanVar(enabled_check)
        self._enabled_check = enabled_check
        self._focus_widgets.add(enabled_check)
        enabled_check.on_focus_out = self._schedule_pending_render

    def _add_component_section(self, entity: Entity) -> None:
        self._section_header("Components")
        search = _Entry("")
        self._layout.addWidget(search)
        self._focus_widgets.add(search)
        self._bind_focus_out(search, lambda: None)
        menu_button = QToolButton()
        menu_button.setText("+ Add Component")
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_button)
        existing = {type(component) for component in entity.components}

        def rebuild(*_args: Any) -> None:
            query = search.text().strip().lower()
            menu.clear()
            for name, component_type in registered_component_types():
                if component_type in existing or query not in name.lower():
                    continue
                label = name.replace("_", " ").title()
                action = menu.addAction(label)
                action.triggered.connect(
                    lambda *_a, component_name=name: self._emit_add_component(component_name)
                )
            if menu.isEmpty():
                menu.addAction("No components available").setEnabled(False)

        search.textChanged.connect(rebuild)
        rebuild()
        menu_button.setMenu(menu)
        self._layout.addWidget(menu_button)

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
            entry = _Entry(f"{getattr(transform, field_name):g}")
            form.addWidget(entry, row, 1)
            handler = self._transform_handler(field_name)
            entry.returnPressed.connect(handler)
            entry.on_focus_out = handler
            self._transform_vars[field_name] = StringVar(entry)
            self._transform_values[field_name] = float(getattr(transform, field_name))

    def _component_section(self, index: int, component: Component) -> None:
        spec = self._component_spec(component)
        if spec is None:
            self._section_header(type(component).__name__.replace("Component", ""))
            return
        header = self._section_header(spec.name.replace("_", " "))
        if self._on_remove_component is not None:
            remove = QPushButton("Remove")
            remove.clicked.connect(lambda *_a, name=spec.name: self._emit_remove_component(name))
            header.addWidget(remove)
        form = self._form()
        for row, descriptor in enumerate(spec.fields):
            self._label(form, descriptor.label, row)
            original = getattr(component, descriptor.name)
            entry = _Entry(self.format_component_value(original))
            form.addWidget(entry, row, 1)
            if not descriptor.editable:
                entry.setEnabled(False)
            variable = StringVar(entry)
            key = (index, descriptor.name)
            self._component_vars[key] = variable
            self._component_widgets[key] = entry
            if descriptor.editable:
                self._focus_widgets.add(entry)
            handler = self._component_handler(index, spec.name, descriptor.name, variable)
            entry.returnPressed.connect(handler)
            self._bind_focus_out(entry, handler)
        if isinstance(component, MaterialComponent):
            controls = QHBoxLayout()
            preview = QPushButton("Preview Normal Map")
            preview.setEnabled(self._on_normal_map_preview is not None)
            preview.clicked.connect(lambda *_a: self._emit_normal_map_preview(index))
            auto_map = QPushButton("Auto-map this Level…")
            auto_map.setEnabled(self._on_normal_map_auto_map is not None)
            auto_map.clicked.connect(lambda *_a: self._emit_normal_map_auto_map())
            controls.addWidget(preview)
            controls.addWidget(auto_map)
            controls.addStretch(1)
            self._layout.addLayout(controls)

    def _script_section(self, index: int, component: ScriptComponent) -> None:
        self._section_header(f"Script — {component.behaviour_class}")
        form = self._form()
        for row, (field, value) in enumerate(component.exposed_values.items()):
            self._label(form, field.replace("_", " ").title(), row)
            key = (index, field)
            control: Any
            variable: Any
            if isinstance(value, bool):
                control = _Check()
                control.setChecked(value)
                variable = BooleanVar(control)
                bool_handler = self._script_bool_handler(index, field)
                control.clicked.connect(lambda *_a, h=bool_handler: h())
                control.on_focus_out = self._schedule_pending_render
            else:
                control = _Entry(str(value))
                variable = StringVar(control)
                handler = self._script_text_handler(index, field, variable)
                control.returnPressed.connect(lambda h=handler: h(None))
                self._bind_focus_out(control, lambda h=handler: h(None))
            form.addWidget(control, row, 1)
            self._focus_widgets.add(control)
            self._script_vars[key] = variable
            self._script_widgets[key] = control

    # -- World inspector (widget half; rows/values come from the core) ---

    def render_world(self, world: World, selection: str | None = None) -> None:
        """Inspect World metadata or one selected descriptor/connection read-only."""
        render_key = (world, selection)
        if render_key == self._world_render_key:
            return
        self._cancel_pending_render()
        self._clear_content()
        self._current_entity = None
        self._current_entity_id = None
        self._structure_key = ("world", selection)
        self._world_render_key = render_key
        self._set_header_text("WORLD INSPECTOR")
        self._world_origin_x_var = None
        self._world_origin_y_var = None
        self._world_selected_level_id = (
            selection.removeprefix("level:")
            if selection and selection.startswith("level:")
            else None
        )
        selected_descriptor = next(
            (item for item in world.levels if item.instance_id == self._world_selected_level_id),
            None,
        )
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        self._layout.addLayout(grid)
        values = self._world_inspection_values(world, selection)
        for row, (name, value) in enumerate(values):
            grid.addWidget(QLabel(name), row, 0)
            if name == "Origin" and selected_descriptor is not None:
                x_entry = QLineEdit(str(selected_descriptor.origin[0]))
                y_entry = QLineEdit(str(selected_descriptor.origin[1]))
                editable = self._on_world_level_placement is not None
                x_entry.setReadOnly(not editable)
                y_entry.setReadOnly(not editable)
                self._world_origin_x_var = StringVar(x_entry)
                self._world_origin_y_var = StringVar(y_entry)
                grid.addWidget(x_entry, row, 1)
                grid.addWidget(y_entry, row, 2)
            else:
                label = QLabel(value)
                label.setWordWrap(True)
                grid.addWidget(label, row, 1)
        row = len(values)
        if selected_descriptor is not None:
            apply_button = QPushButton("Apply Placement")
            apply_button.setEnabled(self._on_world_level_placement is not None)
            apply_button.clicked.connect(lambda *_a: self._apply_world_placement())
            grid.addWidget(apply_button, row, 0, 1, 3)
            row += 1
            if (
                selected_descriptor.instance_id != world.initial_level_id
                and self._on_world_set_initial_level is not None
            ):
                initial = QPushButton("Set Initial Level")
                initial.clicked.connect(
                    lambda *_a, instance_id=selected_descriptor.instance_id: (
                        self._on_world_set_initial_level(instance_id)  # type: ignore[misc]
                    )
                )
                grid.addWidget(initial, row, 0, 1, 3)
                row += 1
            if self._on_world_remove_item is not None:
                remove = QPushButton("Remove Level Reference")
                remove.clicked.connect(
                    lambda *_a, identifier=selection: self._on_world_remove_item(identifier)  # type: ignore[misc]
                )
                grid.addWidget(remove, row, 0, 1, 3)
        elif (
            selection is not None
            and selection.startswith("connection:")
            and self._on_world_remove_item is not None
        ):
            delete = QPushButton("Delete Connection")
            delete.clicked.connect(
                lambda *_a, identifier=selection: self._on_world_remove_item(identifier)  # type: ignore[misc]
            )
            grid.addWidget(delete, row, 0, 1, 3)


__all__ = ["InspectorPanel"]
