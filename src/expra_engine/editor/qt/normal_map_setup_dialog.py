"""Qt Normal Map Setup dialog -- table, filters and controls over the shared core."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from expra_engine.editor.normal_map_generation import (
    NormalMapGenerationPreset,
    NormalMapGenerationSettings,
)
from expra_engine.editor.normal_mapping_workflow import (
    NormalMapAssetCandidate,
    NormalMapClassification,
    NormalMapSetupPlan,
)
from expra_engine.ui.normal_map_setup_dialog import (
    NormalMapSetupDialogCore,
    candidate_action,
)

_NEEDS_ACTION = frozenset(
    {
        NormalMapClassification.READY_EXISTING,
        NormalMapClassification.CAN_GENERATE,
        NormalMapClassification.MISSING_MANUAL,
    }
)

_STATUS_LABELS = {
    NormalMapClassification.READY_EXISTING: "Ready",
    NormalMapClassification.CAN_GENERATE: "Can generate",
    NormalMapClassification.MISSING_MANUAL: "Unresolved",
    NormalMapClassification.ALREADY_CONFIGURED: "Configured",
    NormalMapClassification.PRESERVED: "Preserved",
    NormalMapClassification.INVALID: "Invalid",
}


class NormalMapSetupDialog(NormalMapSetupDialogCore, QDialog):
    """Review, generate, pair and apply normal maps for an open Scene or Level."""

    def __init__(
        self,
        parent: Any,
        window: Any,
        plan: NormalMapSetupPlan,
        project: Any,
        resources: Any,
    ) -> None:
        QDialog.__init__(self, parent)
        self.setWindowTitle("Normal Map Setup")
        self.resize(760, 520)
        self._selected: set[str] = set()
        self._init_setup_state(window, plan, project, resources)
        self._build_ui()
        self._populate_rows()

    # -- frontend hooks --------------------------------------------------

    def _selected_base_ids(self) -> frozenset[str]:
        return frozenset(self._selected)

    def _generation_settings(self) -> NormalMapGenerationSettings:
        return NormalMapGenerationSettings(
            preset=self._preset_combo.currentData(),
            strength=self._strength_spin.value(),
            y_convention=self._convention_combo.currentData(),
            bevel_width=self._smoothness_spin.value(),
            target_size=self._size_combo.currentData(),
        )

    def _refresh_rows(self) -> None:
        self._populate_rows()

    def _show_preview(self, preview: Any, metadata: str) -> None:
        from expra_engine.editor.qt.normal_map_preview import show_normal_map_preview

        show_normal_map_preview(self, preview, metadata)

    def _destroy_dialog(self) -> None:
        QDialog.close(self)
        self.deleteLater()

    def _refresh_assets(self) -> None:
        assets = getattr(self._window, "_assets", None)
        refresh = getattr(assets, "refresh", None)
        if callable(refresh):
            refresh()

    def _show_error(self, message: str) -> None:
        dialogs = getattr(self._window, "_dialogs", None)
        if dialogs is not None:
            dialogs.show_error("Normal Map Setup", message)

    # -- UI --------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("Normal Map Setup — " + self._plan.scene.name))
        header.addStretch(1)
        self._summary_label = QLabel()
        header.addWidget(self._summary_label)
        layout.addLayout(header)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Filter:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItem("All", "all")
        self._filter_combo.addItem("Needs action", "needs_action")
        controls.addWidget(self._filter_combo)
        controls.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("source, normal or entity name")
        controls.addWidget(self._search_edit)
        layout.addLayout(controls)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["", "Source", "Used by", "Normal", "Status", "Action"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, stretch=3)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(120)
        layout.addWidget(self._details)

        generation = QHBoxLayout()
        generation.addWidget(QLabel("Preset:"))
        self._preset_combo = QComboBox()
        for preset in NormalMapGenerationPreset:
            self._preset_combo.addItem(preset.value.replace("_", " ").title(), preset.value)
        self._preset_combo.setCurrentIndex(1)  # Alpha Bevel
        generation.addWidget(self._preset_combo)
        generation.addWidget(QLabel("Strength:"))
        self._strength_spin = QDoubleSpinBox()
        self._strength_spin.setRange(0.0, 4.0)
        self._strength_spin.setSingleStep(0.25)
        self._strength_spin.setValue(1.0)
        generation.addWidget(self._strength_spin)
        generation.addWidget(QLabel("Smoothness:"))
        self._smoothness_spin = QSpinBox()
        self._smoothness_spin.setRange(0, 20)
        self._smoothness_spin.setValue(2)
        generation.addWidget(self._smoothness_spin)
        generation.addWidget(QLabel("Convention:"))
        self._convention_combo = QComboBox()
        self._convention_combo.addItem("OpenGL Y+", "opengl")
        self._convention_combo.addItem("DirectX Y-", "directx")
        generation.addWidget(self._convention_combo)
        generation.addWidget(QLabel("Size:"))
        self._size_combo = QComboBox()
        self._size_combo.addItem("Source", None)
        self._size_combo.addItem("128", (128, 128))
        self._size_combo.addItem("64", (64, 64))
        self._size_combo.addItem("32", (32, 32))
        generation.addWidget(self._size_combo)
        generation.addStretch(1)
        layout.addLayout(generation)

        buttons = QHBoxLayout()
        self._preview_btn = QPushButton("Preview Selected")
        self._import_btn = QPushButton("Import…")
        self._generate_btn = QPushButton("Generate Selected")
        self._apply_btn = QPushButton("Apply Changes")
        close = QPushButton("Cancel")
        buttons.addWidget(self._preview_btn)
        buttons.addWidget(self._import_btn)
        buttons.addStretch(1)
        buttons.addWidget(close)
        buttons.addWidget(self._generate_btn)
        buttons.addWidget(self._apply_btn)
        layout.addLayout(buttons)

        self._filter_combo.currentIndexChanged.connect(lambda *_a: self._populate_rows())
        self._search_edit.textChanged.connect(lambda *_a: self._populate_rows())
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.itemSelectionChanged.connect(self._update_details)
        self._preview_btn.clicked.connect(lambda *_a: self._safe(self.preview_selected))
        self._import_btn.clicked.connect(lambda *_a: self._import_selected())
        self._generate_btn.clicked.connect(lambda *_a: self._safe(self.generate_selected))
        self._apply_btn.clicked.connect(lambda *_a: self._safe(self.apply_changes))
        close.clicked.connect(lambda *_a: self._destroy_dialog())
        self._update_summary()

    def _safe(self, action: Any) -> None:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self._show_error(str(exc))

    def _import_selected(self) -> None:
        selected = sorted(self._selected_base_ids())
        if not selected:
            return
        try:
            self.import_existing(selected[0])
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self._show_error(str(exc))

    def _visible_candidates(self) -> list[NormalMapAssetCandidate]:
        plan = self._plan
        search = self._search_edit.text().strip().casefold()
        mode = self._filter_combo.currentData()
        result: list[NormalMapAssetCandidate] = []
        for candidate in plan.candidates:
            if mode == "needs_action" and candidate.classification not in _NEEDS_ACTION:
                continue
            if search:
                haystack = " ".join(
                    [
                        candidate.base_texture_id,
                        candidate.existing_normal_id or "",
                        *[usage.entity_name for usage in candidate.usages],
                    ]
                ).casefold()
                if search not in haystack:
                    continue
            result.append(candidate)
        return result

    def _populate_rows(self) -> None:
        self._table.blockSignals(True)
        try:
            candidates = self._visible_candidates()
            self._table.setRowCount(len(candidates))
            for row, candidate in enumerate(candidates):
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                check.setCheckState(
                    Qt.CheckState.Checked
                    if candidate.base_texture_id in self._selected
                    else Qt.CheckState.Unchecked
                )
                self._table.setItem(row, 0, check)
                self._table.setItem(row, 1, self._cell(candidate.base_texture_id.rsplit("/", 1)[-1]))
                self._table.setItem(row, 2, self._cell(str(candidate.used_by)))
                normal = candidate.existing_normal_id or "—"
                self._table.setItem(row, 3, self._cell(normal.rsplit("/", 1)[-1]))
                self._table.setItem(row, 4, self._cell(_STATUS_LABELS.get(candidate.classification, str(candidate.classification))))
                self._table.setItem(row, 5, self._cell(candidate_action(candidate)))
        finally:
            self._table.blockSignals(False)
        self._update_summary()
        self._update_details()

    def _cell(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return item

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        candidate = self._candidate_at_row(item.row())
        if candidate is None:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._selected.add(candidate.base_texture_id)
        else:
            self._selected.discard(candidate.base_texture_id)

    def _candidate_at_row(self, row: int) -> NormalMapAssetCandidate | None:
        source_item = self._table.item(row, 0)
        if source_item is None:
            return None
        candidates = self._visible_candidates()
        if not 0 <= row < len(candidates):
            return None
        return candidates[row]

    def _update_summary(self) -> None:
        plan = self._plan
        self._summary_label.setText(
            f"{plan.ready_count} ready   {plan.generatable_count} can generate   "
            f"{plan.unresolved_count} unresolved   {plan.not_applicable_count} not applicable"
        )

    def _update_details(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._details.setPlainText(self._instance_summary())
            return
        candidate = self._candidate_at_row(rows[0].row())
        if candidate is None:
            self._details.setPlainText("")
            return
        lines = [f"{candidate.base_texture_id} — used by {candidate.used_by} visual(s)"]
        for usage in candidate.usages:
            frame = f" frame {usage.frame_index}" if usage.frame_index is not None else ""
            region = f" region {usage.region}" if usage.region else ""
            lines.append(
                f"  {usage.entity_name}: {usage.visual_kind}"
                f"{' ' + usage.animation_name if usage.animation_name else ''}{frame}{region}"
            )
        if candidate.detail:
            lines.append(f"  ({candidate.detail})")
        self._details.setPlainText("\n".join(lines))

    def _instance_summary(self) -> str:
        if not self._plan.instance_sources:
            return ""
        lines = ["Scene-instance dependencies (edit them in their source scene):"]
        for source in self._plan.instance_sources:
            lines.append(f"  {source.root_name or source.root_id}: {source.source_path} ({source.visual_count} visuals)")
        return "\n".join(lines)


__all__ = ["NormalMapSetupDialog"]
