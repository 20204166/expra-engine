"""Tests for the audio system data contracts (no playback backend)."""

import unittest

from expra_engine.runtime.audio import AudioBus, AudioClip, AudioMixer


class AudioBusTests(unittest.TestCase):
    def test_default_volume_is_1(self) -> None:
        bus = AudioBus("sfx")
        self.assertEqual(bus.volume, 1.0)
        self.assertEqual(bus.effective_volume, 1.0)

    def test_muted_bus_effective_volume_is_zero(self) -> None:
        bus = AudioBus("music", volume=0.8, muted=True)
        self.assertEqual(bus.effective_volume, 0.0)

    def test_unmute_restores_volume(self) -> None:
        bus = AudioBus("sfx", volume=0.6, muted=True)
        bus.muted = False
        self.assertAlmostEqual(bus.effective_volume, 0.6)

    def test_volume_clamped(self) -> None:
        bus = AudioBus("sfx")
        bus.set_volume(2.5)
        self.assertEqual(bus.volume, 1.0)
        bus.set_volume(-1.0)
        self.assertEqual(bus.volume, 0.0)

    def test_unknown_bus_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AudioBus("engine_room")

    def test_all_known_buses_accepted(self) -> None:
        for name in ("master", "music", "sfx", "ambience", "dialogue", "ui"):
            AudioBus(name)  # must not raise


class AudioClipTests(unittest.TestCase):
    def test_basic_clip(self) -> None:
        clip = AudioClip("sounds/hit.wav", bus="sfx", volume=0.8)
        self.assertEqual(clip.asset_id, "sounds/hit.wav")

    def test_empty_asset_id_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AudioClip("")

    def test_unknown_bus_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AudioClip("x.wav", bus="unknown")

    def test_pan_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AudioClip("x.wav", pan=2.0)

    def test_zero_pitch_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AudioClip("x.wav", pitch=0.0)

    def test_effective_volume_is_master_times_bus_times_clip(self) -> None:
        mixer = AudioMixer()
        mixer.bus("master").set_volume(0.5)
        mixer.bus("sfx").set_volume(0.8)
        clip = AudioClip("x.wav", bus="sfx", volume=0.5)
        self.assertAlmostEqual(clip.effective_volume(mixer), 0.5 * 0.8 * 0.5)

    def test_muted_bus_zeroes_effective_volume(self) -> None:
        mixer = AudioMixer()
        mixer.bus("music").muted = True
        clip = AudioClip("x.wav", bus="music", volume=1.0)
        self.assertEqual(clip.effective_volume(mixer), 0.0)


class AudioMixerTests(unittest.TestCase):
    def test_all_buses_created_by_default(self) -> None:
        mixer = AudioMixer()
        for name in ("master", "music", "sfx", "ambience", "dialogue", "ui"):
            self.assertIn(name, mixer.buses)

    def test_muting_master_zeros_all(self) -> None:
        mixer = AudioMixer()
        mixer.bus("master").muted = True
        clip = AudioClip("x.wav", bus="sfx")
        self.assertEqual(clip.effective_volume(mixer), 0.0)

    def test_unknown_bus_raises_key_error(self) -> None:
        mixer = AudioMixer()
        with self.assertRaises(KeyError):
            mixer.bus("nonexistent")


if __name__ == "__main__":
    unittest.main()
