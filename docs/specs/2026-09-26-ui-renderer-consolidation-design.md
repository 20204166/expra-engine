# UI Renderer Consolidation Design

**Goal:** Give retained editor trees one shared row-update mechanism and make
the renderer's visual-transform choice canonical across runtime and editor paths.

## Scope

This design covers two bounded refactors found in the UI responsibility audit:

1. Share structural `ttk.Treeview` reconciliation between the asset browser and
   scene hierarchy while retaining their different data collection, ordering,
   selection, and callbacks.
2. Expose the renderer's effective visual transform on `RenderItem` and reuse
   that decision for runtime drawing, visibility bounds, and editor viewport
   geometry.

It does not redesign either panel, change how assets or scenes are ordered,
change selection semantics, or introduce a new renderer.

## Ownership and Data Flow

`ui.tree_reconciliation` will own a small row record and a reconciliation
operation. Panels continue to build an ordered sequence of desired rows from
their domain data. The shared operation applies structural differences to the
existing Tk tree: remove stale subtree roots, insert missing rows, move rows
that changed parent or sibling position, and update only changed row content.
The asset panel retains its asset/path maps and sort keys; the hierarchy retains
scene preorder and entity-selection behavior. Both continue to own their
domain-specific selection and event callbacks.

`RenderItem.visual_transform` will be the canonical transform used to draw an
item: textured items use `sprite_transform`, and untextured items use
`world_transform`. This matches `PygameRenderer._draw_contract_item`, where a
texture ID determines whether sprite-local placement participates. Runtime
visibility bounds and the editor viewport will use the same property. Depth
ordering remains based on `world_transform`.

## Compatibility and Failure Behavior

Tree rows retain their existing IDs, text, values, tags, order, expanded state,
and selection. Reconciliation must preserve surviving descendants when deleting
an old ancestor removes their Tk rows; those descendants are reinserted at their
desired parents. Unchanged renders must continue to avoid Tk insert/delete/item/
move mutations. Tk failures retain their current propagation behavior.

The `RenderItem` property is additive. Existing `world_transform` and
`sprite_transform` properties remain available. No serialized scene or project
schema changes. Project-authored behavior loading, Tk thread delivery, and
resource resolution are outside this change.

## Testing

Tests will be written before production edits. Shared tree tests cover initial
insertion, stale subtree removal, surviving-child reparenting, changed row
content, sibling reordering, and a no-op reconciliation. Existing Tk panel tests
remain the integration contract for asset navigation, hierarchy structure,
selection, expansion, and avoiding redundant mutations.

Render tests cover textured and untextured items, including sprite offsets, and
verify that runtime drawing, visibility bounds, and viewport geometry use the
canonical transform. Existing Pygame renderer and editor rendering suites remain
required regression coverage.

## Verification

Run focused shared-tree, editor UI, runtime-rendering, Pygame-renderer, and
editor-texture tests; then run the configured editor and renderer profiles,
Ruff, formatting, Pyright, Mypy, compileall, and diff checks as available.
