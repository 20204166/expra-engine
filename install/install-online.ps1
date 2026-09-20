# Standalone Expra online installer. Run from any PowerShell directory:
# irm https://raw.githubusercontent.com/20204166/expra-engine/main/install/install-online.ps1 | iex
param([switch]$System)

$ErrorActionPreference = "Stop"
$base = "https://raw.githubusercontent.com/20204166/expra-engine/main/dist"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("expra-engine-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null

try {
    $sumsPath = Join-Path $tmp "SHA256SUMS"
    Invoke-WebRequest "$base/SHA256SUMS" -OutFile $sumsPath
    $line = Get-Content $sumsPath | Where-Object { $_.Trim() } | Select-Object -Last 1
    $parts = $line -split "\s+"
    if ($parts.Count -lt 2) { throw "SHA256SUMS has no wheel entry" }
    $expected = $parts[0]
    $wheel = [System.IO.Path]::GetFileName($parts[1])
    if ($wheel -notmatch "^expra_engine-(\d+\.\d+\.\d+\.\d+)-py3-none-any\.whl$") {
        throw "Unexpected wheel filename: $wheel"
    }
    $expectedVersion = $matches[1]
    $wheelPath = Join-Path $tmp $wheel
    Invoke-WebRequest "$base/$wheel" -OutFile $wheelPath
    $actual = (Get-FileHash $wheelPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected.ToLowerInvariant()) { throw "Wheel checksum mismatch" }

    function New-PythonCandidate {
        param(
            [string]$Command,
            [string[]]$Arguments = @()
        )
        [pscustomobject]@{ Command = $Command; Arguments = $Arguments }
    }

    function Invoke-Python {
        param(
            [object]$Candidate,
            [string[]]$Arguments
        )
        $invokeArgs = @($Candidate.Arguments) + @($Arguments)
        & $Candidate.Command @invokeArgs
    }

    function Test-VenvPython {
        param([object]$Py)
        Invoke-Python $Py @("-c", "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)") 2>$null
        return ($LASTEXITCODE -eq 0)
    }

    if (-not (Get-Command "py" -ErrorAction SilentlyContinue) -and
        -not (Get-Command "python" -ErrorAction SilentlyContinue)) {
        if (-not (Get-Command "winget" -ErrorAction SilentlyContinue)) {
            throw "Python is not installed and winget is unavailable. Install Python 3.12 or newer, then retry."
        }
        Write-Host "Python was not found. Installing Python 3.12 with winget..."
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { throw "winget could not install Python 3.12 (exit $LASTEXITCODE)" }
    }

    $candidates = [System.Collections.Generic.List[object]]::new()
    if (Get-Command "py" -ErrorAction SilentlyContinue) {
        $candidates.Add((New-PythonCandidate "py" @("-3")))
    }
    foreach ($name in @("python3.14", "python3.13", "python3.12", "python3", "python")) {
        if (Get-Command $name -ErrorAction SilentlyContinue) {
            $candidates.Add((New-PythonCandidate $name))
        }
    }

    $py = $null
    foreach ($candidate in $candidates) {
        Invoke-Python $candidate @("-c", "import sys; assert sys.version_info >= (3,12)") 2>$null
        if ($LASTEXITCODE -eq 0 -and -not (Test-VenvPython $candidate)) { $py = $candidate; break }
    }
    if (-not $py) { throw "No usable Python 3.12+ interpreter was found." }

    $pipArgs = @("-m", "pip", "install", "--upgrade", "--force-reinstall")
    if (-not $System) { $pipArgs += "--user" }
    $pipArgs += @("--break-system-packages", $wheelPath)
    Invoke-Python $py $pipArgs
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }

    $installed = Invoke-Python $py @("-c", "import importlib.metadata as m; print(m.version('expra-engine'))")
    if ($installed.Trim() -ne $expectedVersion) { throw "Installed version mismatch" }
    Write-Host "Installed Expra $installed. Run: expra-editor"
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
