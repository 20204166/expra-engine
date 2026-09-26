#!/usr/bin/env python3
"""Static Expra inspection runner.

Executed as a SUBPROCESS under the CONFIGURED Expra interpreter -- never
imported by the expra-mcp server's own process (design point 6: the server
must never import expra_engine itself). This file has zero dependency on
``expra_dev_mcp`` or ``mcp`` so it stays runnable even if those aren't
installed in the Expra environment.

Contract: read one JSON request object from stdin, perform exactly one
read-only, non-project-code-executing operation, write exactly one JSON
response line to stdout.

    Request:  {"op": "expra_inspect" | "resource_trace" | "render_inspect"
                    | "render_snapshot", ...}
    Response: {"ok": true, "data": {...}} | {"ok": false, "kind": str, "error": str}

Every static operation here only parses JSON scene/project data and walks
the in-memory Scene/Entity/Component graph -- confirmed by direct source
reading that Project.load/Scene.from_dict/extract_render_frame never import
or execute a project's own Python (the "script" component type is pure
data: script_id/behaviour_class/exposed_values, never imported). That is
why every result below carries "executed_project_code": false.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

# Must be set before any `import pygame` (done lazily below, inside the ops
# that need it): pygame prints a community banner to stdout on import, which
# would corrupt this script's single-JSON-line stdout contract.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def _safe(value: Any) -> Any:
    """Best-effort JSON-safe conversion for engine objects whose exact
    shape wasn't independently verified against the source (e.g. some
    RenderOrder/rect fields) -- never crash the runner over a cosmetic
    field, fall back to repr().
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:  # noqa: BLE001 -- last-resort fallback below
            pass
    return repr(value)


def _color_to_list(color: Any) -> list[float] | None:
    if color is None:
        return None
    return [color.red, color.green, color.blue, color.alpha]


def _load_project(expra_root: str, project: str):
    from expra_engine.core.project import Project

    return Project.load(Path(expra_root) / project)


def _load_scene(project: Any, scene: str | None, *, observer: Any | None = None):
    return project.load_document(scene, observer=observer)


def _find_entity(scene: Any, entity: str):
    found = scene.find_entity(entity) or scene.find_entity_by_name(entity)
    if found is None:
        raise LookupError(f"entity not found (tried as id and as name): {entity!r}")
    return found


# ---------------------------------------------------------------------------
# expra_inspect
# ---------------------------------------------------------------------------


def _spec_to_dict(spec: Any) -> dict:
    return {
        "name": spec.name,
        "required_types": list(spec.required_types),
        "fields": [
            {
                "name": f.name,
                "label": f.label,
                "value_type": getattr(f.value_type, "__name__", str(f.value_type)),
                "default": _safe(f.default),
                "editable": f.editable,
                "enum_values": _safe(list(f.enum_values)),
                "minimum": f.minimum,
                "maximum": f.maximum,
                "tuple_length": f.tuple_length,
                "tuple_minimum": f.tuple_minimum,
                "tuple_integer": f.tuple_integer,
            }
            for f in spec.fields
        ],
    }


def op_expra_inspect(req: dict) -> dict:
    action = req["action"]
    expra_root = req["expra_root"]

    if action == "project":
        project = _load_project(expra_root, req["project"])
        return {
            "action": action,
            "executed_project_code": False,
            "project": {
                "name": project.name,
                "game_version": project.game_version,
                "schema_version": project.schema_version,
                "entry_point": project.entry_point,
                "start_scene": project.start_scene,
                "entrypoint": project.entrypoint,
                "script_entry_point": project.script_entry_point,
                "scene_paths": list(project.scene_paths()),
                "level_paths": list(project.level_paths()),
                "input_settings": dict(project.input_settings),
                "path": str(project.path),
            },
        }

    if action == "scene":
        project = _load_project(expra_root, req["project"])
        scene = _load_scene(project, req.get("scene"))
        return {
            "action": action,
            "executed_project_code": False,
            "scene": scene.to_dict(),
            "entity_count": len(scene.entities),
            "root_entity_names": [e.name for e in scene.roots()],
        }

    if action == "entity":
        project = _load_project(expra_root, req["project"])
        scene = _load_scene(project, req.get("scene"))
        entity = _find_entity(scene, req["entity"])
        x, y, rotation = scene.world_pose(entity.entity_id)
        return {
            "action": action,
            "executed_project_code": False,
            "entity": entity.to_dict(),
            "world_pose": {"x": x, "y": y, "rotation": rotation},
            "children": [c.name for c in scene.children_of(entity.entity_id)],
        }

    if action == "component":
        project = _load_project(expra_root, req["project"])
        scene = _load_scene(project, req.get("scene"))
        entity = _find_entity(scene, req["entity"])
        component_type = req["component_type"]
        matches = [c.to_dict() for c in entity.components if c.to_dict().get("type") == component_type]
        if not matches:
            raise LookupError(f"entity {entity.name!r} has no {component_type!r} component")
        return {
            "action": action,
            "executed_project_code": False,
            "component": matches[0],
            "match_count": len(matches),
        }

    if action == "component_schema":
        from expra_engine.core import component_schema as schema_mod

        component_type = req.get("component_type")
        if component_type:
            spec = schema_mod.component_type_spec(component_type)
            return {"action": action, "executed_project_code": False, "spec": _spec_to_dict(spec)}
        specs = schema_mod.registered_component_specs()
        return {
            "action": action,
            "executed_project_code": False,
            "registered_types": [s.name for s in specs],
        }

    if action == "input_map":
        project = _load_project(expra_root, req["project"])
        return {
            "action": action,
            "executed_project_code": False,
            "available_statically": True,
            "bindings": dict(project.input_settings),
            "note": (
                "static project-configured action->physical-input bindings; a live "
                "InputMap/ActionEvent stream requires runtime_probe or editor_session "
                "(Phase 2E/2F)"
            ),
        }

    if action == "camera":
        project = _load_project(expra_root, req["project"])
        scene = _load_scene(project, req.get("scene"))
        return {
            "action": action,
            "executed_project_code": False,
            "available_statically": True,
            "scene_camera": scene.camera.to_dict(),
            "note": (
                "static scene-owned camera config (SceneCamera); the live Camera2D "
                "(position/zoom/smoothing while actually playing) requires runtime_probe "
                "or editor_session (Phase 2E/2F)"
            ),
        }

    if action == "systems":
        return {
            "action": action,
            "executed_project_code": False,
            "available_statically": False,
            "note": (
                "systems are instantiated only when the engine actually runs -- there is "
                "no static registry (confirmed: runtime/system.py defines only the "
                "RuntimeSystem base class, no registry). Use "
                "source_search(repos=['expra'], query='RuntimeSystem') to find system "
                "implementations by source, or runtime_probe/editor_session (Phase 2E/2F) "
                "for live instances."
            ),
        }

    if action == "lifecycle":
        return {
            "action": action,
            "executed_project_code": False,
            "available_statically": False,
            "note": (
                "lifecycle state (play/pause/stop, scene transitions) is inherently a "
                "runtime concept. Use runtime_probe or editor_session (Phase 2E/2F)."
            ),
        }

    raise ValueError(f"unknown expra_inspect action: {action!r}")


# ---------------------------------------------------------------------------
# resource_trace
# ---------------------------------------------------------------------------


def op_resource_trace(req: dict) -> dict:
    from expra_engine.filesystem.errors import ResourceNotFoundError
    from expra_engine.filesystem.ids import ResourceId

    expra_root = req["expra_root"]
    project = _load_project(expra_root, req["project"])
    asset_id_str = req["asset_id"]

    try:
        resource_id = ResourceId.parse(asset_id_str)
    except Exception as exc:  # noqa: BLE001 -- surfaced as a structured invalid-id result
        return {
            "logical_id": asset_id_str,
            "exists": False,
            "decode_status": "not_attempted",
            "decode_error": f"invalid resource id: {exc}",
        }

    service = project.resource_service()

    try:
        metadata = service.metadata(resource_id)
    except ResourceNotFoundError:
        return {
            "logical_id": str(resource_id),
            "exists": False,
            "decode_status": "not_attempted",
            "decode_error": None,
        }

    result: dict[str, Any] = {
        "logical_id": str(resource_id),
        "exists": True,
        "resolved_path": str(metadata.physical_path) if metadata.physical_path else None,
        "content_size": metadata.size,
        "content_hash": metadata.content_hash,
        "modified_ns": metadata.modified_ns,
        "extension": Path(resource_id.path).suffix,
        "decode_status": "not_attempted",
        "decode_error": None,
        "pixel_width": None,
        "pixel_height": None,
        "has_alpha": None,
        "cache_key": str(resource_id),
        "last_provider_failure": None,
    }

    if result["extension"].lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
        result["decode_status"] = "skipped"
        result["decode_error"] = f"not a recognized image extension: {result['extension']!r}"
        return result

    try:
        import pygame

        from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider
    except Exception as exc:  # noqa: BLE001
        result["decode_status"] = "failed"
        result["decode_error"] = f"pygame unavailable in the configured Expra interpreter: {exc}"
        return result

    provider = PygameResourceProvider(pygame, service)
    surface = provider(str(resource_id))
    if surface is None:
        result["decode_status"] = "failed"
        failure = provider.last_failure
        if failure is not None:
            stage, message = failure
            result["decode_error"] = message
            result["last_provider_failure"] = {"stage": stage, "message": message}
        return result

    result["decode_status"] = "ok"
    width, height = surface.get_size()
    result["pixel_width"] = width
    result["pixel_height"] = height
    try:
        result["has_alpha"] = surface.get_masks()[3] != 0
    except Exception:  # noqa: BLE001 -- best-effort, never fail the trace over this
        result["has_alpha"] = None

    if req.get("include_preview"):
        buffer = io.BytesIO()
        pygame.image.save(surface, buffer, "PNG")
        result["_preview_png_base64"] = base64.b64encode(buffer.getvalue()).decode("ascii")

    return result


# ---------------------------------------------------------------------------
# render_inspect (static-only: capabilities, entity, frame, plan, operation,
# captures. "cache" is inherently live-only -- reported as unavailable.)
# ---------------------------------------------------------------------------


def _renderer_capabilities(resource_provider: Any) -> dict:
    import pygame

    from expra_engine.runtime.pygame_renderer import PygameRenderer

    surface = pygame.Surface((64, 64))
    renderer = PygameRenderer(pygame, surface, resource_provider=resource_provider)
    caps = renderer.capabilities
    return {
        "primitive": caps.primitive,
        "text": caps.text,
        "texture": caps.texture,
        "outline": caps.outline,
        "nine_slice": caps.nine_slice,
        "blend_mode": caps.blend_mode,
        "resize": caps.resize,
        "headless": caps.headless,
        "screen_capture": caps.screen_capture,
        "screen_texture": caps.screen_texture,
        "screen_texture_mipmaps": caps.screen_texture_mipmaps,
    }


def _extract_frame_and_plan(scene: Any):
    from expra_engine.runtime.render_extractor import extract_render_frame
    from expra_engine.runtime.render_pipeline import RenderPlanBuilder

    frame = extract_render_frame(scene)
    plan = RenderPlanBuilder.from_frame(frame)
    return frame, plan


def _render_item_to_dict(item: Any) -> dict:
    primitive = item.primitive
    material = item.material
    return {
        "key": item.key,
        "primitive": {
            "kind": getattr(primitive, "kind", None),
            "size": _safe(getattr(primitive, "size", None)),
            "radius": getattr(primitive, "radius", None),
        },
        "transform": {
            "position": list(item.transform.position),
            "rotation": item.transform.rotation,
            "scale": list(item.transform.scale),
        },
        "material": {
            "color": _color_to_list(getattr(material, "color", None)),
            "opacity": getattr(material, "opacity", None),
            "texture_id": getattr(material, "texture_id", None),
            "tint": _color_to_list(getattr(material, "tint", None)),
            "outline": _color_to_list(getattr(material, "outline", None)),
            "outline_width": getattr(material, "outline_width", None),
            "blend_mode": getattr(material, "blend_mode", None),
        },
        "phase": getattr(item.phase, "name", str(item.phase)),
        "layer": item.layer,
        "visible": item.visible,
    }


def _operation_to_dict(op: Any) -> dict:
    from expra_engine.runtime.render_pipeline import (
        CaptureScreenOp,
        DrawItemOp,
        DrawScreenTextureOp,
        GenerateScreenMipmapsOp,
    )

    order = _safe(op.order)
    if isinstance(op, DrawItemOp):
        return {"kind": "draw_item", "order": order, "item": _render_item_to_dict(op.item)}
    if isinstance(op, CaptureScreenOp):
        request = op.request
        return {
            "kind": "capture_screen",
            "order": order,
            "automatic": op.automatic,
            "capture_id": getattr(request, "capture_id", None),
            "copy_mode": getattr(request, "copy_mode", None),
            "rect": _safe(getattr(request, "rect", None)),
        }
    if isinstance(op, GenerateScreenMipmapsOp):
        return {"kind": "generate_screen_mipmaps", "order": order, "capture_id": op.capture_id}
    if isinstance(op, DrawScreenTextureOp):
        request = op.request
        return {
            "kind": "draw_screen_texture",
            "order": order,
            "capture_id": getattr(request, "capture_id", None),
            "width": getattr(request, "width", None),
            "height": getattr(request, "height", None),
            "uv_rect": _safe(getattr(request, "uv_rect", None)),
            "opacity": getattr(request, "opacity", None),
        }
    return {"kind": type(op).__name__, "order": order}


def op_render_inspect(req: dict) -> dict:
    action = req["action"]

    if action == "capabilities":
        resource_provider = None
        if req.get("project"):
            project = _load_project(req["expra_root"], req["project"])
            try:
                import pygame

                from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider

                resource_provider = PygameResourceProvider(pygame, project.resource_service())
            except Exception:  # noqa: BLE001 -- capabilities without a provider is still valid
                resource_provider = None
        return {
            "action": action,
            "executed_project_code": False,
            "capabilities": _renderer_capabilities(resource_provider),
            "note": (
                "constructed a headless PygameRenderer (no pygame.display call at all) "
                "purely to read its declared capability flags"
                + ("" if resource_provider else "; no project given, so texture/nine_slice reflect a renderer with no resource provider")
            ),
        }

    if action == "cache":
        return {
            "action": action,
            "executed_project_code": False,
            "available_statically": False,
            "note": (
                "resource/texture cache state is only meaningful across a live renderer's "
                "lifetime; each static inspection call is a fresh, isolated subprocess with "
                "no persistent cache. Use editor_session (Phase 2F) for live cache introspection."
            ),
        }

    project = _load_project(req["expra_root"], req["project"])
    scene = _load_scene(project, req.get("scene"))
    frame, plan = _extract_frame_and_plan(scene)

    if action == "frame":
        return {
            "action": action,
            "executed_project_code": False,
            "item_count": len(frame.items),
            "elapsed": frame.elapsed,
            "modulation": _color_to_list(frame.modulation),
            "items": [_render_item_to_dict(item) for item in frame.items],
        }

    if action == "plan":
        return {
            "action": action,
            "executed_project_code": False,
            "operation_count": len(plan.operations),
            "capture_ids": list(plan.capture_ids),
            "operations": [_operation_to_dict(op) for op in plan.operations],
        }

    if action == "operation":
        index = req["operation_index"]
        operations = plan.operations
        if index < 0 or index >= len(operations):
            raise IndexError(f"operation_index {index} out of range (plan has {len(operations)} operations)")
        return {
            "action": action,
            "executed_project_code": False,
            "operation_index": index,
            "operation": _operation_to_dict(operations[index]),
        }

    if action == "captures":
        return {
            "action": action,
            "executed_project_code": False,
            "capture_count": len(plan.capture_ids),
            "capture_ids": list(plan.capture_ids),
            "capture_operations": [
                _operation_to_dict(op) for op in plan.operations if type(op).__name__ != "DrawItemOp"
            ],
        }

    if action == "entity":
        entity = _find_entity(scene, req["entity"])
        x, y, rotation = scene.world_pose(entity.entity_id)
        matching_items = [_render_item_to_dict(item) for item in frame.items if item.key == entity.entity_id]
        return {
            "action": action,
            "executed_project_code": False,
            "entity": {"entity_id": entity.entity_id, "name": entity.name},
            "world_transform": {"x": x, "y": y, "rotation": rotation},
            "render_items": matching_items,
            "note": None if matching_items else (
                "no RenderItem was extracted for this entity -- it likely has no enabled/"
                "visible visual component (PrimitiveComponent/SpriteComponent/TextComponent/"
                "AnimatedSprite2DComponent), or the entity itself is disabled"
            ),
        }

    if action == "compare_modes":
        from expra_engine.runtime.rendering import OrthographicCamera

        edit_w = int(req.get("edit_viewport_width", 400))
        edit_h = int(req.get("edit_viewport_height", 300))
        runtime_w = int(req.get("runtime_viewport_width", 400))
        runtime_h = int(req.get("runtime_viewport_height", 300))
        base_width = float(req.get("camera_width", 20.0))

        # Mirrors the REAL construction each context uses: OrthographicCamera
        # seeds its aspect ratio from (width, height) at __init__ time (see
        # rendering.py -- it passes viewport=(width, height) to Camera2D
        # purely to encode that aspect). Applying scene.camera's "width" via
        # apply_dict() then RECOMPUTES height preserving that seed aspect --
        # so if edit_viewport and runtime_viewport have different pixel
        # aspect ratios, the resulting world-space heights will genuinely
        # differ, and that difference is real camera math, not a guess.
        edit_camera = OrthographicCamera(width=base_width, height=base_width * edit_h / edit_w)
        edit_camera.apply_dict(scene.camera)
        runtime_camera = OrthographicCamera(width=base_width, height=base_width * runtime_h / runtime_w)
        runtime_camera.apply_dict(scene.camera)

        def _cam_summary(cam: Any) -> dict:
            return {
                "position": list(cam.position),
                "width": cam.width,
                "height": cam.height,
                "rotation": cam.rotation,
                "zoom": cam.zoom,
            }

        edit_summary = _cam_summary(edit_camera)
        runtime_summary = _cam_summary(runtime_camera)
        edit_aspect = edit_w / edit_h
        runtime_aspect = runtime_w / runtime_h

        differences = []
        for field_name in ("position", "width", "rotation", "zoom"):
            if edit_summary[field_name] != runtime_summary[field_name]:
                differences.append(
                    {
                        "field": field_name,
                        "edit_value": edit_summary[field_name],
                        "runtime_value": runtime_summary[field_name],
                        "classification": "ENGINE_PARITY_BUG",
                        "evidence": (
                            f"{field_name} is applied identically from scene.camera by both "
                            "paths -- a mismatch here means something other than the supplied "
                            "viewport aspect ratios is responsible; investigate directly"
                        ),
                    }
                )
        if edit_summary["height"] != runtime_summary["height"]:
            classification = "EXPECTED_EDITOR_DIFFERENCE" if edit_aspect != runtime_aspect else "ENGINE_PARITY_BUG"
            differences.append(
                {
                    "field": "height",
                    "edit_value": edit_summary["height"],
                    "runtime_value": runtime_summary["height"],
                    "classification": classification,
                    "evidence": (
                        f"edit_viewport aspect ({edit_w}x{edit_h} = {edit_aspect:.4f}) vs "
                        f"runtime_viewport aspect ({runtime_w}x{runtime_h} = {runtime_aspect:.4f}) "
                        "differ, and OrthographicCamera recomputes height to preserve its "
                        "construction-time aspect when width is overridden by scene.camera -- "
                        "this height difference directly follows from that, mathematically"
                        if edit_aspect != runtime_aspect
                        else "aspects match but heights still differ -- unexplained by viewport "
                        "aspect alone, investigate directly"
                    ),
                }
            )

        default_viewports_used = (
            req.get("edit_viewport_width") is None
            and req.get("edit_viewport_height") is None
            and req.get("runtime_viewport_width") is None
            and req.get("runtime_viewport_height") is None
        )

        return {
            "action": action,
            "executed_project_code": False,
            "edit": {"camera": edit_summary, "viewport": {"width": edit_w, "height": edit_h}, "item_count": len(frame.items)},
            "runtime": {"camera": runtime_summary, "viewport": {"width": runtime_w, "height": runtime_h}, "item_count": len(frame.items)},
            "modulation": _color_to_list(frame.modulation),
            "differences": differences,
            "note": (
                "edit_viewport_width/height and runtime_viewport_width/height were not "
                "supplied, so both default to 400x300 (identical aspect) -- this comparison "
                "is NOT informative until you supply the real pixel size of the live editor "
                "panel (Tk Canvas) and the real game window size (found via source_read on "
                "the project's __main__.py, since that is hardcoded there and not discoverable "
                "from project.json)."
                if default_viewports_used
                else None
            ),
        }

    raise ValueError(f"unknown render_inspect action: {action!r}")


# ---------------------------------------------------------------------------
# render_snapshot
# ---------------------------------------------------------------------------


class _RecordCapture(logging.Handler):
    """Captures log records emitted during one render call for later
    diagnostics_analyze aggregation -- RenderDiagnostics itself only
    dedups within a single process (confirmed: no count/timestamp
    tracking), so the counting/signature work has to happen on the
    captured records, not by wrapping RenderDiagnostics.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            formatted = record.getMessage()
        except Exception:  # noqa: BLE001 -- never let a bad record crash the capture
            formatted = str(record.msg)
        self.records.append(
            {
                "logger": record.name,
                "level": record.levelname,
                "message_template": str(record.msg),
                "formatted": formatted,
                "timestamp": record.created,
            }
        )


def _compare_images(pygame_module: Any, baseline_bytes: bytes, candidate_bytes: bytes) -> dict:
    baseline = pygame_module.image.load(io.BytesIO(baseline_bytes))
    candidate = pygame_module.image.load(io.BytesIO(candidate_bytes))
    bw, bh = baseline.get_size()
    cw, ch = candidate.get_size()
    if (bw, bh) != (cw, ch):
        return {"same_dimensions": False}

    different = 0
    total_abs_diff = 0
    min_x, min_y = cw, ch
    max_x, max_y = -1, -1
    for y in range(ch):
        for x in range(cw):
            pb = baseline.get_at((x, y))
            pc = candidate.get_at((x, y))
            diff = abs(pb[0] - pc[0]) + abs(pb[1] - pc[1]) + abs(pb[2] - pc[2]) + abs(pb[3] - pc[3])
            if diff:
                different += 1
                total_abs_diff += diff
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

    total_pixels = cw * ch
    return {
        "same_dimensions": True,
        "different_pixel_count": different,
        "difference_ratio": (different / total_pixels) if total_pixels else 0.0,
        "mean_absolute_difference": (total_abs_diff / (different * 4)) if different else 0.0,
        "bounding_box": (
            {"x": min_x, "y": min_y, "width": max_x - min_x + 1, "height": max_y - min_y + 1}
            if max_x >= 0
            else None
        ),
    }


def op_render_snapshot(req: dict) -> dict:
    import pygame

    # Real fonts require pygame.font's SDL_ttf backend to be initialized --
    # every real Expra entry point calls pygame.init() (which includes this)
    # at startup; this subprocess is the one place that has to do it
    # explicitly. Font-only init avoids touching display/audio/joystick,
    # which keeps this safe on a machine with no video driver at all.
    pygame.font.init()

    from expra_engine.runtime.pygame_renderer import PygameRenderer
    from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider
    from expra_engine.runtime.render_diagnostics import RenderDiagnostics
    from expra_engine.runtime.render_extractor import extract_render_frame
    from expra_engine.runtime.rendering import OrthographicCamera, RenderContext, Viewport
    from expra_engine.ui.editor_pixel_renderer import (
        encode_pygame_surface,
        render_editor_frame_to_image,
    )

    mode = req["mode"]
    project = _load_project(req["expra_root"], req["project"])
    scene = _load_scene(project, req.get("scene"))
    width = int(req.get("viewport_width", 400))
    height = int(req.get("viewport_height", 300))
    elapsed = float(req.get("elapsed", 0.0))

    frame = extract_render_frame(scene, elapsed=elapsed)
    entity_names = {e.entity_id: e.name for e in scene.entities}
    resource_provider = PygameResourceProvider(pygame, project.resource_service())

    base_width = float(req.get("camera_width", 20.0))
    camera = OrthographicCamera(width=base_width, height=base_width * height / width)
    camera.apply_dict(scene.camera)
    context = RenderContext(Viewport(0, 0, width, height), camera)

    render_logger = logging.getLogger("expra_engine.runtime.pygame_renderer")
    editor_logger = logging.getLogger("expra_engine.ui.editor_pixel_renderer")
    capture = _RecordCapture()
    render_logger.addHandler(capture)
    editor_logger.addHandler(capture)
    try:
        if mode == "edit":
            diagnostics = RenderDiagnostics(editor_logger)
            image_bytes = render_editor_frame_to_image(
                frame,
                context,
                surface_factory=lambda size: pygame.Surface(size),
                renderer_factory=lambda surface: PygameRenderer(
                    pygame, surface, screen_size=(width, height), resource_provider=resource_provider
                ),
                encode_surface=lambda surface: encode_pygame_surface(pygame, surface),
                image_factory=lambda data: data,
                diagnostics=diagnostics,
                entity_names=entity_names,
            )
            success = image_bytes is not None
        elif mode == "runtime":
            surface = pygame.Surface((width, height))
            renderer = PygameRenderer(
                pygame, surface, screen_size=(width, height), resource_provider=resource_provider
            )
            renderer.start(context)
            renderer.render(frame)
            success = not renderer.draw_failed
            # Unlike edit mode (which calls the editor's own strict
            # all-or-nothing render_editor_frame_to_image), the per-item draw
            # loop inside PygameRenderer.render() keeps drawing after a
            # single item fails -- the surface still holds real, partially-
            # correct pixels, which is more useful to return than nothing.
            # pixel_renderer_success still reports the real draw_failed state.
            image_bytes = encode_pygame_surface(pygame, surface)
        else:
            raise ValueError(f"unknown render_snapshot mode: {mode!r} (expected 'edit' or 'runtime')")
    finally:
        render_logger.removeHandler(capture)
        editor_logger.removeHandler(capture)

    texture_ids = sorted(
        {item.material.texture_id for item in frame.items if item.material.texture_id is not None}
    )

    result: dict[str, Any] = {
        "mode": mode,
        "executed_project_code": False,
        "width": width,
        "height": height,
        "renderer": "pygame",
        "camera": {
            "position": list(camera.position),
            "width": camera.width,
            "height": camera.height,
            "rotation": camera.rotation,
        },
        "render_item_count": len(frame.items),
        "texture_ids": texture_ids,
        "pixel_renderer_success": success,
        "failures": [r["formatted"] for r in capture.records],
        "diagnostics_records": capture.records,
    }

    if image_bytes is not None:
        result["_png_base64"] = base64.b64encode(image_bytes).decode("ascii")
        if req.get("compare_to_png_base64"):
            baseline_bytes = base64.b64decode(req["compare_to_png_base64"])
            result["comparison"] = _compare_images(pygame, baseline_bytes, image_bytes)

    return result


# ---------------------------------------------------------------------------
# runtime_probe -- the ONE place in this runner that genuinely executes
# project-authored Python (Behaviour subclasses, via ScriptRegistry's real
# importlib.util.spec_from_file_location/exec_module -- confirmed by reading
# runtime/script_registry.py). Every other op in this file is pure data
# parsing. One Engine instance is built and driven through the caller's
# entire step sequence within this single subprocess invocation, since state
# (scene, behaviours, physics) must persist across steps.
# ---------------------------------------------------------------------------


def _entity_snapshot(scene: Any, entity: Any) -> dict:
    x, y, rotation = scene.world_pose(entity.entity_id)
    return {"entity": entity.to_dict(), "world_pose": {"x": x, "y": y, "rotation": rotation}}


def _run_probe_step(engine: Any, action: str, step: dict) -> dict:
    from expra_engine.runtime.input import PhysicalInput
    from expra_engine.runtime.physics_world import PhysicsWorld2D
    from expra_engine.runtime.render_extractor import extract_render_frame

    if action == "play":
        return {"playing": bool(engine.play())}
    if action == "pause":
        engine.pause()
        return {}
    if action == "resume":
        return {"playing": bool(engine.play())}
    if action == "stop":
        engine.stop()
        return {}
    if action == "tick":
        dt = float(step.get("dt", 1.0 / 60.0))
        elapsed = engine.tick(dt)
        return {"requested_dt": dt, "elapsed": elapsed}
    if action in ("key_down", "key_up"):
        key = step["key"]
        physical = PhysicalInput("keyboard", key)
        transitions = engine.input_map.press(physical) if action == "key_down" else engine.input_map.release(physical)
        for event in transitions:
            engine.signal(event)
        return {
            "physical": {"device": "keyboard", "code": key},
            "action_events": [
                {
                    "action": getattr(e.action, "value", None) or getattr(e.action, "name", None) or str(e.action),
                    "phase": e.phase,
                }
                for e in transitions
            ],
        }
    if action == "inspect_entity":
        scene = engine.active_scene
        entity = _find_entity(scene, step["entity"])
        return _entity_snapshot(scene, entity)
    if action == "inspect_render":
        scene = engine.active_scene
        entity = _find_entity(scene, step["entity"])
        frame = extract_render_frame(scene)
        items = [_render_item_to_dict(item) for item in frame.items if item.key == entity.entity_id]
        return {
            "entity": {"entity_id": entity.entity_id, "name": entity.name},
            "render_items": items,
        }
    if action == "raycast":
        scene = engine.active_scene
        physics = PhysicsWorld2D(scene)
        hit = physics.raycast(
            tuple(step["origin"]),
            tuple(step["direction"]),
            float(step["distance"]),
            mask=int(step.get("mask", 0xFFFFFFFF)),
            include_triggers=bool(step.get("include_triggers", True)),
        )
        return {
            "hit": hit.hit,
            "entity_id": hit.entity_id,
            "point": list(hit.point) if hit.point is not None else None,
            "normal": list(hit.normal) if hit.normal is not None else None,
            "distance": hit.distance,
            "fraction": hit.fraction,
        }
    if action == "overlap":
        scene = engine.active_scene
        physics = PhysicsWorld2D(scene)
        overlapping = physics.overlap(step["entity"], include_triggers=bool(step.get("include_triggers", True)))
        return {"body_id": step["entity"], "overlapping": list(overlapping)}

    raise ValueError(f"unknown runtime_probe step action: {action!r}")


def op_runtime_probe(req: dict) -> dict:
    from expra_engine.core.engine import Engine
    from expra_engine.observability import ObservabilityWatcher, serialize_observability

    project = _load_project(req["expra_root"], req["project"])
    observer = ObservabilityWatcher()
    scene = _load_scene(project, req.get("scene"), observer=observer)

    engine = Engine(observer=observer)
    engine.set_project(project)
    engine.set_scene(scene)
    # MUST happen before any "play" step: engine.behaviour_system is a lazy
    # property that registers BehaviourSystem into engine._systems on first
    # access. If never accessed, play() silently never instantiates any
    # ScriptComponent's Behaviour -- confirmed by reading core/engine.py.
    _ = engine.behaviour_system

    step_results = []
    for index, step in enumerate(req.get("steps", [])):
        action = step.get("action")
        try:
            data = _run_probe_step(engine, action, step)
            step_results.append({"index": index, "action": action, "ok": True, "data": data, "error": None})
        except Exception as exc:  # noqa: BLE001 -- one bad step must not abort the whole probe
            step_results.append(
                {"index": index, "action": action, "ok": False, "data": {}, "error": f"{type(exc).__name__}: {exc}"}
            )

    return {
        "project": req["project"],
        "executed_project_code": True,
        "steps": step_results,
        "observability": json.loads(serialize_observability(observer)),
    }


# ---------------------------------------------------------------------------
# export_inspect
# ---------------------------------------------------------------------------


def _asset_manifest_summary(manifest: Any, *, sample: int = 20) -> dict:
    entries = manifest.entries
    return {
        "file_count": len(entries),
        "total_size": sum(e.size for e in entries),
        "sample_paths": [e.path for e in entries[:sample]],
    }


def op_export_inspect(req: dict) -> dict:
    from expra_engine.export.exporter import ExportError, GameExporter
    from expra_engine.export.manifest import AssetManifest
    from expra_engine.export.plan import ExportPlan, ExportTarget, PythonArch, RuntimeProfile
    from expra_engine.export.verify import (
        ExportVerificationError,
        _scan_for_forbidden_imports,
        verify_export,
    )

    action = req["action"]

    if action == "verify":
        build_dir = Path(req["build_dir"])
        if not build_dir.is_dir():
            raise ValueError(f"build_dir does not exist or is not a directory: {build_dir}")
        result: dict[str, Any] = {"action": action, "build_dir": str(build_dir)}
        try:
            verify_export(build_dir)
            result["verification"] = {"success": True, "error": None}
        except ExportVerificationError as exc:
            result["verification"] = {"success": False, "error": str(exc)}

        forbidden = _scan_for_forbidden_imports(build_dir)
        result["forbidden_imports"] = forbidden

        manifest_path = build_dir / "build_manifest.json"
        if manifest_path.is_file():
            result["build_manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
        asset_manifest_path = build_dir / "asset_manifest.json"
        if asset_manifest_path.is_file():
            asset_manifest = AssetManifest.from_json(asset_manifest_path.read_text(encoding="utf-8"))
            result["asset_manifest"] = _asset_manifest_summary(asset_manifest)
        return result

    # "plan" and "export" both need a real ExportPlan first.
    project = _load_project(req["expra_root"], req["project"])
    output_dir = Path(req["output_dir"])
    try:
        plan = ExportPlan(
            project_dir=project.path,
            entry_point=req.get("entry_point", project.entry_point),
            output_dir=output_dir,
            target=ExportTarget(req.get("target", "linux")),
            game_name=req.get("game_name", project.name),
            game_version=req.get("game_version", project.game_version),
            python_version=req.get("python_version", "3.12.4"),
            arch=PythonArch(req.get("arch", "amd64")),
            compile_bytecode=bool(req.get("compile_bytecode", True)),
            runtime_profile=RuntimeProfile(req.get("runtime_profile", "pygame")),
        )
    except ValueError as exc:
        return {"action": action, "plan_valid": False, "plan_error": str(exc)}

    plan_summary = {
        "project_dir": str(plan.project_dir),
        "entry_point": plan.entry_point,
        "output_dir": str(plan.output_dir),
        "target": plan.target.value,
        "game_name": plan.game_name,
        "game_version": plan.game_version,
        "python_version": plan.python_version,
        "arch": plan.arch.value,
        "compile_bytecode": plan.compile_bytecode,
        "runtime_profile": plan.runtime_profile.value,
    }

    if action == "plan":
        return {"action": action, "plan_valid": True, "plan_error": None, "plan": plan_summary}

    if action == "export":
        import threading

        result = {"action": action, "plan": plan_summary}
        try:
            build_dir = GameExporter().export(plan, cancel=threading.Event())
        except ExportError as exc:
            result["success"] = False
            result["error"] = str(exc)
            result["build_dir"] = None
            return result

        result["success"] = True
        result["error"] = None
        result["build_dir"] = str(build_dir)

        manifest_path = build_dir / "build_manifest.json"
        if manifest_path.is_file():
            result["build_manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
        asset_manifest_path = build_dir / "asset_manifest.json"
        if asset_manifest_path.is_file():
            asset_manifest = AssetManifest.from_json(asset_manifest_path.read_text(encoding="utf-8"))
            result["asset_manifest"] = _asset_manifest_summary(asset_manifest)

        try:
            verify_export(build_dir)
            result["verification"] = {"success": True, "error": None}
        except ExportVerificationError as exc:
            result["verification"] = {"success": False, "error": str(exc)}
        result["forbidden_imports"] = _scan_for_forbidden_imports(build_dir)
        return result

    raise ValueError(f"unknown export_inspect action: {action!r}")


# ---------------------------------------------------------------------------
# performance_probe
# ---------------------------------------------------------------------------


def _synthetic_document(
    *,
    entity_count: int,
    kind: str,
    hierarchy_depth: int,
    breadth: int,
    component_density: float,
    instance_count: int,
):
    from expra_engine.core.component import OpaqueComponent, TransformComponent
    from expra_engine.core.scene import Level, LevelMetadata, Scene, SceneInstanceComponent

    if entity_count < 1 or entity_count > 5000:
        raise ValueError("synthetic_entity_count must be between 1 and 5000")
    if kind not in ("scene", "level"):
        raise ValueError("synthetic_kind must be 'scene' or 'level'")
    if hierarchy_depth < 0 or breadth < 1 or instance_count < 0:
        raise ValueError("synthetic hierarchy and instance values must be non-negative")
    if not 0.0 <= component_density <= 1.0:
        raise ValueError("synthetic_component_density must be between 0 and 1")

    document = (
        Level(
            "Synthetic Level",
            scene_id="synthetic-level",
            level_metadata=LevelMetadata(display_name="Synthetic Level"),
        )
        if kind == "level"
        else Scene("Synthetic Scene", scene_id="synthetic-scene")
    )
    depths: list[int] = []
    entities: list[Any] = []
    for index in range(entity_count):
        parent_id = None
        depth = 0
        if index and hierarchy_depth:
            candidate = (index - 1) // breadth
            if candidate < len(entities) and depths[candidate] < hierarchy_depth:
                parent_id = entities[candidate].entity_id
                depth = depths[candidate] + 1
        entity = document.create_entity(
            f"Synthetic Entity {index}",
            entity_id=f"synthetic-entity-{index}",
            parent_id=parent_id,
        )
        entity.add_tag("synthetic")
        entity.add_tag("even" if index % 2 == 0 else "odd")
        entity.add_component(TransformComponent(x=float(index), y=float(depth)))
        if index == 0 or index / max(entity_count, 1) < component_density:
            entity.add_component(
                OpaqueComponent(
                    {
                        "type": "synthetic.opaque",
                        "enabled": True,
                        "index": index,
                        "values": [index, index / 10.0, index % 3 == 0],
                        "labels": {"kind": kind, "depth": depth},
                    }
                )
            )
        entities.append(entity)
        depths.append(depth)

    for index in range(instance_count):
        instance = document.create_entity(
            f"Synthetic Instance {index}", entity_id=f"synthetic-instance-{index}"
        )
        instance.add_component(SceneInstanceComponent("scenes/synthetic_source.scene.pb"))
    return document


def _synthetic_project(request: dict) -> tuple[TemporaryDirectory[str], Any, str, str]:
    from expra_engine.core.project import Project
    from expra_engine.core.scene import Scene

    temporary = TemporaryDirectory(prefix="expra-document-probe-")
    project = Project.create("Synthetic Document Probe", Path(temporary.name) / "project")
    document = _synthetic_document(
        entity_count=int(request.get("synthetic_entity_count", 100)),
        kind=str(request.get("synthetic_kind", "scene")),
        hierarchy_depth=int(request.get("synthetic_hierarchy_depth", 0)),
        breadth=int(request.get("synthetic_breadth", 4)),
        component_density=float(request.get("synthetic_component_density", 0.5)),
        instance_count=int(request.get("synthetic_instance_count", 0)),
    )
    source = Scene("Synthetic Source", scene_id="synthetic-source")
    source.create_entity("Synthetic Source Entity", entity_id="synthetic-source-entity")
    project.save_document(source, "scenes/synthetic_source.scene.pb")
    pb_path = (
        "levels/synthetic.level.pb"
        if document.document_kind.value == "level"
        else "scenes/synthetic.scene.pb"
    )
    json_path = (
        "levels/synthetic.level.json"
        if document.document_kind.value == "level"
        else "scenes/synthetic.json"
    )
    project.save_document(document, pb_path)
    if document.document_kind.value == "level":
        json_file = project.path / json_path
        json_file.parent.mkdir(parents=True, exist_ok=True)
        json_file.write_text(json.dumps(document.to_dict(include_instance_content=False), indent=2))
        project.register_level_path(json_path)
    else:
        project.save_scene(document, json_path)
    project.save()
    # Reload through the normal manifest path, not the creation-time object.
    return temporary, Project.load(project.path), pb_path, json_path


def _document_stage_stats(observer: Any | None) -> dict[str, dict[str, Any]]:
    if observer is None:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for metric in observer.snapshot().metrics:
        distribution = metric.distribution
        result[metric.target] = {
            "count": metric.count,
            "min_ms": float(distribution.get("minimum", 0.0)) * 1000.0,
            "p50_ms": float(distribution.get("p50", 0.0)) * 1000.0,
            "p95_ms": float(distribution.get("p95", 0.0)) * 1000.0,
            "max_ms": float(distribution.get("maximum", 0.0)) * 1000.0,
            "failures": metric.failures,
            "in_flight": metric.in_flight,
            "peak_in_flight": metric.peak_in_flight,
        }
    return result


def _document_shape(document: Any) -> tuple[int, int, int]:
    entities = list(document.entities)
    components = sum(len(entity.components) for entity in entities)
    instances = sum(
        1
        for entity in entities
        for component in entity.components
        if getattr(component, "component_type", None) == "scene_instance"
    )
    return len(entities), components, instances


def _measure_document_load(
    project: Any,
    resource: str,
    *,
    iterations: int,
    observer_enabled: bool,
) -> dict[str, Any]:
    from expra_engine.observability import ObservabilityWatcher

    path = project.document_file(resource)
    format_name = "protobuf" if str(path).casefold().endswith(".pb") else "legacy_json"
    observer = (
        ObservabilityWatcher(sample_limit=min(max(iterations, 128), 4096))
        if observer_enabled
        else None
    )
    first_start = time.perf_counter()
    try:
        document = project.load_document(resource, observer=observer)
    except Exception as exc:  # noqa: BLE001 -- preserve stage attribution in probe output
        stages = _document_stage_stats(observer)
        failed_stages = [target for target, data in stages.items() if data["failures"]]
        return {
            "resource": resource,
            "format": format_name,
            "kind": None,
            "bytes": path.stat().st_size if path.exists() else 0,
            "entities": 0,
            "components": 0,
            "instances": 0,
            "iterations": 0,
            "duration_seconds": 0.0,
            "first_load_total_ms": (time.perf_counter() - first_start) * 1000.0,
            "observer_enabled": observer_enabled,
            "stages": stages,
            "error": f"{type(exc).__name__}: {exc}",
            "failed_stage": failed_stages[-1] if failed_stages else None,
        }
    first_load_total_ms = (time.perf_counter() - first_start) * 1000.0
    if observer is not None:
        observer.reset()
    start = time.perf_counter()
    for _ in range(iterations):
        document = project.load_document(resource, observer=observer)
    duration = time.perf_counter() - start
    entities, components, instances = _document_shape(document)
    return {
        "resource": resource,
        "format": format_name,
        "kind": document.document_kind.value,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "entities": entities,
        "components": components,
        "instances": instances,
        "iterations": iterations,
        "duration_seconds": duration,
        "first_load_total_ms": first_load_total_ms,
        "observer_enabled": observer_enabled,
        "stages": _document_stage_stats(observer),
        "error": None,
        "failed_stage": None,
    }


def op_performance_probe(req: dict) -> dict:
    action = req["action"]

    if action == "document_load":
        temporary = None
        if req.get("synthetic_entity_count") is not None:
            temporary, project, pb_path, json_path = _synthetic_project(req)
            resource = req.get("resource") or pb_path
            compare_resource = req.get("compare_resource")
            if req.get("synthetic_compare") and compare_resource is None:
                compare_resource = json_path if resource == pb_path else pb_path
        else:
            if not req.get("project") or not req.get("resource"):
                raise ValueError("action='document_load' requires 'project' and 'resource'")
            project = _load_project(req["expra_root"], req["project"])
            resource = req["resource"]
            compare_resource = req.get("compare_resource")
        try:
            iterations = max(1, int(req.get("iterations", 30)))
            observer_enabled = bool(req.get("observer_enabled", True))
            resources = [resource]
            if compare_resource:
                resources.append(compare_resource)
            results = [
                _measure_document_load(
                    project,
                    item,
                    iterations=iterations,
                    observer_enabled=observer_enabled,
                )
                for item in resources
            ]
            primary = dict(results[0])
            primary["action"] = action
            primary["verdict"] = "measured"
            primary["comparisons"] = results if len(results) > 1 else []
            return primary
        finally:
            if temporary is not None:
                temporary.cleanup()

    if action == "render_stress":
        import pygame

        pygame.font.init()
        from expra_engine.runtime.pygame_renderer import PygameRenderer
        from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider
        from expra_engine.runtime.render_extractor import extract_render_frame
        from expra_engine.runtime.rendering import OrthographicCamera, RenderContext, Viewport

        project = _load_project(req["expra_root"], req["project"])
        scene = _load_scene(project, req.get("scene"))
        width = int(req.get("viewport_width", 400))
        height = int(req.get("viewport_height", 300))
        iterations = max(1, int(req.get("iterations", 50)))
        track_memory = bool(req.get("track_memory", False))

        resource_provider = PygameResourceProvider(pygame, project.resource_service())
        base_width = float(req.get("camera_width", 20.0))
        camera = OrthographicCamera(width=base_width, height=base_width * height / width)
        camera.apply_dict(scene.camera)
        context = RenderContext(Viewport(0, 0, width, height), camera)

        render_logger = logging.getLogger("expra_engine.runtime.pygame_renderer")
        # Measure BEFORE attaching our own capture handler, or "before" would
        # always include it -- an off-by-one that made every call report a
        # spurious handler leak.
        handlers_before = len(render_logger.handlers)
        cache_before = len(getattr(resource_provider, "_texture_identities", {}))

        capture = _RecordCapture()
        render_logger.addHandler(capture)

        tracemalloc_mod = None
        snapshot_before = None
        if track_memory:
            import tracemalloc as tracemalloc_mod

            tracemalloc_mod.start()
            snapshot_before = tracemalloc_mod.take_snapshot()

        surface = pygame.Surface((width, height))
        renderer = PygameRenderer(pygame, surface, screen_size=(width, height), resource_provider=resource_provider)

        distinct_texture_ids: set[str] = set()
        start = time.monotonic()
        for _ in range(iterations):
            frame = extract_render_frame(scene)
            distinct_texture_ids.update(
                item.material.texture_id for item in frame.items if item.material.texture_id is not None
            )
            renderer.start(context)
            renderer.render(frame)
        duration = time.monotonic() - start

        render_logger.removeHandler(capture)
        cache_after = len(getattr(resource_provider, "_texture_identities", {}))
        handlers_after = len(render_logger.handlers)

        memory_delta_kb = None
        if track_memory and tracemalloc_mod is not None and snapshot_before is not None:
            snapshot_after = tracemalloc_mod.take_snapshot()
            diff = snapshot_after.compare_to(snapshot_before, "lineno")
            memory_delta_kb = sum(stat.size_diff for stat in diff) / 1024
            tracemalloc_mod.stop()

        signatures: dict[tuple[str, str], int] = {}
        for record in capture.records:
            key = (record["logger"], record["message_template"])
            signatures[key] = signatures.get(key, 0) + 1

        # A healthy cache resolves each DISTINCT texture the scene actually
        # references once, then reuses it every subsequent iteration -- so
        # "bounded" means growth tracks the real distinct-texture count, not
        # a fixed constant (a scene with 3 real sprites growing the cache by
        # 3 is perfectly healthy, not "inconclusive").
        cache_growth = cache_after - cache_before
        expected_bound = max(1, len(distinct_texture_ids))
        if cache_growth <= expected_bound:
            verdict = "bounded"
        elif cache_growth >= iterations:
            verdict = "growing"
        else:
            verdict = "inconclusive"

        return {
            "action": action,
            "iterations": iterations,
            "duration_seconds": duration,
            "resource_cache_count_before": cache_before,
            "resource_cache_count_after": cache_after,
            "logger_handler_count_before": handlers_before,
            "logger_handler_count_after": handlers_after,
            "unique_diagnostic_signatures": len(signatures),
            "total_diagnostic_occurrences": len(capture.records),
            "memory_delta_kb": memory_delta_kb,
            "verdict": verdict,
        }

    if action == "resource_cache":
        import pygame

        pygame.font.init()
        from expra_engine.runtime.pygame_resource_provider import PygameResourceProvider

        project = _load_project(req["expra_root"], req["project"])
        asset_ids = req["asset_ids"]
        iterations = max(1, int(req.get("iterations", 20)))
        resource_provider = PygameResourceProvider(pygame, project.resource_service())

        cache_before = len(getattr(resource_provider, "_texture_identities", {}))
        start = time.monotonic()
        for _ in range(iterations):
            for asset_id in asset_ids:
                resource_provider(asset_id)
        duration = time.monotonic() - start
        cache_after = len(getattr(resource_provider, "_texture_identities", {}))

        # A healthy cache resolves each distinct asset once and reuses it --
        # cache size should track len(asset_ids), not iterations * len(asset_ids).
        verdict = "bounded" if cache_after <= len(asset_ids) + 1 else "growing"

        return {
            "action": action,
            "iterations": iterations,
            "duration_seconds": duration,
            "asset_count": len(asset_ids),
            "resource_cache_count_before": cache_before,
            "resource_cache_count_after": cache_after,
            "verdict": verdict,
        }

    raise ValueError(f"unknown performance_probe action: {action!r}")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

_OPS = {
    "expra_inspect": op_expra_inspect,
    "resource_trace": op_resource_trace,
    "render_inspect": op_render_inspect,
    "render_snapshot": op_render_snapshot,
    "runtime_probe": op_runtime_probe,
    "performance_probe": op_performance_probe,
    "export_inspect": op_export_inspect,
}


def main() -> None:
    raw = sys.stdin.read()
    try:
        request = json.loads(raw)
        op = request["op"]
        handler = _OPS[op]
    except Exception as exc:  # noqa: BLE001 -- malformed request must still produce clean JSON
        sys.stdout.write(json.dumps({"ok": False, "kind": "bad_request", "error": str(exc)}))
        return

    try:
        data = handler(request)
    except LookupError as exc:
        sys.stdout.write(json.dumps({"ok": False, "kind": "not_found", "error": str(exc)}))
        return
    except (ValueError, IndexError, KeyError) as exc:
        sys.stdout.write(json.dumps({"ok": False, "kind": "invalid", "error": str(exc)}))
        return
    except Exception as exc:  # noqa: BLE001 -- last resort: still return clean JSON, never a traceback on stdout
        sys.stdout.write(json.dumps({"ok": False, "kind": "internal_error", "error": f"{type(exc).__name__}: {exc}"}))
        return

    sys.stdout.write(json.dumps({"ok": True, "data": data}))


if __name__ == "__main__":
    main()
