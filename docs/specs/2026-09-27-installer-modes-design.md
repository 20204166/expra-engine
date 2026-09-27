# Expra Installer Modes Design

## Context

The local wheel installer and online installer currently use different default
install strategies. The local installer writes to the Python user site and
passes `--break-system-packages`; the online installer creates a managed
per-user environment, but its `--system` path does not handle PEP 668. This
causes confusing outcomes on externally-managed distributions and can leave an
older `expra-editor` earlier on `PATH`.

## Goals

- Make the local-wheel and online installers share consistent install behavior.
- Make the default install safe for externally-managed system Python.
- Keep `expra-editor` available from the user's normal `PATH` after a user
  install.
- Make `--system` an explicit elevated machine-wide install that handles PEP
  668 deliberately.
- Verify the installed package version matches the selected, verified wheel.
- Preserve unrelated launchers and fail clearly on an unmanaged command-name
  conflict.

## Install Modes

### Normal user install

Install into a version-specific managed per-user virtual environment under
`~/.local/share/expra-engine/versions/<version>`. A `current` pointer selects
the active verified environment, and a stable user launcher at
`~/.local/bin/expra-editor` invokes it. Switch the pointer atomically only
after installation and version verification. The launcher update may replace
an existing Expra-generated launcher, but must not silently overwrite an
unrelated executable. This mode does not pass `--break-system-packages` to pip.

### `--system`

Use a system Python outside a virtual environment, require `sudo`, and install
into the system prefix. Because this mode explicitly requests a system-wide
pip install, pass `--break-system-packages` where required by PEP 668. Verify
the installed distribution version and print the system launcher path. If a
per-user `expra-editor` shadows the system launcher, report that fact.

## Installer Flow

- `scripts/install-user.sh` selects the requested local wheel and passes it to
  a shared wheel installer.
- `scripts/install-online.sh` downloads the wheel named in `SHA256SUMS`,
  verifies the SHA-256 digest, then passes the verified wheel to the same
  installer.
- The shared installer owns mode validation, environment creation, pip
  invocation, launcher management, and installed-version verification.
- Existing version selection and `EXPRA_SYSTEM_PYTHON` support remain
  available.

## Failure Handling

- Reject Python interpreters inside virtual environments for `--system`.
- Fail before installation if `sudo`, a supported Python, venv support, or a
  verified wheel is unavailable.
- Keep the previous environment active until the new environment and launcher
  are verified; preserve the prior user launcher on failure.
- Print the exact launcher path and an actionable PATH hint when needed.

## Validation

- Unit-level checks cover local wheel selection, online checksum gating, mode
  argument propagation, PEP 668 flags, user launcher conflict handling, and
  installed-version mismatch handling without modifying the host environment.
- Shell syntax checks cover each installer entry point.
- Existing wheel verification remains the authority for package contents and
  metadata.
- No package is installed into the active development environment as part of
  tests.
