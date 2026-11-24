param(
    [string]$PackageDir = '',
    [string]$OutputDir = '',
    [string]$Compiler = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (!$PackageDir) { $PackageDir = Join-Path $root 'build/Pereplet-Tauri-Windows-x64' }
if (!$OutputDir) { $OutputDir = Join-Path $root 'dist' }
$PackageDir = (Resolve-Path -LiteralPath $PackageDir).Path
New-Item -ItemType Directory -Force $OutputDir | Out-Null
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path
# Refuse personal state, and require every packaged file to match the portable manifest.
python "$PSScriptRoot/verify_package.py" $PackageDir
if ($LASTEXITCODE -ne 0) { throw 'Package hygiene check failed' }
$hashes = Get-Content -Raw -LiteralPath (Join-Path $PackageDir 'SHA256SUMS.json') | ConvertFrom-Json -AsHashtable
foreach ($name in $hashes.Keys) {
    $file = Join-Path $PackageDir $name
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $hashes[$name]) { throw "Package checksum mismatch: $name" }
}
if (!$Compiler) {
    $tools = Join-Path $root 'build/inno-tools'
    New-Item -ItemType Directory -Force $tools | Out-Null
    $setup = Join-Path $tools 'innosetup-6.7.4.exe'
    $expected = 'a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c'
    if (!(Test-Path $setup)) { Invoke-WebRequest 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe' -OutFile $setup }
    if ((Get-FileHash $setup -Algorithm SHA256).Hash -ne $expected) { throw 'Inno Setup SHA-256 mismatch' }
    $toolDir = Join-Path $tools 'compiler'
    $process = Start-Process -FilePath $setup -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER','/NOICONS','/TASKS=',('/DIR="'+$toolDir+'"')) -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Inno Setup tool installation failed: $($process.ExitCode)" }
    $Compiler = Join-Path $toolDir 'ISCC.exe'
}
$version = (Get-Content -Raw (Join-Path $root 'src-tauri/tauri.conf.json') | ConvertFrom-Json).version
& $Compiler '/Qp' "/DPackageDir=$PackageDir" "/DAppVersion=$version" "/O$OutputDir" "$PSScriptRoot/installer.iss"
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
$file = Join-Path $OutputDir 'Pereplet-Setup-Windows-x64.exe'
$hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$file.sha256", "$hash  Pereplet-Setup-Windows-x64.exe`n", [Text.Encoding]::ASCII)
Write-Host "Installer ready: $file"
