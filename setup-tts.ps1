param([switch]$VerifyOnly, [switch]$ModelsOnly, [string[]]$VoiceIds, [switch]$AllVoices)
$ErrorActionPreference = 'Stop'
$appDirectory = $PSScriptRoot
$pythonPath = Join-Path $appDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create the application .venv first (see README.md). No global Python packages will be installed.'
}
if (-not $VerifyOnly -and -not $ModelsOnly) {
    & $pythonPath -m pip install --disable-pip-version-check --no-cache-dir -r (Join-Path $appDirectory 'requirements-tts.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Piper package installation failed.' }
}
$manifest = Get-Content -LiteralPath (Join-Path $appDirectory 'model-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($VoiceIds) {
 foreach ($id in $VoiceIds) { if ($id -notin $manifest.voices.id) { throw "Unknown voice: $id" } }
}
$selectedVoices = @($manifest.voices | Where-Object {
 if ($VoiceIds) { $_.id -in $VoiceIds }
 elseif ($AllVoices) { $true }
 else { -not $_.optional -or (Test-Path -LiteralPath (Join-Path (Join-Path $appDirectory $_.directory) ($_.id + '.onnx'))) }
})
foreach ($voice in $selectedVoices) {
 if ($voice.directory -notmatch '^data/models/piper-(ru|en)-[a-z]+$') { throw 'Invalid model directory.' }
 $modelDirectory = Join-Path $appDirectory $voice.directory
 if (-not $VerifyOnly) { New-Item -ItemType Directory -Path $modelDirectory -Force | Out-Null }
 Write-Host "Voice: $($voice.id)"
 foreach ($entry in $voice.files) {
    # Fixed local directory and a plain filename; no arbitrary manifest output paths.
    if ($entry.name -notmatch '^[A-Za-z0-9_.-]+$') { throw 'Invalid model filename.' }
    $target = Join-Path $modelDirectory $entry.name
    $valid = (Test-Path -LiteralPath $target) -and ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $entry.sha256)
    if (-not $valid) {
        if ($VerifyOnly) { throw "Missing or invalid model file: $($entry.name)" }
        if (-not $entry.url.StartsWith('https://huggingface.co/rhasspy/piper-voices/resolve/')) { throw 'Unexpected model source.' }
        $temporary = "$target.download"
        Write-Host "Downloading $($entry.name)..."
        Invoke-WebRequest -Uri $entry.url -OutFile $temporary -TimeoutSec 300
        if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
            Remove-Item -LiteralPath $temporary -Force
            throw "SHA256 mismatch: $($entry.name)"
        }
        Move-Item -LiteralPath $temporary -Destination $target -Force
    }
    Write-Host "Verified: $($entry.name)"
 }
}
@'
from importlib.metadata import version
from piper import PiperVoice
print("Piper " + version("piper-tts") + " is ready. Audio is generated locally when requested.")
'@ | & $pythonPath -
if ($LASTEXITCODE -ne 0) { throw 'Piper import failed.' }
