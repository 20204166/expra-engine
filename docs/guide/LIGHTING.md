# Lighting

Expra 2D lighting is renderer-neutral at the data level and implemented by the
Pygame backend.

## Components

- `Light2DComponent` (`light_2d`) — a point or spot light.
- `CanvasModulateComponent` (`canvas_modulate`) — a scene-wide ambient tint.
- `MaterialComponent` (`material`) — how a primitive/sprite responds to light.

## Canvas modulation

`CanvasModulateComponent.color` sets the ambient baseline for the whole scene.
At most one modulation applies per scene (the first enabled one in scene order
wins). Set a dark color for a night/dungeon baseline before adding lights.

## Lights

`Light2DComponent`:

| Field | Default | Range |
|---|---|---|
| `kind` | `"point"` | `point` / `spot` |
| `color` | `(1,1,1)` | RGB(A) |
| `energy` | `1.0` | [0, 8] |
| `radius` | `4.0` | > 0 |
| `falloff` | `2.0` | [0.1, 8] |
| `cone_angle` | `60.0` | (0, 360] (spot) |
| `height` | `1.0` | [0, 1024] (normal-map light height) |

Radius scales with the entity's world scale. The renderer extracts each light
as a `LightDescriptor`; light compositing is additive.

## Materials

`MaterialComponent` controls light response:

- `mode` `lit`/`unlit`/`toon`; `toon_steps` (2–8) quantizes for a toon look;
- `ambient_response`, `diffuse` (0–1), `emission` (0–1) + `emission_color`.

## Normal mapping

See `MaterialComponent.normal_map_mode`:

- `explicit` — use `normal_texture_id` directly (missing resource is an error).
- `auto_pair` — resolve `<stem>_normal.<same-extension>` next to the albedo
  texture automatically (missing pair falls back to flat lighting).
- `disabled` — flat.

`normal_strength` (0–4), `normal_y_convention` (`opengl`/`directx`),
`normal_encoding` (`rgb_xyz`/`rg_xy`). Normal mapping needs `numpy`; without it,
materials fall back to flat lighting with a diagnostic logged.

## Tutorial

1. Add a `CanvasModulateComponent` to a scene entity and set a dark ambient.
2. Add a visible lamp sprite (or primitive) so the light has a source.
3. Add a `Light2DComponent` to the lamp entity.
4. Tune `radius`, `energy`, `falloff`.
5. Verify in Play.

## Common mistake

Large floating RGB light blobs with no visible source. Always pair a light with
a lamp/sprite/primitive, and keep the ambient dark enough that light reads as
light.

## Limitations

- The Pygame renderer does **not** implement `blend_mode` (`add`/`multiply`).
- Light shapes are point/spot; no volumetric or shadow casting.
- Screen effects (BackBufferCopy/ScreenTexture) are not rendered in the editor
  preview.
