<#
.SYNOPSIS
    Build a distributable Windows folder with PyInstaller (onedir; see doc M5).

.DESCRIPTION
    Two deliberate choices:

    - onedir instead of onefile: onefile unpacks itself into a temp folder on every
      launch, which makes startup noticeably slower.
    - Explicitly exclude unused Qt modules: a full PySide6 bundle is several hundred
      MB, which conflicts with this project's "keep it light" goal.

    After building, README.md and FIRST_RUN.md are copied into the output folder so the
    whole folder can be shared as-is, and the packaged exe is smoke-tested twice: once
    for the data layer (`--self-check`) and once for the Qt platform plugin plus the
    whole UI layer (`--self-check-gui`). Neither check opens a window.

    SAFETY: PyInstaller deletes the whole output folder before collecting, and the
    portable data folder lives right next to the exe. So if `dist\<name>\data\index.json`
    exists -- meaning someone actually used that copy -- this script refuses to rebuild
    unless -Force is given.

    NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 files as ANSI
    unless they begin with a UTF-8 BOM, so non-ASCII text here can break parsing.

    NOTE ON SIZE: module-level --exclude-module only drops the Python-side modules. It does
    NOT remove the underlying Qt DLLs: Qt6Quick.dll, Qt6Qml.dll, libcrypto-3*.dll and
    opengl32sw.dll still end up in the bundle (~35 MB together) because PySide6's
    PyInstaller hook collects them. Slimming further means filtering binaries in a spec
    file, i.e. hand-deleting DLLs -- and the two non-interactive self-checks cannot cover
    every runtime path that might need them (file dialogs, styles). Not done on purpose.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/build.ps1
    powershell -ExecutionPolicy Bypass -File tools/build.ps1 -Python 'C:\Python312\python.exe'
    powershell -ExecutionPolicy Bypass -File tools/build.ps1 -Force
#>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$name = 'AlgorithmNoteHelper'
$dist = Join-Path $root "dist\$name"

# Guard: a rebuild wipes the output folder, and the portable data folder sits inside it.
$existingIndex = Join-Path $dist 'data\index.json'
if ((Test-Path $existingIndex) -and -not $Force) {
    throw ("Refusing to rebuild: {0} exists, which means this dist copy was actually used.`n" +
           "Rebuilding deletes the whole output folder, so that data would be lost.`n" +
           "Move it somewhere safe first, or re-run with -Force if you are sure.") -f $existingIndex
}

Push-Location $root
try {
    $excludes = @(
        # WebEngine / QML / Quick: this is a plain Widgets app
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets',
        # charts / 3D / multimedia
        'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtSpatialAudio',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic',
        'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
        # database / test / designer / help
        'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDesigner', 'PySide6.QtUiTools',
        'PySide6.QtHelp', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        # networking / devices
        'PySide6.QtNetworkAuth', 'PySide6.QtWebSockets', 'PySide6.QtWebChannel',
        'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning', 'PySide6.QtLocation',
        'PySide6.QtSerialPort', 'PySide6.QtRemoteObjects', 'PySide6.QtScxml',
        'PySide6.QtSensors', 'PySide6.QtStateMachine', 'PySide6.QtTextToSpeech',
        'PySide6.QtVirtualKeyboard', 'PySide6.QtHttpServer',
        # unrelated packages installed on this machine; do not let hooks drag them in.
        # setuptools / pkg_resources are intentionally NOT excluded: some PyInstaller
        # hooks need them at build time.
        'tkinter', 'pytest', 'numpy', 'pandas', 'matplotlib', 'PIL', 'lxml',
        'docx', 'pptx', 'openpyxl', 'XlsxWriter'
    )

    $arguments = @(
        '-m', 'PyInstaller',
        '--noconfirm', '--clean',
        '--onedir', '--windowed',
        '--name', $name
    )
    foreach ($module in $excludes) {
        $arguments += @('--exclude-module', $module)
    }
    $arguments += 'main.py'

    Write-Host '==> Running PyInstaller (the first build takes a while) ...' -ForegroundColor Cyan
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    $dist = Join-Path $root "dist\$name"
    Copy-Item (Join-Path $root 'README.md') $dist -Force
    Copy-Item (Join-Path $root 'FIRST_RUN.md') $dist -Force
    $exe = Join-Path $dist "$name.exe"
    Write-Host ''
    Write-Host '==> Smoke-testing the packaged exe (does not open a window) ...' -ForegroundColor Cyan
    & $exe --self-check
    $checkExit = $LASTEXITCODE

    # The plain self-check never creates a QApplication, so it cannot prove that the Qt
    # platform plugin was bundled. This second check builds the whole UI without showing
    # a window.
    Write-Host ''
    Write-Host '==> Checking that the packaged GUI can load Qt ...' -ForegroundColor Cyan
    & $exe --self-check-gui
    $guiExit = $LASTEXITCODE

    $files = Get-ChildItem $dist -Recurse -File
    $size = ($files | Measure-Object -Property Length -Sum).Sum

    Write-Host ''
    Write-Host ("Output : {0}" -f $dist)
    Write-Host ("Size   : {0:N1} MB ({1} files)" -f ($size / 1MB), $files.Count)

    foreach ($logName in 'self-check.log', 'gui-check.log') {
        $log = Join-Path $dist "data\$logName"
        if (Test-Path $log) {
            Write-Host ("{0}:" -f $logName)
            Get-Content $log | ForEach-Object { Write-Host "    $_" }
        }
    }
    Write-Host ("Self-check exit code    : {0}" -f $checkExit)
    Write-Host ("GUI self-check exit code: {0}" -f $guiExit)
    if ($checkExit -ne 0) { throw 'the packaged exe failed its self-check' }
    if ($guiExit -ne 0) { throw 'the packaged exe failed its GUI self-check' }
}
finally {
    Pop-Location
}
