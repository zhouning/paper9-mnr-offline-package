[CmdletBinding()]
param(
    [string]$CondaExe = "conda",
    [string]$BuildPrefix,
    [string]$RuntimeArchive,
    [string]$OutputBundle,
    [switch]$ReuseEnvironment,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

if ($env:OS -ne "Windows_NT" -or -not [Environment]::Is64BitOperatingSystem) {
    throw "This runtime must be built on 64-bit Windows, not on macOS, Linux, WSL, or Windows ARM."
}

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$BuildPrefix = if ($BuildPrefix) {
    [IO.Path]::GetFullPath($BuildPrefix)
} else {
    Join-Path $RepoRoot "dist\build\paper9-mnr-windows-x86_64"
}
$RuntimeArchive = if ($RuntimeArchive) {
    [IO.Path]::GetFullPath($RuntimeArchive)
} else {
    Join-Path $RepoRoot "dist\paper9-mnr-runtime-0.4.0-windows-x86_64.zip"
}
$OutputBundle = if ($OutputBundle) {
    [IO.Path]::GetFullPath($OutputBundle)
} else {
    Join-Path $RepoRoot "dist\paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64.zip"
}
$EnvironmentFile = Join-Path $PSScriptRoot "environment-windows-x86_64.yml"
$EnvironmentLock = Join-Path $RepoRoot "dist\paper9-mnr-runtime-0.4.0-windows-x86_64-explicit.txt"

if ((Test-Path -LiteralPath $BuildPrefix) -and -not $ReuseEnvironment) {
    throw "Build environment already exists. Pass -ReuseEnvironment or choose another -BuildPrefix: $BuildPrefix"
}
if (-not (Test-Path -LiteralPath $BuildPrefix)) {
    & $CondaExe env create --prefix $BuildPrefix --file $EnvironmentFile --yes
    if ($LASTEXITCODE -ne 0) {
        throw "Conda environment creation failed with exit code $LASTEXITCODE."
    }
}

$PythonExe = Join-Path $BuildPrefix "python.exe"
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Windows Python was not created: $PythonExe"
}

$PreviousPythonPath = $env:PYTHONPATH
$PreviousGdalData = $env:GDAL_DATA
$PreviousProjLib = $env:PROJ_LIB
$PreviousPath = $env:PATH
$env:PYTHONPATH = Join-Path $RepoRoot "src"
$env:GDAL_DATA = Join-Path $BuildPrefix "Library\share\gdal"
$env:PROJ_LIB = Join-Path $BuildPrefix "Library\share\proj"
$env:PATH = "$BuildPrefix;$BuildPrefix\Library\bin;$BuildPrefix\Scripts;$env:PATH"
try {
    if (-not $SkipTests) {
        Push-Location $RepoRoot
        try {
            & $PythonExe -m pytest -q
            if ($LASTEXITCODE -ne 0) {
                throw "Windows test suite failed with exit code $LASTEXITCODE."
            }
            & $PythonExe -m ruff check --select E4,E7,E9,F `
                src\paper9_mnr\audit.py `
                src\paper9_mnr\config.py `
                src\paper9_mnr\dltb_dem_fusion.py `
                src\paper9_mnr\fusion.py `
                src\paper9_mnr\version.py `
                src\farmland_mpc\cli.py `
                src\farmland_mpc\mpc_plan.py `
                src\farmland_mpc\shapefile_io.py `
                scripts\05_audit.py `
                scripts\fuse_dltb_dem_county.py `
                scripts\render_dltb_only_runtime_config.py `
                tests\test_audit_constraints.py `
                tests\test_authoritative_fusion.py `
                tests\test_run_metadata.py `
                tests\test_version_and_config.py `
                tests\test_windows_native_deployment.py
            if ($LASTEXITCODE -ne 0) {
                throw "Windows Ruff check failed with exit code $LASTEXITCODE."
            }
        } finally {
            Pop-Location
        }
    }
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
    $env:GDAL_DATA = $PreviousGdalData
    $env:PROJ_LIB = $PreviousProjLib
    $env:PATH = $PreviousPath
}

New-Item -ItemType Directory -Path (Split-Path $RuntimeArchive -Parent) -Force | Out-Null
if (Test-Path -LiteralPath $RuntimeArchive) {
    throw "Runtime archive already exists: $RuntimeArchive"
}
$CondaPackExe = Join-Path $BuildPrefix "Scripts\conda-pack.exe"
if (-not (Test-Path -LiteralPath $CondaPackExe -PathType Leaf)) {
    throw "conda-pack was not installed in the build environment."
}
& $CondaPackExe --prefix $BuildPrefix --output $RuntimeArchive --format zip
if ($LASTEXITCODE -ne 0) {
    throw "conda-pack failed with exit code $LASTEXITCODE."
}

$LockLines = & $CondaExe list --explicit --prefix $BuildPrefix
if ($LASTEXITCODE -ne 0) {
    throw "Could not export the explicit Conda environment lock."
}
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllLines($EnvironmentLock, [string[]]$LockLines, $Utf8NoBom)

$GitCommit = (& git -C $RepoRoot rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $GitCommit) {
    $GitCommit = "unknown"
}
& (Join-Path $PSScriptRoot "package-windows-bundle.ps1") `
    -RuntimeArchive $RuntimeArchive `
    -EnvironmentLock $EnvironmentLock `
    -Output $OutputBundle `
    -GitCommit $GitCommit
