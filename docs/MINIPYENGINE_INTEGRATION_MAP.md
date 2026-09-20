# MiniPyEngine to Expra Integration Map

Audited read-only sources under `/home/btn17/Downloads/MiniPyEngine-main`:
`Engine/StartGame.py`, `Engine/objects/GameObjectBase.py`, `GameObjects.py`,
`Player.py`, `Level1.py`, `GMMKR.py`, the default map, and `README.md`.

Useful extraction:

- Keep gameplay code simple with `update(delta_time)` ergonomics.
- Keep a central scene/object owner rather than hidden per-object loops.
- Use deferred removal rather than mutating a live collection during dispatch.
- Keep map/script data separate from live objects.

No reusable script, component, inspector, registry, or hot-reload architecture
exists to copy. Expra rejects MiniPyEngine's live-list removal, hard-coded map
type dispatch, and direct pygame input/collision/render ownership. The dogfood
PlayerBehaviour keeps the simple `dt` style while calling Expra's existing
Transform, InputMap, EventQueue, and timing owners.
