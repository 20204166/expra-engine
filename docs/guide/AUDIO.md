# Audio

Audio is renderer-neutral at the contract level. The 2D spatial layer is
`Audio2DWorld` / `Audio2DSystem`.

## Components

- `AudioListener2DComponent` (`audio_listener_2d`) — the spatial listener.
  `current=False`; the first enabled `current=True` listener in scene order wins.
- `AudioStreamPlayer2DComponent` (`audio_stream_player_2d`) — a spatial source.

## Stream player fields

`asset_id`, `volume_db=0.0`, `pitch_scale=1.0`, `autoplay=False`,
`stream_paused=False`, `max_distance=2000.0`, `attenuation=1.0`,
`max_polyphony=1`, `panning_strength=1.0`, `bus="sfx"`
(`master|music|sfx|ambience|dialogue|ui`), `area_mask=0`,
`playback_type="default"` (`default|stream|sample`). `volume_linear` converts dB.

## Buses and mixing

`AudioBus` / `AudioMixer` (`runtime/audio.py`) define buses and mixing.
`Audio2DWorld.mix_for(…)` does spatial mixing against the current listener.

## Notes

- This is a contract/state layer; actual sample playback depends on the backend
  the runtime attaches.
- Volume/pitch/attenuation are validated; `max_polyphony >= 1`.
