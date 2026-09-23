# Third-Party Notices

## PursuedPyBear (ppb)

Portions of expra-engine are adapted from the PursuedPyBear game framework.

**License:** Artistic License 2.0
**Copyright:** PursuedPyBear contributors
**Repository:** https://github.com/ppb/pursuedpybear (see supplied canon at `/home/btn17/Downloads/pursuedpybear-canon`)

The following Expra subsystems were architecturally adapted (not verbatim copied) from PursuedPyBear source files. In each case, PPB-specific concerns (SDL, ppb_vector, Renderer coupling) were removed and the mechanism was recast in Expra's architecture:

| Expra file | PPB source | Nature |
|---|---|---|
| `src/expra_engine/core/utils.py` | `src/ppb/utils.py` | Adapted — camel_to_snake and get_time only; LoggingMixin and module-index removed |
| `src/expra_engine/core/errors.py` | `src/ppb/errors.py` | Adapted — BadEventHandlerException message style; PPB-specific context removed |
| `src/expra_engine/runtime/event_queue.py` | `src/ppb/engine.py` (GameEngine signal/publish) | Adapted — extracted as standalone class; no EngineChildren, no WeakSet targets, no event_extensions |
| `src/expra_engine/runtime/events.py` | `src/ppb/events.py` | Adapted — event names/semantics preserved; all PPB-specific fields (scene, Vector, MouseButton, KeyCode) removed |
| `src/expra_engine/runtime/clock.py` | `src/ppb/systems/clocks.py` (Updater) | Adapted — fixed-timestep accumulator logic preserved; System base class removed; start/stop lifecycle changed |
| `src/expra_engine/core/camera.py` | `src/ppb/camera.py` | Adapted — coordinate math and visibility semantics preserved; ppb_vector replaced with plain float tuples; Renderer coupling removed |
| `src/expra_engine/core/scene.py` (hierarchy/walk methods) | `src/ppb/gomlib.py` (walk function, Children) | Concept adapted — walk() BFS traversal pattern; translated to Expra's Entity/parent_id model rather than importing GameObject |

**Artistic License 2.0 compliance:** The adapted code constitutes a "Modified Version" as defined by the Artistic License 2.0. The above attribution satisfies the requirement to include notices in the Modified Version. The original copyright notice is preserved here. No "Standard Version" files are distributed; only the Modified Version is included in expra-engine.

## Godot Engine conceptual adaptation

The renderer-neutral screen-texture contracts in
`src/expra_engine/runtime/screen_texture.py` preserve selected concepts from
Godot's `BackBufferCopy` and screen-texture renderer design. This is a
conceptual architectural adaptation, not a copy of Godot source code. Expra
does not ship Godot code, Godot binaries, shaders, or GPU device code.

**License:** MIT License
**Copyright:** Copyright (c) 2014-present Godot Engine contributors; Copyright
(c) 2007-2014 Juan Linietsky, Ariel Manzur
**Repository and license:** https://github.com/godotengine/godot/blob/master/LICENSE.txt

## Kenney Top-down Shooter assets

`examples/blacksite_relay/assets/kenney/` contains four PNG assets from
Kenney's Top-down Shooter asset pack: `floor_panel.png`,
`player_survivor_gun.png`, `survivor_blue.png`, and `zombie.png`.

**License:** Creative Commons CC0 1.0 Public Domain Dedication
**Source:** https://kenney.nl/assets/top-down-shooter

These files are example-game content only; they are not part of the Expra
engine package and do not change the engine's source license.

## Pygame (optional runtime dependency)

The optional `runtime-pygame` extra depends on Pygame for the SDL display and
Pygame renderer adapter. Pygame is installed separately and is not bundled in
the Expra wheel.

**License:** GNU Lesser General Public License 2.1 or later, as distributed by
the Pygame project
**Repository:** https://github.com/pygame/pygame
