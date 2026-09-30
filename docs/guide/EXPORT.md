# Export

The exporter bundles a project into a standalone build with no editor UI
toolkit or editor runtime.

## CLI

```bash
python -m expra_engine.export.cli <project> \
  --target linux \
  --output ./builds \
  --game-name MyGame \
  --game-version 1.0.0 \
  --python-version 3.12.4 \
  --arch amd64 \
  --runtime-profile pygame \
  --entry-point __main__.py \
  [--no-bytecode] [--no-debug-launcher]
```

Console scripts: `expra-editor`, `expra-export`, `expra-new`.

| Argument | Default | Notes |
|---|---|---|
| `project` | — (required) | project directory |
| `--target` | — (required) | `windows` \| `linux` |
| `--output` | `<project>/builds` | |
| `--game-name` | project dir name | |
| `--game-version` | `project.game_version` or `1.0.0` | |
| `--python-version` | `3.12.4` | |
| `--arch` | `amd64` | `amd64` \| `arm64` |
| `--runtime-profile` | `none` | `pygame` \| `none` |
| `--entry-point` | `project.entry_point` or `__main__.py` | |
| `--no-bytecode` | false | skip `.pyc` compilation |
| `--no-debug-launcher` | false | skip debug launcher |

## Pipeline

`GameExporter.export()` runs an **atomic** build: stage in a temp dir → verify →
promote. Failure never disturbs a previous export.

| Stage | Phase |
|---|---|
| Prepare plan + normal-map discovery | `PLANNING` |
| Collect assets (manifest + closure) | `COLLECTING_ASSETS` |
| Compile bytecode (`.py` → `.pyc`, then delete sources) | `COMPILING_BYTECODE` |
| Install Python runtime | `COPYING_RUNTIME` |
| Resolve deps (pygame + optional numpy) | `RESOLVING_DEPS` |
| Write manifests | `WRITING_MANIFESTS` |
| Verify | `VERIFYING` |
| Promote (atomic) | `PROMOTING` |

## Runtime profiles

- **`pygame`** — stages `expra_engine` runtime modules into site-packages,
  installs `pygame>=2.6` (+ `numpy>=2.0,<3` if normal mapping is used), and
  discovers normal-map resources.
- **`none`** — bare Python runtime; no engine modules staged.

## Resource closure

`AssetManifest.collect()` resolves transitive dependencies per asset, dedupes by
SHA-256. World projects traverse World → Level → Scene → resources. Normal-map
auto-pairs are resolved and added; a missing explicit normal map fails the
export, a missing auto-pair warns and falls back to flat lighting.

## Verification

`verify_export()` checks build presence, `build_manifest.json` keys, asset
manifest integrity, and runs a **forbidden-import scan** (AST for `.py`,
`marshal`+`dis` for `.pyc`). Forbidden imports: `tkinter`, `ttkbootstrap`,
`expra_engine.editor`, `expra_engine.ui`, `expra_engine.design`, `ursina`,
`panda3d`.

## Build layout

```
<output>/<game>_<target>/
  <game>/                    # game source (.pyc or .py)
  runtime/                   # venv (linux) or embedded python (windows)
  asset_manifest.json
  runtime_manifest.json
  build_manifest.json
  <game>.sh | .bat
  <game>_debug.sh | .bat     # redirects to log.txt, returns status
```

## Headless smoke validation

Set `EXPRA_SMOKE_FRAMES` + `EXPRA_SMOKE_REPORT` and run the debug launcher to
confirm the bundled runtime started and rendered N frames.
