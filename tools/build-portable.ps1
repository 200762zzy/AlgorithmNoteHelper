<#
.SYNOPSIS
    Build the "signed host" portable distribution (no SmartScreen prompt).

.DESCRIPTION
    Why this exists
    ---------------
    PyInstaller's entry point is an unsigned exe, so Windows SmartScreen warns on every
    distribution AND on every new version (unsigned files rebuild reputation from zero).
    Verified on Windows 11 25H2: running the same code through the Python Software
    Foundation's *signed* pythonw.exe does not trigger the warning, even when the files
    carry Mark-of-the-Web (i.e. extracted from a downloaded zip). No certificate needed.

    How the Qt payload is chosen
    ---------------------------
    The installed PySide6 is ~634 MB (full Qt, incl. WebEngine .pak resources, qml, all
    translations). Hand-picking DLLs is exactly the unverifiable change this project
    avoids, so instead this script runs tools/build.ps1 first and treats the resulting
    PyInstaller payload as a *manifest*: the Qt6*.dll / .pyd / plugins / translations it
    contains are already proven sufficient by the two self-checks. Those exact files are
    copied from the install, plus the small set of .py files PyInstaller strips (the
    payload has no __init__.py, so it is not directly importable).

    What it does NOT do
    -------------------
    It does not prune beyond that manifest. Qt's own translation files are the obvious
    next candidate but are still unverified, so they stay.

    NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 files as ANSI
    unless they begin with a UTF-8 BOM, so non-ASCII text here can break parsing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/build-portable.ps1
    powershell -ExecutionPolicy Bypass -File tools/build-portable.ps1 -Python 'C:\Python312\python.exe'
#>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$DistPath = 'dist-portable',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$name = 'AlgorithmNoteHelper'
$portable = Join-Path (Join-Path $root $DistPath) $name
$runtime = Join-Path $portable 'runtime'
# PySide6 must live under Lib\site-packages: sys.path only contains the script directory,
# Lib, Lib\site-packages and DLLs, so it would not be importable at the runtime root.
$runtimeSite = Join-Path $runtime 'Lib\site-packages'

# --- resolve the Python installation ------------------------------------------------
$command = Get-Command $Python -ErrorAction SilentlyContinue
$pythonExe = if ($command) { $command.Source } elseif (Test-Path $Python) { (Resolve-Path $Python).Path } else { $null }
if (-not $pythonExe) { throw "cannot find the Python interpreter: $Python" }
$pythonRoot = Split-Path $pythonExe -Parent
$sitePackages = Join-Path $pythonRoot 'Lib\site-packages'
Write-Host ("Python : {0}" -f $pythonRoot) -ForegroundColor Cyan

# --- guard: a rebuild wipes the folder, and the portable data folder lives inside it --
$existingIndex = Join-Path $portable 'data\index.json'
if ((Test-Path $existingIndex) -and -not $Force) {
    throw ("Refusing to rebuild: {0} exists, which means this copy was actually used.`n" +
           "Rebuilding deletes the whole output folder, so that data would be lost.`n" +
           "Move it somewhere safe first, or re-run with -Force if you are sure.") -f $existingIndex
}

# --- step 1: produce the manifest payload with PyInstaller --------------------------
$manifestName = 'portable-manifest'
Write-Host '==> Step 1/4: building the PyInstaller payload to use as a file manifest ...' -ForegroundColor Cyan
$manifestLog = Join-Path $root 'build\portable-manifest-build.log'
$manifestErr = Join-Path $root 'build\portable-manifest-build.err.log'
# Start-Process with separate redirects, NOT `*> $log`: merging stderr into PowerShell's
# error stream turns PyInstaller's normal INFO output into a terminating error here,
# because $ErrorActionPreference is Stop.
$manifestDist = Join-Path 'build' $manifestName
$inner = Start-Process -FilePath 'powershell.exe' -Wait -PassThru -NoNewWindow -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', (Join-Path $PSScriptRoot 'build.ps1'),
    '-Python', $pythonExe,
    '-DistPath', $manifestDist
) -RedirectStandardOutput $manifestLog -RedirectStandardError $manifestErr
if ($inner.ExitCode -ne 0) {
    Get-Content $manifestErr | Select-Object -Last 15
    throw "the manifest build failed with exit code $($inner.ExitCode)"
}
$manifest = Join-Path $root "build\$manifestName\$name\_internal"
if (-not (Test-Path $manifest)) { throw "manifest payload not found: $manifest" }

# --- step 2: assemble the portable folder -------------------------------------------
Write-Host '==> Step 2/4: copying the verified Qt payload ...' -ForegroundColor Cyan
if (Test-Path $portable) { Remove-Item $portable -Recurse -Force }
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Copy-Tree([string]$From, [string]$To, [scriptblock]$Filter) {
    foreach ($file in (Get-ChildItem $From -Recurse -File -ErrorAction SilentlyContinue)) {
        if ($Filter -and -not (& $Filter $file)) { continue }
        $relative = $file.FullName.Substring($From.Length).TrimStart('\')
        $target = Join-Path $To $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
        Copy-Item $file.FullName $target -Force
    }
}

# 2a) exactly the files the verified payload ships (Qt6*.dll, .pyd, plugins, translations)
Copy-Tree (Join-Path $manifest 'PySide6') (Join-Path $runtimeSite 'PySide6') { $true }
Copy-Tree (Join-Path $manifest 'shiboken6') (Join-Path $runtimeSite 'shiboken6') { $true }

# 2b) the .py files PyInstaller strips; without __init__.py the package is not importable
Copy-Tree (Join-Path $sitePackages 'PySide6') (Join-Path $runtimeSite 'PySide6') {
    param($f) $f.Extension -eq '.py'
}
Copy-Tree (Join-Path $sitePackages 'shiboken6') (Join-Path $runtimeSite 'shiboken6') {
    param($f) $f.Extension -eq '.py'
}

# 2c) interpreter, runtime DLLs and extension modules
foreach ($file in (Get-ChildItem $manifest -File -Filter '*.dll')) {
    Copy-Item $file.FullName (Join-Path $runtime $file.Name) -Force
}
foreach ($name2 in 'pythonw.exe', 'python.exe', 'python312.dll', 'python3.dll') {
    $source = Join-Path $pythonRoot $name2
    if (Test-Path $source) { Copy-Item $source (Join-Path $runtime $name2) -Force }
}
Copy-Tree (Join-Path $pythonRoot 'DLLs') (Join-Path $runtime 'DLLs') { $true }

# 2d) standard library, minus the obvious dead weight
Write-Host '==> Step 3/4: copying the standard library ...' -ForegroundColor Cyan
$deadWeight = 'site-packages', 'test', 'idlelib', 'tkinter', 'lib2to3', 'ensurepip',
              'turtledemo', 'pydoc_data', 'distutils', 'venv', '__pycache__'
robocopy (Join-Path $pythonRoot 'Lib') (Join-Path $runtime 'Lib') /E /XD @deadWeight /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

# 2e) our own source and the two documents people need
foreach ($file in 'main.py', 'models.py', 'paths.py', 'services.py', 'srs.py', 'storage.py') {
    Copy-Item (Join-Path $root $file) $portable -Force
}
Copy-Item (Join-Path $root 'ui') $portable -Recurse -Force
Get-ChildItem (Join-Path $portable 'ui') -Recurse -Directory -Filter '__pycache__' |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
foreach ($doc in 'README.md', 'FIRST_RUN.md') {
    Copy-Item (Join-Path $root $doc) $portable -Force
}

# 2f) launchers (ASCII content; the file names may be non-ASCII, cmd handles that)
$launch = @"
@echo off
rem Run AlgorithmNoteHelper through the Python Software Foundation's signed pythonw.exe.
rem That signature is exactly why Windows SmartScreen stays quiet - see FIRST_RUN.md.
set PYTHONHOME=%~dp0runtime
start "" "%~dp0runtime\pythonw.exe" "%~dp0main.py"
"@
[System.IO.File]::WriteAllText((Join-Path $portable 'run.bat'), $launch, (New-Object System.Text.ASCIIEncoding))

$diagnose = @"
@echo off
rem Diagnostic launcher: keeps a console open so errors are readable, and writes
rem data\self-check.log. Use this when the app does not start.
set PYTHONHOME=%~dp0runtime
"%~dp0runtime\python.exe" "%~dp0main.py" --self-check
echo.
echo exit code: %errorlevel%
pause
"@
[System.IO.File]::WriteAllText((Join-Path $portable 'self-check.bat'), $diagnose, (New-Object System.Text.ASCIIEncoding))

# --- step 3: verify the assembled runtime ------------------------------------------
Write-Host '==> Step 4/4: verifying (no window is opened) ...' -ForegroundColor Cyan
$env:PYTHONHOME = $runtime
try {
    # Start-Process -Wait, not `&`: pythonw.exe is a GUI-subsystem binary, so the call
    # operator does NOT wait for it and $LASTEXITCODE keeps a stale value from whatever
    # native command ran before. That mistake made a passing build look like a failure.
    $mainScript = Join-Path $portable 'main.py'
    $check = Start-Process -FilePath (Join-Path $runtime 'pythonw.exe') `
        -ArgumentList @($mainScript, '--self-check') -Wait -PassThru -NoNewWindow
    $checkExit = $check.ExitCode
    $guiCheck = Start-Process -FilePath (Join-Path $runtime 'pythonw.exe') `
        -ArgumentList @($mainScript, '--self-check-gui') -Wait -PassThru -NoNewWindow
    $guiExit = $guiCheck.ExitCode
} finally {
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
}

$dataDir = Join-Path $portable 'data'
foreach ($log in 'self-check.log', 'gui-check.log') {
    $path = Join-Path $dataDir $log
    if (Test-Path $path) {
        Write-Host ("{0}:" -f $log)
        Get-Content $path -Encoding UTF8 | ForEach-Object { Write-Host "    $_" }
    }
}

# Do not ship what the verification run left behind. Note that data\index.json only
# appears once someone actually uses the copy, so the rebuild guard above still protects
# real data.
Get-ChildItem $portable -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $dataDir -Recurse -Force -ErrorAction SilentlyContinue

$files = Get-ChildItem $portable -Recurse -File
$size = ($files | Measure-Object -Property Length -Sum).Sum
Write-Host ''
Write-Host 'Entries users will double-click:'
foreach ($entry in 'run.bat', 'self-check.bat') {
    Write-Host ("    {0,-16} (a script; no signature involved)" -f $entry)
}
$pythonw = Join-Path $runtime 'pythonw.exe'
$pythonwSignature = Get-AuthenticodeSignature $pythonw
Write-Host ("    runtime\pythonw.exe is signed by {0} ({1})" -f `
    ($pythonwSignature.SignerCertificate.Subject -replace '^CN=([^,]+).*', '$1'),
    $pythonwSignature.Status)

Write-Host ''
Write-Host ("Output : {0}" -f $portable)
Write-Host ("Size   : {0:N1} MB ({1} files)" -f ($size / 1MB), $files.Count)
Write-Host ("Self-check exit code    : {0}" -f $checkExit)
Write-Host ("GUI self-check exit code: {0}" -f $guiExit)
if ($checkExit -ne 0) { throw 'the portable runtime failed its self-check' }
if ($guiExit -ne 0) { throw 'the portable runtime failed its GUI self-check' }
Write-Host 'Done. Distribute this folder; users double-click run.bat.'
