"""The editor worker's render-item serialization must report the same
material fields as the static runner's ``render_inspect``.

Both workers serialize ``RenderItem`` objects for the MCP inspection tools;
if they diverge, ``editor_session.inspect_render`` silently reports less
material data than ``render_inspect``.  This pins the editor worker to the
full material field set (color, opacity, texture_id, tint, outline,
outline_width, blend_mode) and to a robust primitive-size conversion.
"""

from __future__ import annotations

from types import SimpleNamespace

from expra_dev_mcp import _editor_worker


def _color(r: float, g: float, b: float, a: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(red=r, green=g, blue=b, alpha=a)


def _item(**overrides: object) -> SimpleNamespace:
    material = SimpleNamespace(
        color=_color(1.0, 1.0, 1.0),
        opacity=0.5,
        texture_id="assets://tex.png",
        tint=_color(1.0, 0.0, 0.0),
        outline=_color(0.0, 0.0, 0.0),
        outline_width=2.0,
        blend_mode="normal",
    )
    primitive = SimpleNamespace(kind="rectangle", size=(4.0, 3.0), radius=None)
    transform = SimpleNamespace(position=(1.0, 2.0, 0.0), rotation=0.0, scale=(1.0, 1.0, 1.0))
    phase = SimpleNamespace(name="opaque")
    return SimpleNamespace(
        key="entity-1",
        primitive=primitive,
        material=material,
        transform=transform,
        phase=phase,
        layer=0,
        visible=True,
    )


def test_editor_worker_reports_full_material_fields() -> None:
    result = _editor_worker._render_item_to_dict(_item())

    material = result["material"]
    assert material["color"] == [1.0, 1.0, 1.0, 1.0]
    assert material["opacity"] == 0.5
    assert material["texture_id"] == "assets://tex.png"
    assert material["tint"] == [1.0, 0.0, 0.0, 1.0]
    assert material["outline"] == [0.0, 0.0, 0.0, 1.0]
    assert material["outline_width"] == 2.0
    assert material["blend_mode"] == "normal"


def test_editor_worker_serializes_primitive_size_robustly() -> None:
    result = _editor_worker._render_item_to_dict(_item())
    assert result["primitive"]["size"] == [4.0, 3.0]

    # A primitive without an iterable size must not crash the worker.
    degenerate = _item()
    degenerate.primitive = SimpleNamespace(kind="rectangle", size=None, radius=None)
    result = _editor_worker._render_item_to_dict(degenerate)
    assert result["primitive"]["size"] is None
