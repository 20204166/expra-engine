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
