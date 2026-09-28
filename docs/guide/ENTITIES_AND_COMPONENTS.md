# Entities and Components

## Entity

`Entity` (`core/entity.py`) is a named object with components, tags, a parent,
and attached behaviours.

| Attribute | Type | Default |
|---|---|---|
| `entity_id` | `str` | `str(uuid.uuid4())` (stable across serialization) |
| `name` | `str` | required (non-unique) |
| `enabled` | `bool` | `True` |
| `layer` | `int` | `0` |
| `parent_id` | `str \| None` | `None` (root) |
| `tags` | `frozenset[str]` | empty |
| `components` | tuple | empty |

Methods: `add_component`, `remove_component`, `get_component(cls)`,
`get_components(cls)`, `add_behaviour`, `remove_behaviour`, `get_behaviour`,
`add_tag`, `remove_tag`, `has_tag`, `to_dict`, `from_dict`.

`entity_id` is the stable identity (survives round-trips). `name` is a display
label and is **not** unique — never rely on it for identity.

## How components register

Components identify themselves by a string `component_type`. Registration is
lazy and populates two parallel registries:

- `_COMPONENT_REGISTRY` (serialization, used by `component_from_dict`);
- `_COMPONENT_SPECS` (editor schema, used by the Inspector).

`AreaComponent` → `ColliderComponent` is the only cross-component dependency.

## Complete component reference

| # | type_id | Class | Purpose |
|---|---|---|---|
| 1 | `transform` | `TransformComponent` | 2D position/rotation/scale |
| 2 | `primitive` | `PrimitiveComponent` | rectangle/circle primitive |
| 3 | `sprite` | `SpriteComponent` | textured sprite |
| 4 | `text` | `TextComponent` | text label |
| 5 | `material` | `MaterialComponent` | lighting + normal-map response |
| 6 | `animated_sprite` | `AnimatedSprite2DComponent` | frame animation |
| 7 | `canvas_modulate` | `CanvasModulateComponent` | global ambient tint |
| 8 | `light_2d` | `Light2DComponent` | point/spot light |
| 9 | `collider` | `ColliderComponent` | physics shape |
| 10 | `area` | `AreaComponent` | gravity/damping override (needs collider) |
| 11 | `audio_listener_2d` | `AudioListener2DComponent` | spatial audio listener |
| 12 | `audio_stream_player_2d` | `AudioStreamPlayer2DComponent` | spatial audio source |
| 13 | `back_buffer_copy` | `BackBufferCopyComponent` | screen capture |
| 14 | `screen_texture` | `ScreenTextureComponent` | draw a captured region |
| 15 | `scene_instance` | `SceneInstanceComponent` | reuse a Scene |
| 16 | `level_anchor` | `LevelAnchorComponent` | entrance/exit portal |
| 17 | `streaming_anchor` | `StreamingAnchorComponent` | residency anchor |
| 18 | `world_persistent_actor` | `WorldPersistentActorComponent` | survives travel |
| 19 | `world_session_state` | `WorldSessionStateComponent` | opt-in session values |
| — | `script` | `ScriptComponent` | attach a Behaviour (lazy) |

Fallbacks (not in the registry): `OpaqueComponent` (unknown type) and
`UnresolvedScriptComponent` (`"missing_script"`).

### TransformComponent — `transform`

`x=0.0`, `y=0.0`, `rotation=0.0` (degrees), `scale_x=1.0`, `scale_y=1.0`,
`enabled=True`. Consumed by render extraction, physics (world transforms),
interpolation, world materialization, and the editor.

### PrimitiveComponent — `primitive`

`kind="rectangle"`, `width=1.0`, `height=1.0`, `radius=None`,
`fill=Color(1,1,1)`, `outline=None`, `outline_width=0.0`, `layer=0`,
`visible=True`. Consumed by `render_extractor` → `PrimitiveDescriptor`.

### SpriteComponent — `sprite`

`asset=""`, `tint=Color(1,1,1)`, `width=1.0`, `height=1.0`, `region=None`
(atlas crop), `centered=True`, `offset=(0,0)`, `flip_h=False`, `flip_v=False`,
`layer=0`, `visible=True`. Consumed by `render_extractor` →
`MaterialDescriptor(texture_id=…)`.

### TextComponent — `text`

`text=""`, `font="default"`, `size=16.0`, `color=Color(1,1,1)`,
`max_width=None`, `align="left"` (`left|center|right`), `layer=0`,
`visible=True`. Consumed by `render_extractor` → `TextDescriptor`.

### MaterialComponent — `material`

`mode="lit"` (`lit|unlit|toon`), `ambient_response=1.0` [0,1],
`diffuse=1.0` [0,1], `emission=0.0` [0,1], `emission_color=(1,1,1,1)`,
`toon_steps=3` [2,8], `normal_map_mode="disabled"`
(`disabled|explicit|auto_pair`), `normal_texture_id=""`, `normal_strength=1.0`
[0,4], `normal_y_convention="opengl"` (`opengl|directx`),
`normal_encoding="rgb_xyz"` (`rgb_xyz|rg_xy`). Provides `response` and
`normal_map_descriptor` computed properties. See [Lighting](LIGHTING.md).

### AnimatedSprite2DComponent — `animated_sprite`

`frames` (`SpriteFrames2D`), `animation="default"`, `autoplay=""`, `frame=0`,
`frame_progress=0.0`, `speed_scale=1.0`, `centered=True`, `offset=(0,0)`,
`flip_h/v=False`, `layer=0`, `visible=True`. Driven by `AnimatedSpriteSystem`.
See [Entities note](#animation) below.

### CanvasModulateComponent — `canvas_modulate`

`color=(1,1,1,1)`. At most one modulation applies per scene (first enabled one
in scene order wins). Consumed by `resolve_canvas_modulation`.

### Light2DComponent — `light_2d`

`kind="point"` (`point|spot`), `color=(1,1,1)`, `energy=1.0` [0,8],
`radius=4.0` (>0), `falloff=2.0` [0.1,8], `cone_angle=60.0` (0,360],
`height=1.0` [0,1024] (normal-map light height), `visible=True`. Radius scales
with the entity's world scale. See [Lighting](LIGHTING.md).

### ColliderComponent — `collider`

`shape="rectangle"` (`rectangle|circle`), `width=1.0`, `height=1.0`,
`radius=None`, `offset=(0,0)`, `solid=True`, `trigger=False`, `layer=1`,
`mask=0xFFFFFFFF`. See [Physics](PHYSICS.md).

### AreaComponent — `area`

`priority=0`, `gravity_mode="disabled"` (SpaceOverride),
`gravity=0.0`, `gravity_direction=(0,-1)`, `gravity_point=False`,
`gravity_point_center=(0,0)`, `gravity_point_unit_distance=0.0`,
`linear_damp_mode="disabled"`, `linear_damp=0.0`,
`angular_damp_mode="disabled"`, `angular_damp=0.0`. Requires a collider.

### AudioListener2DComponent — `audio_listener_2d`

`current=False`. The first enabled `current=True` listener in scene order wins.

### AudioStreamPlayer2DComponent — `audio_stream_player_2d`

`asset_id=None`, `volume_db=0.0`, `pitch_scale=1.0`, `autoplay=False`,
`stream_paused=False`, `max_distance=2000.0`, `attenuation=1.0`,
`max_polyphony=1`, `panning_strength=1.0`, `bus="sfx"`,
`area_mask=0`, `playback_type="default"`. See [Audio](AUDIO.md).

### BackBufferCopyComponent — `back_buffer_copy`

`copy_mode="rect"` (`disabled|rect|viewport`), `rect=(-100,-100,200,200)`,
`capture_id="screen"`, `layer=0`, `phase="opaque"`. Runtime only — not shown in
the editor preview.

### ScreenTextureComponent — `screen_texture`

`capture_id="screen"`, `uv_rect=(0,0,1,1)`, `width=1.0`, `height=1.0`,
`filter="linear"` (`nearest|linear|nearest_mipmap|linear_mipmap`), `lod=0.0`,
`tint=(1,1,1,1)`, `opacity=1.0`, `layer=0`, `phase="transparent"`,
`visible=True`. Runtime only in the editor preview.

### SceneInstanceComponent — `scene_instance`

See [Scene Instances](SCENE_INSTANCES.md).

### LevelAnchorComponent — `level_anchor`

`anchor_id` (required), `kind="both"` (`entrance|exit|both`),
`shape="rectangle"` (`rectangle|circle`), `size=(1,1)`. See [Worlds](WORLDS.md).

### StreamingAnchorComponent — `streaming_anchor`

`anchor_id` (required, default `"primary"`). See
[World Streaming](WORLD_STREAMING.md).

### WorldPersistentActorComponent — `world_persistent_actor`

`persistent_id` (required). See [World Streaming](WORLD_STREAMING.md).

### WorldSessionStateComponent — `world_session_state`

`values={}` (JSON-serializable). See [World Streaming](WORLD_STREAMING.md).

### ScriptComponent — `script`

`script_id` (ResourceId), `behaviour_class` (valid identifier), `exposed_values`
(dict), `order=0`, `enabled=True`, plus `_extra` for forward-compat. See
[Behaviours and Scripting](BEHAVIOURS_AND_SCRIPTING.md).

## Animation data (not components)

`SpriteFrames2D` / `SpriteAnimation2D` / `SpriteFrame2D` are data types owned by
the animated-sprite component. Loop modes: `NONE`, `LINEAR`, `PINGPONG`.
