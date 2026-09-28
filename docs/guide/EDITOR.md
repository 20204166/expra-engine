# Editor

The editor is a Tk application (`EditorWindow`) for authoring documents and
previewing gameplay. It is not the game runtime.

## Launch

```bash
expra-editor
python -m expra_engine
```

## Layout

```
┌──────────────────── EditorWindow ────────────────────────┐
│  Toolbar (play · run project · pause · stop · new · save)│
├──────────┬──────────────────────────┬────────────────────┤
│ Hierarchy│       Viewport           │    Inspector       │
├──────────┴──────────────────────────┴────────────────────┤
│  Asset Browser / Console / Status                        │
└──────────────────────────────────────────────────────────┘
```

Panels: `HierarchyPanel`, `ViewportPanel`, `InspectorPanel`, `ConsolePanel`,
`AssetBrowserPanel`. The middle panes are user-resizable (`ttkbootstrap.PanedWindow`).

## Document modes

The editor has three document kinds — Scene, Level, World — selected by the
active document (`ActiveDocument`). `ProjectWorkflow` owns open/create/save/duplicate:

- **Scene/Level** — hierarchy shows entities; you add entities and components.
- **World** — hierarchy shows Level descriptors and connections; the "Add"
  button becomes "Add Level"; entity editing is disabled. `WorldAuthoringWorkflow`
  provides add/remove/place level, set initial level, and create connections.

## Key workflows

- **New/Open/Close project** and **New/Open/Save Scene/Level/World** via File
  menu (all use the command stack for undo/redo).
- **Inspector** edits entity name/enabled, transform, and component fields from
  the component schema. `MaterialComponent` gets "Preview Normal Map" and
  "Auto-map this Level" buttons.
- **Add Component** — searchable dropdown over registered component types.
- **Asset Browser** — tree view of project files; drag sprites into the viewport
  to create entities; double-click to open Scene/Level/World documents.
- **Autosave** — optional recurring silent save.

## Viewport (edit mode)

The viewport renders a **pixel layer** through the same `PygameRenderer` as the
runtime (via `EditorPixelRenderer`), plus editor-only overlays: grid/axes,
selection outlines, collider outlines, camera frame, entity markers, light
gizmos. If pixel rendering fails, it falls back to Tk canvas geometry. Screen
effects (BackBufferCopy/ScreenTexture) are reported as unsupported and not drawn
in the preview.

## Play / Run Project

- **Play** runs in-process (see [Play vs Run Project](PLAY_AND_RUN_PROJECT.md)).
- **Run Project** spawns the project entrypoint as a child process.

## Threading

All Tk mutation happens on the main thread. Background work (asset scan, save,
export dialog) runs through `AppCoordinator` and delivers via
`TkDeliveryQueue`. See [THREADING.md](../THREADING.md).

## Preferences

Window geometry, recent projects, and camera state persist outside `project.json`
(`PreferencesStore`).
