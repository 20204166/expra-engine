"""Tests for renderer-neutral sprite and animation contracts."""

import unittest
from dataclasses import FrozenInstanceError
from math import inf, nan

from expra_engine.runtime.animation import (
    AnimationClip,
    AnimationFrame,
    Animator,
    SpriteMetadata,
    SpriteRegion,
    SpriteSheet,
)


class TestSpriteMetadata(unittest.TestCase):
    def test_preserves_texture_identity_scale_and_aspect_policy(self) -> None:
        texture = object()
        metadata = SpriteMetadata(texture, pixels_per_unit=32.0, preserve_aspect=False)

        self.assertIs(metadata.texture, texture)
        self.assertEqual(metadata.pixels_per_unit, 32.0)
        self.assertFalse(metadata.preserve_aspect)

    def test_metadata_is_immutable_and_scale_is_positive(self) -> None:
        metadata = SpriteMetadata("hero")

        with self.assertRaises(FrozenInstanceError):
            metadata.texture = "other"  # type: ignore[misc]
        for value in (0.0, -1.0, inf, nan):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SpriteMetadata("hero", pixels_per_unit=value)


class TestSpriteSheetAndClips(unittest.TestCase):
    def test_sprite_regions_require_integer_pixel_coordinates(self) -> None:
        with self.assertRaises(ValueError):
            SpriteRegion(1.5, 0, 8, 8)  # type: ignore[arg-type]

    def test_sprite_sheet_returns_renderer_neutral_tile_region(self) -> None:
        sheet = SpriteSheet("atlas", tile_width=16, tile_height=24, columns=3, rows=2)

        self.assertEqual(sheet.region(2, 1), SpriteRegion(32, 24, 16, 24))

    def test_sprite_sheet_rejects_invalid_dimensions_and_coordinates(self) -> None:
        with self.assertRaises(ValueError):
            SpriteSheet("atlas", tile_width=0, tile_height=16, columns=3, rows=2)
        sheet = SpriteSheet("atlas", tile_width=16, tile_height=16, columns=3, rows=2)
        for column, row in ((-1, 0), (3, 0), (0, -1), (0, 2)):
            with self.subTest(column=column, row=row), self.assertRaises(ValueError):
                sheet.region(column, row)

    def test_frames_require_positive_finite_durations_and_are_immutable(self) -> None:
        region = SpriteRegion(0, 0, 16, 16)
        for duration in (0.0, -0.1, inf, nan):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                AnimationFrame(region, duration)

        frame = AnimationFrame(region, 0.1)
        with self.assertRaises(FrozenInstanceError):
            frame.duration = 0.2  # type: ignore[misc]

    def test_clip_copies_frames_and_rejects_empty_clips(self) -> None:
        frames = [AnimationFrame(SpriteRegion(0, 0, 8, 8), 0.1)]
        clip = AnimationClip(frames)
        frames.append(AnimationFrame(SpriteRegion(8, 0, 8, 8), 0.1))

        self.assertEqual(len(clip.frames), 1)
        self.assertIsInstance(clip.frames, tuple)
        with self.assertRaises(ValueError):
            AnimationClip(())


class TestAnimator(unittest.TestCase):
    def setUp(self) -> None:
        self.frame_a = AnimationFrame(SpriteRegion(0, 0, 8, 8), 0.1)
        self.frame_b = AnimationFrame(SpriteRegion(8, 0, 8, 8), 0.2)
        self.idle = AnimationClip((self.frame_a,), loop=True)
        self.walk = AnimationClip((self.frame_a, self.frame_b), loop=True)

    def test_looping_advances_frames_and_wraps(self) -> None:
        animator = Animator({"idle": self.idle, "walk": self.walk})
        animator.play("walk")

        animator.update(0.15)
        self.assertIs(animator.current_frame, self.frame_b)
        animator.update(0.2)
        self.assertIs(animator.current_frame, self.frame_a)

    def test_play_pause_and_resume_control_advancement(self) -> None:
        animator = Animator({"walk": self.walk})
        animator.play("walk")
        animator.update(0.1)
        animator.pause()
        animator.update(0.2)
        self.assertIs(animator.current_frame, self.frame_b)
        animator.resume()
        animator.update(0.2)
        self.assertIs(animator.current_frame, self.frame_a)

    def test_named_state_transitions_validate_state_and_clip(self) -> None:
        animator = Animator({"idle": self.idle}, states={"default": "idle"})

        animator.set_state("default")
        self.assertEqual(animator.state, "default")
        self.assertIs(animator.current_clip, self.idle)
        with self.assertRaises(KeyError):
            animator.set_state("missing-state")
        with self.assertRaises(KeyError):
            Animator({}, states={"broken": "missing-clip"}).set_state("broken")

    def test_animator_rejects_invalid_deltas(self) -> None:
        animator = Animator({"idle": self.idle})
        for delta in (-0.1, inf, nan):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                animator.update(delta)


if __name__ == "__main__":
    unittest.main()
