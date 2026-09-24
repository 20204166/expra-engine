#!/usr/bin/env python3
"""Long-lived Expra editor worker.

Owns a REAL Tk ``EditorWindow`` on this process's own main thread, driven
entirely through a newline-delimited JSON command protocol over
stdin/stdout. Executed as a subprocess under the CONFIGURED Expra
interpreter -- never imported by the expra-mcp server's own process (design
point 6). Zero dependency on ``expra_dev_mcp``/``mcp`` so it stays runnable
even if those aren't installed in the Expra environment.

Protocol:
    Request  (stdin,  one JSON object per line): {"id": int, "command": str, ...params}
    Response (stdout, one JSON object per line): {"id": int, "ok": bool, "data": {...}}
                                                | {"id": int, "ok": false, "error": str}

The first stdout line is a startup handshake with id=0, reporting whether
the Tk window was constructed successfully.

Threading: a background daemon thread ONLY reads stdin lines and pushes
them onto a queue -- it never touches Tk. All Tk mutation happens on this
process's own main thread inside root.after()-scheduled polling, per the
hard invariant documented in ui/editor_window.py's own module docstring
("ALL Tk mutations on the main thread... Never call widget.after_idle()
from a worker" -- confirmed by reading that file). If stdin closes (the
parent MCP server died), this worker shuts itself down rather than
lingering as an orphaned Tk window.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

_LOGGER = logging.getLogger("expra_editor_worker")


def _send(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _respond(request_id: int, ok: bool, data: dict[str, Any] | None = None, error: str | None = None) -> None:
    payload: dict[str, Any] = {"id": request_id, "ok": ok}
    if ok:
        payload["data"] = data or {}
    else:
        payload["error"] = error or "unknown error"
    _send(payload)


def _reader_thread(command_queue: queue.Queue[dict[str, Any]]) -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            command_queue.put(json.loads(line))
        except ValueError:
            command_queue.put({"id": -1, "command": "__bad_json__", "raw": line})
    command_queue.put({"id": -1, "command": "__stdin_closed__"})


# ---------------------------------------------------------------------------
# Shared helpers (duplicated from _static_runner.py rather than imported --
# these two scripts are each invoked standalone via subprocess and must not
# depend on each other or on expra_dev_mcp being importable in this env)
# ---------------------------------------------------------------------------


def _color_to_list(color: Any) -> list[float] | None:
    if color is None:
        return None
    return [color.red, color.green, color.blue, color.alpha]


def _pixel_fallback_reason(viewport: Any) -> str:
    """Explain why ``viewport`` has no rendered pixel image right now.

    Reads ``EditorPixelRenderer.diagnostics.active_keys()`` -- the same
    signatures the real renderer already tracks to avoid re-logging a
    persistent failure -- rather than re-deriving anything. Falls back to a
    generic explanation when nothing is active (e.g. no scene loaded yet).
    """
    pixel_renderer = getattr(viewport, "_pixel_renderer", None)
    diagnostics = getattr(pixel_renderer, "diagnostics", None)
    active_keys = diagnostics.active_keys() if diagnostics is not None else ()
    if not active_keys:
        return "no rendered pixel frame available (no scene loaded, or nothing rendered yet)"
    category, *rest = active_keys[0]
    if category == "preflight" and len(rest) >= 3 and rest[0] == "primitive":
        return f"unsupported primitive: {rest[2]}"
    if category == "preflight" and len(rest) >= 3 and rest[0] == "source-region":
        return f"invalid source region: entity={rest[1]} resource={rest[2]}"
    if category == "renderer" and len(rest) >= 3 and rest[0] == "texture":
        return f"texture unavailable: {rest[1]}"
    return ": ".join(str(part) for part in active_keys[0])


def _find_entity(scene: Any, entity: str) -> Any:
    found = scene.find_entity(entity) or scene.find_entity_by_name(entity)
    if found is None:
        raise LookupError(f"entity not found (tried as id and as name): {entity!r}")
    return found


def _entity_snapshot(scene: Any, entity: Any) -> dict:
    x, y, rotation = scene.world_pose(entity.entity_id)
    return {"entity": entity.to_dict(), "world_pose": {"x": x, "y": y, "rotation": rotation}}


def _render_item_to_dict(item: Any) -> dict:
    primitive = item.primitive
    material = item.material
    return {
        "key": item.key,
        "primitive": {
            "kind": getattr(primitive, "kind", None),
            "size": list(getattr(primitive, "size", ()) or ()),
            "radius": getattr(primitive, "radius", None),
        },
        "transform": {
            "position": list(item.transform.position),
            "rotation": item.transform.rotation,
            "scale": list(item.transform.scale),
        },
        "material": {
            "color": _color_to_list(getattr(material, "color", None)),
            "texture_id": getattr(material, "texture_id", None),
        },
        "phase": getattr(item.phase, "name", str(item.phase)),
        "layer": item.layer,
        "visible": item.visible,
    }


class _RecordCapture(logging.Handler):
    """Captures log records emitted during a performance_probe stress loop
    (duplicated from _static_runner.py's identical class, not imported --
    these two scripts are each invoked standalone and must not depend on
    each other).
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


# ---------------------------------------------------------------------------
# Command dispatch -- runs entirely on the Tk main thread
# ---------------------------------------------------------------------------


def _dispatch(command: str, params: dict[str, Any], *, engine: Any, window: Any, root: Any, state: dict[str, Any]) -> dict:
    if command == "open_project":
        from expra_engine.core.project import Project
        from expra_engine.runtime.script_registry import ScriptRegistry

        expra_root = Path(params["expra_root"])
        project = Project.load(expra_root / params["project"])
        scene = project.load_scene(params.get("scene"))
        # Mirrors editor/project_workflow.py's ProjectWorkflow.open_loaded()
        # exactly (confirmed by reading it), so this behaves identically to
        # a human choosing File > Open Project.
        window._engine.set_project(project)
        window._engine.set_scene(scene)
        window._viewport.set_resource_service(project.resource_service())
        window._engine.set_script_registry(ScriptRegistry(project.path))
        window._selected_id = None
        window._root.title(f"{project.name} — Expra Editor")
        window._present_all()
        # Real Tk key bindings only fire for events routed to a widget that
        # actually has keyboard focus -- confirmed empirically: without
        # this, event_generate("<KeyPress>", ...) is silently dropped, even
        # though it's synthetic. There is no real user to click the window,
        # so we must force it ourselves.
        window._root.focus_force()
        state["expra_root"] = str(expra_root)
        state["project"] = params["project"]
        return {
            "executed_project_code": True,
            "project_name": project.name,
            "entity_count": len(scene.entities),
            "run_state": engine.run_state.value,
        }

    if command == "state":
        scene = engine.active_scene
        return {
            "project": state["project"],
            "run_state": engine.run_state.value,
            "selected_id": window._selected_id,
            "entity_count": len(scene.entities) if scene is not None else 0,
            "is_closing": getattr(window, "_is_closing", False),
        }

    if command == "play":
        window._act_play()
        return {"run_state": engine.run_state.value}

    if command == "pause":
        window._act_pause()
        return {"run_state": engine.run_state.value}

    if command == "resume":
        window._act_play()
        return {"run_state": engine.run_state.value}

    if command == "stop":
        window._act_stop()
        return {"run_state": engine.run_state.value}

    if command == "send_key":
        # Deliberately uses the REAL Tk event system (event_generate),
        # exercising the actual <KeyPress>/<KeyRelease> bindings a human
        # keypress would trigger (EditorWindow.__init__ binds these on
        # self._root, forwarding through the same InputMap.press()/
        # .release() + engine.signal() pipeline runtime_probe uses) --
        # NOT direct InputMap injection, per the spec's own explicit
        # instruction not to treat that as proof of editor keyboard
        # handling.
        key = params["key"]
        phase = params.get("phase", "down")
        event_type = "<KeyPress>" if phase == "down" else "<KeyRelease>"
        root.focus_force()  # defensive: focus can be lost between calls, and a dropped keyboard event is silent
        root.event_generate(event_type, keysym=key)
        root.update()
        return {"key": key, "phase": phase, "run_state": engine.run_state.value}

    if command == "select_entity":
        # _on_hierarchy_select() does an exact entity_id lookup only (no
        # name resolution -- confirmed by reading it: scene.find_entity(id),
        # not find_entity_by_name) -- resolve name-or-id first, same as
        # every other action, or a name-only selection would silently set
        # _selected_id to a nonexistent id while _present_selection()
        # renders "nothing selected".
        scene = engine.active_scene
        if scene is None:
            raise RuntimeError("no scene loaded")
        entity = _find_entity(scene, params["entity"])
        window._on_hierarchy_select(entity.entity_id)
        return {"selected_id": window._selected_id, "entity_name": entity.name}

    if command == "frame_scene":
        return {
            "available": False,
            "note": (
                "no frame/fit-view method exists on EditorWindow in this codebase "
                "version (confirmed by source search) -- nothing to call"
            ),
        }

    if command == "capture_viewport":
        # ViewportPanel._pixel_image is a real tk.PhotoImage; .write() with
        # format="png" works directly (confirmed empirically on this
        # machine's real DISPLAY -- produced a genuine, valid PNG). This
        # captures the pygame-rendered sprite/texture layer only --
        # Canvas-drawn overlays (grid, collider outlines, selection
        # markers) are vector-drawn directly on the Canvas widget and are
        # NOT included; canvas.postscript() captures those too but needs
        # an external PS->PNG conversion step this tool doesn't add as a
        # new dependency.
        image = getattr(window._viewport, "_pixel_image", None)
        if image is None:
            # Canvas fallback is a legitimate renderer state (e.g. an
            # unsupported primitive, a missing texture, or simply no scene
            # loaded yet) -- report it as structured data rather than
            # raising, so a caller can tell "renderer genuinely can't do
            # this" apart from "tool usage error". Canvas fallback must never
            # be reported as a successful pixel render.
            return {
                "available": False,
                "pixel_layer_active": False,
                "fallback_active": True,
                "reason": _pixel_fallback_reason(window._viewport),
            }
        fd, tmp_path_str = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        tmp_path = Path(tmp_path_str)
        try:
            image.write(str(tmp_path), format="png")
            png_bytes = tmp_path.read_bytes()
        finally:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        return {
            "available": True,
            "pixel_layer_active": True,
            "fallback_active": False,
            "width": image.width(),
            "height": image.height(),
            "_png_base64": base64.b64encode(png_bytes).decode("ascii"),
            "note": (
                "pygame-rendered sprite/texture layer only; Canvas-drawn overlays "
                "(grid, collider outlines, selection markers) are not included"
            ),
        }

    if command == "inspect":
        scene = engine.active_scene
        if scene is None:
            raise RuntimeError("no scene loaded")
        entity_param = params.get("entity")
        if entity_param:
            entity = _find_entity(scene, entity_param)
            return _entity_snapshot(scene, entity)
        return {"entity_count": len(scene.entities), "entity_names": [e.name for e in scene.entities]}

    if command == "inspect_render":
        scene = engine.active_scene
        if scene is None:
            raise RuntimeError("no scene loaded")
        entity = _find_entity(scene, params["entity"])
        from expra_engine.runtime.render_extractor import extract_render_frame

        frame = extract_render_frame(scene)
        items = [_render_item_to_dict(item) for item in frame.items if item.key == entity.entity_id]
        return {"entity": {"entity_id": entity.entity_id, "name": entity.name}, "render_items": items}

    if command == "performance_probe":
        # The only performance_probe action that needs a LIVE Tk widget --
        # static/headless stress (render_stress, resource_cache) lives in
        # _static_runner.py instead. Uses real Tcl introspection
        # ("image names") for the PhotoImage count, not a guess.
        iterations = max(1, int(params.get("iterations", 30)))
        canvas = window._viewport._canvas
        render_logger = logging.getLogger("expra_engine.runtime.pygame_renderer")
        editor_logger = logging.getLogger("expra_engine.ui.editor_pixel_renderer")

        # Measure BEFORE attaching our own capture handler, or "before"
        # would always include it -- an off-by-one that made every call
        # report a spurious handler leak (confirmed live: this exact bug
        # existed in _static_runner.py's render_stress too).
        items_before = len(canvas.find_all())
        images_before = len(root.tk.call("image", "names"))
        handlers_before = len(render_logger.handlers) + len(editor_logger.handlers)

        capture = _RecordCapture()
        render_logger.addHandler(capture)
        editor_logger.addHandler(capture)

        start = time.monotonic()
        for _ in range(iterations):
            window._present_all()
            root.update()
        duration = time.monotonic() - start

        render_logger.removeHandler(capture)
        editor_logger.removeHandler(capture)
        items_after = len(canvas.find_all())
        images_after = len(root.tk.call("image", "names"))
        handlers_after = len(render_logger.handlers) + len(editor_logger.handlers)

        item_growth = items_after - items_before
        image_growth = images_after - images_before
        if item_growth <= 2 and image_growth <= 2:
            verdict = "bounded"
        elif item_growth >= iterations or image_growth >= iterations:
            verdict = "growing"
        else:
            verdict = "inconclusive"

        return {
            "iterations": iterations,
            "duration_seconds": duration,
            "canvas_item_count_before": items_before,
            "canvas_item_count_after": items_after,
            "photoimage_count_before": images_before,
            "photoimage_count_after": images_after,
            "logger_handler_count_before": handlers_before,
            "logger_handler_count_after": handlers_after,
            "total_diagnostic_occurrences": len(capture.records),
            "verdict": verdict,
        }

    raise ValueError(f"unknown editor_session command: {command!r}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    try:
        from expra_engine.core.engine import Engine
        from expra_engine.ui.editor_window import EditorWindow
    except Exception as exc:  # noqa: BLE001 -- must always answer the startup handshake
        _respond(0, False, error=f"could not import editor: {type(exc).__name__}: {exc}")
        return

    try:
        engine = Engine()
        window = EditorWindow(engine)
        root = window._root
        # Forces real geometry before the first capture -- confirmed
        # necessary empirically: winfo_width()/height() return 1 until the
        # window has actually been mapped by the window manager.
        root.update()
    except Exception as exc:  # noqa: BLE001
        _respond(0, False, error=f"could not construct editor window: {type(exc).__name__}: {exc}")
        return

    _respond(0, True, {"width": root.winfo_width(), "height": root.winfo_height()})

    command_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    reader = threading.Thread(target=_reader_thread, args=(command_queue,), daemon=True)
    reader.start()

    state: dict[str, Any] = {"expra_root": None, "project": None}

    def handle(request_id: int, command: str, params: dict[str, Any]) -> None:
        if command == "wait":
            # Deferred response: schedule via root.after() rather than
            # time.sleep(), so the Tk mainloop keeps pumping (and the real
            # RuntimePreviewLoop keeps auto-ticking, matching genuine
            # real-time Play behavior) while we wait, instead of freezing
            # the whole event loop.
            duration_ms = int(params.get("duration_ms", 250))

            def _respond_after() -> None:
                _respond(request_id, True, {"waited_ms": duration_ms, "run_state": window._engine.run_state.value})

            root.after(max(0, duration_ms), _respond_after)
            return
        try:
            data = _dispatch(command, params, engine=engine, window=window, root=root, state=state)
            _respond(request_id, True, data)
        except Exception as exc:  # noqa: BLE001 -- one bad command must not crash the worker
            _respond(request_id, False, error=f"{type(exc).__name__}: {exc}")

    def poll() -> None:
        try:
            while True:
                item = command_queue.get_nowait()
                request_id = item.get("id", -1)
                command = item.get("command")
                if command == "__bad_json__":
                    _respond(request_id, False, error=f"could not parse request JSON: {item.get('raw')!r}")
                    continue
                if command in ("close", "__stdin_closed__"):
                    with contextlib.suppress(Exception):
                        window._on_close()
                    if command == "close":
                        _respond(request_id, True, {"closed": True})
                    root.quit()
                    return
                if not isinstance(command, str):
                    _respond(request_id, False, error=f"request is missing a valid 'command' field: {item!r}")
                    continue
                handle(request_id, command, item)
        except queue.Empty:
            pass
        root.after(20, poll)

    root.after(20, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
