# Expra Installer Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local-wheel and online installers share one consistent install path: a version-specific per-user venv with an atomic launcher by default, and an explicit elevated `--system` mode that handles PEP 668.

**Architecture:** A new shared `scripts/install-common.sh` owns mode validation, environment creation, pip invocation, launcher management, and installed-version verification. `scripts/install-user.sh` and `scripts/install-online.sh` keep their existing entry-point responsibilities (local wheel selection / online download + checksum verification) and delegate to the shared installer.

**Tech Stack:** Bash 5, Python 3.12, pip, venv.

---

## File Structure

- Modify: `scripts/install-user.sh` — local wheel selection + delegate to shared installer.
- Modify: `scripts/install-online.sh` — online download + checksum verification + delegate to shared installer.
- Create: `scripts/install-common.sh` — shared wheel installer (mode validation, venv, pip, launcher, version check).
- Modify: `tests/test_install_scripts.py` — extend with new boundary assertions.
- Modify: `README.md` — update install instructions.
- Modify: `docs/ARCHITECTURE.md` — reflect the shared installer owner.

---

### Task 1: Shared installer skeleton and mode validation

**Files:**
- Create: `scripts/install-common.sh`
- Test: `tests/test_install_scripts.py`

- [ ] **Step 1: Write the failing test**

Edit `tests/test_install_scripts.py` to add a source-level assertion that the shared installer never installs into the active checkout venv and validates modes.

```python
INSTALL_COMMON = Path(__file__).parents[1] / "scripts" / "install-common.sh"


def test_install_common_never_targets_the_checkout_venv() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert "here/.venv/bin/python" not in script
    assert 'sys.prefix != sys.base_prefix' in script
    assert "--break-system-packages" in script


def test_install_common_accepts_system_mode() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert '--system' in script
    assert 'sudo' in script
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: FAIL with "No such file or directory" for `scripts/install-common.sh`.

- [ ] **Step 3: Write the shared installer skeleton**

Create `scripts/install-common.sh` with argument parsing, mode validation, and the interpreter guard.

```bash
#!/usr/bin/env bash
# Shared wheel installer: per-user venv by default, elevated system install with --system.
set -euo pipefail

install_wheel() {
    local wheel="$1"
    local mode="${2:-user}"

    [[ "$mode" == "user" || "$mode" == "system" ]] || {
        echo "ERROR: unsupported install mode: $mode" >&2
        return 1
    }

    if [[ -n "${EXPRA_SYSTEM_PYTHON:-}" ]]; then
        py="$EXPRA_SYSTEM_PYTHON"
    elif command -v python3 >/dev/null 2>&1; then
        py="$(command -v python3)"
    else
        echo "ERROR: no Python 3 interpreter found; set EXPRA_SYSTEM_PYTHON." >&2
        return 1
    fi

    if "$py" -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' \
        >/dev/null 2>&1 && [[ "$mode" == "system" ]]; then
        echo "ERROR: --system requires a Python outside a virtual environment: $py" >&2
        return 1
    fi

    echo "shared installer: mode=$mode wheel=$wheel py=$py"
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: PASS (source-level assertions hold).

- [ ] **Step 5: Commit**

```bash
git add scripts/install-common.sh tests/test_install_scripts.py
git commit -m "feat: add shared installer skeleton with mode validation"
```

---

### Task 2: Per-user venv install path

**Files:**
- Modify: `scripts/install-common.sh`
- Test: `tests/test_install_scripts.py`

- [ ] **Step 1: Write the failing test**

Edit `tests/test_install_scripts.py` to assert the user-mode layout constants.

```python
def test_install_common_user_mode_uses_version_specific_venv() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert 'versions' in script
    assert 'current' in script
    assert 'venv' in script
    assert '$HOME/.local/share/expra-engine' in script
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: FAIL because those paths are not yet present.

- [ ] **Step 3: Implement the per-user venv install path**

Edit `scripts/install-common.sh` to add the user-mode branch.

```bash
    if [[ "$mode" == "user" ]]; then
        local root="${EXPRA_ENGINE_INSTALL_ROOT:-$HOME/.local/share/expra-engine}"
        local version_dir="$root/versions/$expected_version"
        if [[ ! -x "$version_dir/bin/python" ]]; then
            "$py" -m venv "$version_dir"
        fi
        env -u PYTHONPATH "$version_dir/bin/python" -m pip install \
            --upgrade --upgrade-strategy eager "$wheel"
        printf '%s\n' "$version_dir" >"$root/current"
        py="$version_dir/bin/python"
        bin_dir="$version_dir/bin"
    fi
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-common.sh tests/test_install_scripts.py
git commit -m "feat: install per-user venv in shared installer"
```

---

### Task 3: System install path

**Files:**
- Modify: `scripts/install-common.sh`
- Test: `tests/test_install_scripts.py`

- [ ] **Step 1: Write the failing test**

Edit `tests/test_install_scripts.py` to assert the system-mode install flags.

```python
def test_install_common_system_mode_uses_elevated_pip_with_pep668() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert 'sudo -H' in script
    assert '--break-system-packages' in script
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: FAIL because the elevated pip branch is missing.

- [ ] **Step 3: Implement the system install path**

Edit `scripts/install-common.sh` to add the system-mode branch.

```bash
    else
        command -v sudo >/dev/null 2>&1 || {
            echo "ERROR: sudo is required for --system" >&2
            return 1
        }
        sudo -H env -u PYTHONPATH "$py" -m pip install \
            --upgrade --upgrade-strategy eager --break-system-packages "$wheel"
        bin_dir="$("$py" -c 'import sysconfig; print(sysconfig.get_path("scripts", scheme="posix_prefix"))')"
    fi
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-common.sh tests/test_install_scripts.py
git commit -m "feat: add elevated system install path to shared installer"
```

---

### Task 4: Installed-version verification

**Files:**
- Modify: `scripts/install-common.sh`
- Test: `tests/test_install_scripts.py`

- [ ] **Step 1: Write the failing test**

Edit `tests/test_install_scripts.py` to assert version verification.

```python
def test_install_common_verifies_installed_version() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert 'importlib.metadata' in script
    assert 'installed' in script
    assert 'expected_version' in script
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: FAIL because version verification is absent.

- [ ] **Step 3: Implement version verification**

Edit `scripts/install-common.sh` to add verification after the install branches.

```bash
    local installed_version
    installed_version="$("$py" -c 'import importlib.metadata as m; print(m.version("expra-engine"))')"
    [[ "$installed_version" == "$expected_version" ]] || {
        echo "ERROR: installed $installed_version, expected $expected_version" >&2
        return 1
    }
    echo "Installed Expra $installed_version. Launcher: $bin_dir/expra-editor"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-common.sh tests/test_install_scripts.py
git commit -m "feat: verify installed version in shared installer"
```

---

### Task 5: User launcher management

**Files:**
- Modify: `scripts/install-common.sh`
- Test: `tests/test_install_scripts.py`

- [ ] **Step 1: Write the failing test**

Edit `tests/test_install_scripts.py` to assert launcher conflict handling.

```python
def test_install_common_installs_user_launcher_atomically() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert '$HOME/.local/bin/expra-editor' in script
    assert 'mktemp' in script
    assert 'mv' in script


def test_install_common_does_not_overwrite_unmanaged_launcher() -> None:
    script = INSTALL_COMMON.read_text(encoding="utf-8")

    assert 'unrelated' in script or 'not overwrit' in script
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: FAIL because launcher management is absent.

- [ ] **Step 3: Implement launcher management**

Edit `scripts/install-common.sh` to add the user launcher creation.

```bash
    if [[ "$mode" == "user" ]]; then
        local launcher_dir="${EXPRA_ENGINE_BIN_DIR:-$HOME/.local/bin}"
        mkdir -p "$launcher_dir"
        local launcher="$launcher_dir/expra-editor"
        if [[ -e "$launcher" && ! -L "$launcher" ]]; then
            echo "WARNING: not overwriting existing executable $launcher" >&2
        else
            local tmp_launcher
            tmp_launcher="$(mktemp "$launcher.XXXXXX")"
            printf '#!/usr/bin/env bash\nexec "%s/expra-editor" "$@"\n' "$bin_dir" >"$tmp_launcher"
            chmod +x "$tmp_launcher"
            mv -f "$tmp_launcher" "$launcher"
        fi
    fi
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-common.sh tests/test_install_scripts.py
git commit -m "feat: manage user launcher in shared installer"
```

---

### Task 6: Wire entry points to the shared installer

**Files:**
- Modify: `scripts/install-user.sh`
- Modify: `scripts/install-online.sh`

- [ ] **Step 1: Rewrite the install-user tail**

Replace the `pip_install` block and following lines in `scripts/install-user.sh` so local selection delegates to the shared installer.

```bash
echo "Verifying wheel: $(basename "$wheel")"
PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}" "$py" -m expra_engine._release verify-wheel "$wheel"

source "$here/scripts/install-common.sh"
install_wheel "$wheel" "$mode"
```

- [ ] **Step 2: Rewrite the install-online install tail**

Replace the mode dispatch and version check in `scripts/install-online.sh` to delegate to the shared installer.

```bash
source "$here/scripts/install-common.sh"
install_wheel "$wheel" "$mode"
```

- [ ] **Step 3: Run shell syntax checks**

Run: `bash -n scripts/install-user.sh scripts/install-online.sh scripts/install-common.sh`
Expected: exit 0, no output.

- [ ] **Step 4: Run the existing install-script test**

Run: `.venv/bin/python -m pytest tests/test_install_scripts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-user.sh scripts/install-online.sh scripts/install-common.sh tests/test_install_scripts.py
git commit -m "feat: route installers through shared wheel installer"
```

---

### Task 7: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update README install section**

Replace the `./scripts/install-user.sh` explanation with the per-user venv default and the `--system` semantics.

```markdown
Install the latest built wheel outside the repository virtual environment:

./scripts/install-user.sh
```

- [ ] **Step 2: Update ARCHITECTURE install description**

Reflect the shared installer owner in `docs/ARCHITECTURE.md`.

- [ ] **Step 3: Run diff check**

Run: `git diff --check`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: document shared installer modes"
```

---

## Self-Review

- Spec coverage: goals map to Tasks 1-6 (shared flow, per-user venv, `--system`, version verification, launcher preservation, failure handling); docs to Task 7.
- Placeholder scan: no TODO/TBD markers remain.
- Type consistency: `install_wheel` signature and `$mode` values are consistent across Tasks 1-6.
