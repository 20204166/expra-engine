# Troubleshooting

Practical "do not do this" guidance, with the likely symptom and the fix.

## Document / identity mistakes

- **Editing `.pb` directly** — the format is deterministic binary output. Edit
  in the editor; re-save. `.json` is a read-only import path.
- **Treating JSON and PB as two documents** — they are one document, two
  serializations. Never keep both and edit one.
- **Using entity `name` as identity** — names are non-unique display labels.
  Use `entity_id` (stable) or a `persistent_id`.
- **Duplicating `persistent_id`s** — the World rejects duplicates; make IDs
  unique per actor.

## World / streaming mistakes

- **Making the World a giant Level/Scene** — the World owns no entities; put
  entities in Levels and connect them.
- **Inferring connections from proximity** — travel is authored via
  `WorldConnection`s between named anchors. Proximity does nothing.
- **Loading every Level eagerly** — streaming loads on demand; don't fight it.
- **Using the camera as a streaming anchor** — residency anchors are
  `StreamingAnchorComponent`; the camera context is separate.
- **Persistent player with Level-owned helpers** — helpers/hitboxes on Level
  entities don't travel; put them under the persistent actor's subtree.
- **Expecting a rendered fade** — `TransitionMode.FADE` only computes alpha;
  the renderer must draw it.
- **Expecting `loading` to differ from `instant`** — it currently doesn't.

## Scripting mistakes

- **Importing editor/GUI modules into runtime scripts** — forbidden in exports
  (the scan rejects `expra_engine.editor`/`ui` and GUI toolkit imports).
- **Manually parsing `.pb`** — use the document model.
- **Using `TextComponent` as game state** — store state in components/behaviour
  or `WorldSessionStateComponent`, not in a label's text.
- **Global mutable state** — prefer the runtime owner (engine/scene/system).
- **Scanning files every frame** — use the resource service.
- **Forgetting to cancel timelines/tweens/sequences on destroy** — detach them
  or they leak work.

## Asset mistakes

- **Absolute machine paths in asset references** — use logical IDs
  (`assets://…`).
- **Runtime directory scanning / loading outside the resource system** — use
  `ResourceService`.

## Rendering / lighting mistakes

- **Floating RGB light blobs with no source** — pair lights with a visible lamp.
- **Expecting `add`/`multiply` blend** — not implemented.
- **Normal mapping with no `numpy`** — materials silently fall back to flat
  lighting; install `numpy` (or `[normal-mapping]` extra).
- **Screen effects invisible in editor** — they render at runtime only.

## Editor mistakes

- **Touching widgets from a worker thread** — deliver via `QtDeliveryQueue`.
- **Calling widget methods from a background task** — Qt widgets belong to the
  GUI thread; deliver work through the Qt queue.

## Play vs Run Project confusion

- **"My World entrypoint doesn't run in Play"** — Play runs the current
  document; Run Project follows `project.json`'s entrypoint.
