param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Run-Checked([scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" }
}
Push-Location frontend
try {
    Run-Checked { npm.cmd ci }
    Run-Checked { npm.cmd run check }
    if (-not $SkipTests) { Run-Checked { node --test tests/*.test.cjs } }
    Run-Checked { npm.cmd run build }
} finally { Pop-Location }
# Avoid embedding the build machine's home or checkout path in Rust diagnostics.
$env:RUSTFLAGS = "--remap-path-prefix=$((Get-Location).Path)=."
if ($env:CARGO_HOME) { $env:RUSTFLAGS += " --remap-path-prefix=$env:CARGO_HOME=cargo" }
Run-Checked { cargo build --release --locked --manifest-path src-tauri/Cargo.toml }
$arguments = @('scripts/build_windows.py')
if ($SkipTests) { $arguments += '--skip-tests' }
Run-Checked { python @arguments }
