#!/usr/bin/env python3
"""Experimental A/B bench for the Tk pixel-bridge candidates.

Not part of production code -- compares the current PNG-level-1 bridge
against Pillow/ImageTk and a couple of low-copy variants, on real project
scenes, to decide whether any candidate is worth adopting. See
"EXPRA -- FINAL TK PIXEL-BRIDGE PERFORMANCE PASS".

Usage:
    .venv/bin/python tools/perf/bench_pixel_bridge_candidates.py --project examples/space_pong
"""

from __future__ import annotations

import argparse
import os
import statistics
import time
import tkinter as tk
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(REPO_ROOT / "src"))


def _stats(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    n = len(ordered)

    def pct(f: float) -> float:
        if n == 1:
            return ordered[0]
        pos = (n - 1) * f
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)

    return {
        "mean_ms": statistics.mean(ordered) * 1000,
        "p50_ms": pct(0.5) * 1000,
        "p95_ms": pct(0.95) * 1000,
        "max_ms": ordered[-1] * 1000,
    }


def run(project: str, width: int, height: int, iterations: int) -> None:
    from expra_engine.core.project import Project
    from expra_engine.runtime.render_extractor import extract_render_frame
    from expra_engine.ui.editor_pixel_renderer import (
        EditorPixelRenderer,
        editor_render_context,
        encode_pygame_surface_fast,
    )
    from expra_engine.ui.viewport_camera import ViewportCamera

    project_path = (REPO_ROOT / project).resolve()
    proj = Project.load(project_path)
    scene = proj.load_scene(None)
    resource_service = proj.resource_service()
    frame = extract_render_frame(scene)

    root = tk.Tk()
    root.withdraw()
    try:
        import pygame

        camera = ViewportCamera((width, height))
        context = editor_render_context(camera, width, height)

        from expra_engine.runtime.pygame_renderer import PygameRenderer, PygameResourceProvider

        provider = PygameResourceProvider(pygame, resource_service)

        def make_surface() -> "pygame.Surface":
            surface = pygame.Surface((width, height), flags=pygame.SRCALPHA)
            renderer = PygameRenderer(
                pygame,
                surface,
                screen_size=(width, height),
                arena_bounds=(0, 0, width, height),
                resource_provider=provider,
                clear_color=None,
            )
            renderer.start(context)
            renderer.render(frame)
            return surface

        # warm up
        for _ in range(10):
            make_surface()

        print(f"\n=== {project} @ {width}x{height}, {iterations} iters ===")

        # --- candidate A: current PNG level-1 + persistent PhotoImage.configure ---
        render_s, extract_s, encode_s, upload_s, total_s = [], [], [], [], []
        photo = None
        for _ in range(iterations):
            t0 = time.perf_counter()
            surface = make_surface()
            t1 = time.perf_counter()
            rgba = pygame.image.tostring(surface, "RGBA")
            t2 = time.perf_counter()
            # encode_pygame_surface_fast redoes tostring internally; reuse its
            # PNG-build math directly on rgba we already extracted, to split
            # extract vs encode honestly.
            import struct
            import zlib

            stride = width * 4
            raw = bytearray()
            for y in range(height):
                raw.append(0)
                raw += rgba[y * stride : (y + 1) * stride]
            compressed = zlib.compress(bytes(raw), level=1)
            ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

            def chunk(tag: bytes, data: bytes) -> bytes:
                return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
            t3 = time.perf_counter()
            if photo is None:
                photo = tk.PhotoImage(master=root, data=png, format="png")
            else:
                photo.configure(data=png, format="png")
            t4 = time.perf_counter()
            render_s.append(t1 - t0)
            extract_s.append(t2 - t1)
            encode_s.append(t3 - t2)
            upload_s.append(t4 - t3)
            total_s.append(t4 - t0)
        print("A: current PNG-level1 + PhotoImage.configure")
        for name, s in [("render", render_s), ("extract", extract_s), ("encode", encode_s), ("upload", upload_s), ("total", total_s)]:
            st = _stats(s)
            print(f"   {name:8s} mean={st['mean_ms']:.3f}ms p50={st['p50_ms']:.3f}ms p95={st['p95_ms']:.3f}ms max={st['max_ms']:.3f}ms")

        # --- candidate B: Pillow frombuffer -> new ImageTk.PhotoImage every frame ---
        try:
            from PIL import Image, ImageTk

            render_s, extract_s, wrap_s, upload_s, total_s = [], [], [], [], []
            for _ in range(iterations):
                t0 = time.perf_counter()
                surface = make_surface()
                t1 = time.perf_counter()
                rgba = pygame.image.tostring(surface, "RGBA")
                t2 = time.perf_counter()
                img = Image.frombuffer("RGBA", (width, height), rgba, "raw", "RGBA", 0, 1)
                t3 = time.perf_counter()
                tkimg = ImageTk.PhotoImage(img, master=root)
                t4 = time.perf_counter()
                render_s.append(t1 - t0)
                extract_s.append(t2 - t1)
                wrap_s.append(t3 - t2)
                upload_s.append(t4 - t3)
                total_s.append(t4 - t0)
            print("B: Pillow frombuffer + new ImageTk.PhotoImage/frame")
            for name, s in [("render", render_s), ("extract", extract_s), ("wrap", wrap_s), ("upload", upload_s), ("total", total_s)]:
                st = _stats(s)
                print(f"   {name:8s} mean={st['mean_ms']:.3f}ms p50={st['p50_ms']:.3f}ms p95={st['p95_ms']:.3f}ms max={st['max_ms']:.3f}ms")

            # --- candidate C: Pillow frombuffer -> persistent ImageTk.PhotoImage.paste() ---
            render_s, extract_s, wrap_s, upload_s, total_s = [], [], [], [], []
            persistent_tkimg = ImageTk.PhotoImage(Image.new("RGBA", (width, height)), master=root)
            for _ in range(iterations):
                t0 = time.perf_counter()
                surface = make_surface()
                t1 = time.perf_counter()
                rgba = pygame.image.tostring(surface, "RGBA")
                t2 = time.perf_counter()
                img = Image.frombuffer("RGBA", (width, height), rgba, "raw", "RGBA", 0, 1)
                t3 = time.perf_counter()
                persistent_tkimg.paste(img)
                t4 = time.perf_counter()
                render_s.append(t1 - t0)
                extract_s.append(t2 - t1)
                wrap_s.append(t3 - t2)
                upload_s.append(t4 - t3)
                total_s.append(t4 - t0)
            print("C: Pillow frombuffer + persistent ImageTk.PhotoImage.paste()")
            for name, s in [("render", render_s), ("extract", extract_s), ("wrap", wrap_s), ("upload", upload_s), ("total", total_s)]:
                st = _stats(s)
                print(f"   {name:8s} mean={st['mean_ms']:.3f}ms p50={st['p50_ms']:.3f}ms p95={st['p95_ms']:.3f}ms max={st['max_ms']:.3f}ms")
        except ImportError:
            print("Pillow not installed -- skipping candidates B/C")

        # --- candidate D: get_view('2') zero-copy-ish extraction, still PNG path ---
        render_s, extract_s, total_s = [], [], []
        for _ in range(iterations):
            t0 = time.perf_counter()
            surface = make_surface()
            t1 = time.perf_counter()
            view = surface.get_view("2")
            rgba = bytes(view)  # type: ignore[arg-type]  # pygame stubs omit BufferProxy's buffer protocol
            t2 = time.perf_counter()
            render_s.append(t1 - t0)
            extract_s.append(t2 - t1)
            total_s.append(t2 - t0)
        print("D: surface.get_view('2') extraction only (vs tostring)")
        for name, s in [("render", render_s), ("extract(view+bytes)", extract_s), ("total", total_s)]:
            st = _stats(s)
            print(f"   {name:20s} mean={st['mean_ms']:.3f}ms p50={st['p50_ms']:.3f}ms p95={st['p95_ms']:.3f}ms max={st['max_ms']:.3f}ms")

        # compare straight tostring cost alone for reference
        extract_only = []
        for _ in range(iterations):
            surface = make_surface()
            t0 = time.perf_counter()
            pygame.image.tostring(surface, "RGBA")
            t1 = time.perf_counter()
            extract_only.append(t1 - t0)
        st = _stats(extract_only)
        print(f"   tostring-only extract: mean={st['mean_ms']:.3f}ms p50={st['p50_ms']:.3f}ms p95={st['p95_ms']:.3f}ms")

    finally:
        root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="examples/space_pong")
    parser.add_argument("--iterations", type=int, default=120)
    args = parser.parse_args()

    for w, h in [(800, 600), (1280, 720)]:
        run(args.project, w, h, args.iterations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
