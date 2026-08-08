[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("fuse", "all", "check", "check-config", "dry-run", "run", "audit")]
    [string]$Action,

    [ValidateSet("zhongning", "dongxing", "bishan")]
    [string]$Dataset = "zhongning",
    [string]$DltbSource,
    [string]$DltbLayer,
    [string]$DataRoot,
    [string]$Config,
    [string]$DemDir,
    [string]$AdminReference,
    [string]$CountyCode,
    [string]$CountyName,
    [string]$ReferenceCountyCode
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Get-AbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Invoke-Paper9Python {
    param([Parameter(Mandatory = $true)][string[]]$CommandArguments)
    & $script:PythonExe @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Paper9 command failed with exit code $LASTEXITCODE."
    }
}

$ParentOfBin = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (Test-Path -LiteralPath (Join-Path $ParentOfBin "app\src")) {
    $BundleRoot = $ParentOfBin
    $AppRoot = Join-Path $BundleRoot "app"
} else {
    $BundleRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
    $AppRoot = $BundleRoot
}

$RuntimeRoot = Join-Path $BundleRoot "runtime"
$script:PythonExe = Join-Path $RuntimeRoot "python.exe"
$ExternalDltbSource = -not [string]::IsNullOrWhiteSpace($DltbSource)
$DatasetDefaults = switch ($Dataset) {
    "zhongning" {
        [ordered]@{
            county_code = "640521"
            county_name = "中宁县"
            reference_county_code = "640521"
            config = "configs\paper9v23_zhongning_dltb_only.yml"
            dltb = $null
            dem_dir = "dem\copernicus_glo30_zhongning"
            admin = "reference\admin\xiangzhen_zhongning.gpkg"
            dem_tiles = @(
                "Copernicus_DSM_COG_10_N36_00_E105_00_DEM.tif",
                "Copernicus_DSM_COG_10_N36_00_E106_00_DEM.tif",
                "Copernicus_DSM_COG_10_N37_00_E105_00_DEM.tif",
                "Copernicus_DSM_COG_10_N37_00_E106_00_DEM.tif"
            )
        }
    }
    "dongxing" {
        [ordered]@{
            county_code = "511011"
            county_name = "四川省内江市东兴区"
            reference_county_code = "511011"
            config = "configs\paper9v23_dongxing_dltb_only.yml"
            dltb = "datasets\dongxing\DLTB_with_slope.gpkg"
            dem_dir = "dem\copernicus_glo30"
            admin = "reference\admin\xiangzhen_dongxing_bishan.gpkg"
            dem_tiles = @(
                "Copernicus_DSM_COG_10_N29_00_E104_00_DEM.tif",
                "Copernicus_DSM_COG_10_N29_00_E105_00_DEM.tif"
            )
        }
    }
    "bishan" {
        [ordered]@{
            county_code = "500227"
            county_name = "重庆市璧山区（源数据旧码）"
            reference_county_code = "500120"
            config = "configs\paper9v23_bishan_dltb_only.yml"
            dltb = "datasets\bishan\DLTB_with_slope.gpkg"
            dem_dir = "dem\copernicus_glo30"
            admin = "reference\admin\xiangzhen_dongxing_bishan.gpkg"
            dem_tiles = @(
                "Copernicus_DSM_COG_10_N29_00_E106_00_DEM.tif"
            )
        }
    }
}
$CountyCode = if ($CountyCode) { $CountyCode } else { $DatasetDefaults.county_code }
$CountyName = if ($CountyName) { $CountyName } else { $DatasetDefaults.county_name }
$ReferenceCountyCode = if ($ReferenceCountyCode) { $ReferenceCountyCode } else { $DatasetDefaults.reference_county_code }
$DltbSource = if ($DltbSource) {
    Get-AbsolutePath $DltbSource
} elseif ($DatasetDefaults.dltb) {
    Join-Path $BundleRoot $DatasetDefaults.dltb
} else {
    $null
}
$TemplateConfig = if ($Config) {
    Get-AbsolutePath $Config
} else {
    Join-Path $AppRoot $DatasetDefaults.config
}
$DemDir = if ($DemDir) {
    Get-AbsolutePath $DemDir
} else {
    Join-Path $BundleRoot $DatasetDefaults.dem_dir
}
$AdminReference = if ($AdminReference) {
    Get-AbsolutePath $AdminReference
} else {
    Join-Path $BundleRoot $DatasetDefaults.admin
}
$DataRoot = if ($DataRoot) {
    Get-AbsolutePath $DataRoot
} else {
    Join-Path $BundleRoot ("paper9-data\" + $Dataset)
}
$InputDir = Join-Path $DataRoot "input"
$OutputsDir = Join-Path $DataRoot "outputs"
$RuntimeConfig = Join-Path $DataRoot "paper9v23_$Dataset.runtime.yml"

function Initialize-Paper9Runtime {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "Paper9v2.3 requires 64-bit Windows."
    }
    if (-not (Test-Path -LiteralPath $script:PythonExe -PathType Leaf)) {
        throw "Bundled Windows runtime is missing: $script:PythonExe"
    }

    $UnpackMarker = Join-Path $RuntimeRoot ".paper9-conda-unpacked"
    if (-not (Test-Path -LiteralPath $UnpackMarker)) {
        $CondaUnpack = Join-Path $RuntimeRoot "Scripts\conda-unpack.exe"
        $CondaUnpackScript = Join-Path $RuntimeRoot "Scripts\conda-unpack-script.py"
        if (Test-Path -LiteralPath $CondaUnpack -PathType Leaf) {
            & $CondaUnpack
        } elseif (Test-Path -LiteralPath $CondaUnpackScript -PathType Leaf) {
            & $script:PythonExe $CondaUnpackScript
        } else {
            throw "conda-unpack is missing from the bundled runtime."
        }
        if ($LASTEXITCODE -ne 0) {
            throw "conda-unpack failed with exit code $LASTEXITCODE."
        }
        New-Item -ItemType File -Path $UnpackMarker -Force | Out-Null
    }

    $env:PYTHONPATH = Join-Path $AppRoot "src"
    $env:PAPER9_OFFLINE = "1"
    $env:NO_PROXY = "*"
    $env:PATH = "$RuntimeRoot;$RuntimeRoot\Library\bin;$RuntimeRoot\Scripts;$env:PATH"
    $env:GDAL_DATA = Join-Path $RuntimeRoot "Library\share\gdal"
    $env:PROJ_LIB = Join-Path $RuntimeRoot "Library\share\proj"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
}

function Initialize-DataDirectories {
    foreach ($Directory in @($DataRoot, $InputDir, (Join-Path $DataRoot "working"), $OutputsDir, (Join-Path $OutputsDir "logs"))) {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    }
}

function Write-RuntimeConfig {
    Initialize-DataDirectories
    Invoke-Paper9Python -CommandArguments @(
        (Join-Path $AppRoot "scripts\render_dltb_only_runtime_config.py"),
        "--template", $TemplateConfig,
        "--output", $RuntimeConfig,
        "--data-root", $DataRoot,
        "--run-name", $Dataset
    )
}

function Assert-FusedInputs {
    foreach ($RequiredFile in @(
        (Join-Path $InputDir "DLTB_with_authority_slope.gpkg"),
        (Join-Path $InputDir "admin_units.gpkg"),
        (Join-Path $InputDir "DEM_placeholder.tif"),
        (Join-Path $InputDir "input_availability.json")
    )) {
        if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
            throw "Run the fuse action first. Missing input: $RequiredFile"
        }
    }
}

function Invoke-Fusion {
    if (-not $DltbSource) {
        throw "-DltbSource is required for the Zhongning dataset; use -Dataset dongxing or -Dataset bishan for built-in samples."
    }
    if ($ExternalDltbSource) {
        if (-not (Test-Path -LiteralPath $DltbSource -PathType Container)) {
            throw "-DltbSource must point to an existing Esri FileGDB directory (*.gdb), not a file."
        }
        if (-not $DltbSource.EndsWith(".gdb", [StringComparison]::OrdinalIgnoreCase)) {
            throw "-DltbSource must point to a complete Esri FileGDB directory whose path ends in .gdb."
        }
    }
    $ResolvedDltb = (Resolve-Path -LiteralPath $DltbSource).Path
    if (-not (Test-Path -LiteralPath $DemDir -PathType Container)) {
        throw "Bundled DEM directory is missing: $DemDir"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $DemDir "DEM_MANIFEST.json") -PathType Leaf)) {
        throw "Bundled DEM manifest is missing: $DemDir\DEM_MANIFEST.json"
    }
    if (-not (Test-Path -LiteralPath $AdminReference -PathType Leaf)) {
        throw "Bundled administrative reference is missing: $AdminReference"
    }
    $DemFiles = @(
        foreach ($TileName in $DatasetDefaults.dem_tiles) {
            $TilePath = Join-Path $DemDir $TileName
            if (-not (Test-Path -LiteralPath $TilePath -PathType Leaf)) {
                throw "Required $Dataset DEM tile is missing: $TilePath"
            }
            Get-Item -LiteralPath $TilePath
        }
    )
    if ($DemFiles.Count -ne $DatasetDefaults.dem_tiles.Count) {
        throw "The bundled DEM selection for $Dataset is incomplete."
    }

    Initialize-DataDirectories
    $FusionArguments = @(
        (Join-Path $AppRoot "scripts\fuse_dltb_dem_county.py"),
        "--dltb-source", $ResolvedDltb,
        "--county-code", $CountyCode,
        "--county-name", $CountyName,
        "--output-dir", $InputDir,
        "--dem"
    )
    foreach ($DemFile in $DemFiles) {
        $FusionArguments += $DemFile.FullName
    }
    $FusionArguments += @(
        "--admin-reference", $AdminReference,
        "--log-dir", (Join-Path $OutputsDir "logs")
    )
    if ($ReferenceCountyCode -and $ReferenceCountyCode -ne $CountyCode) {
        $FusionArguments += @("--reference-county-code", $ReferenceCountyCode)
    }
    if ($DltbLayer) {
        $FusionArguments += @("--dltb-layer", $DltbLayer)
    }
    Invoke-Paper9Python -CommandArguments $FusionArguments
    Write-RuntimeConfig

    Write-Host "Fusion completed for dataset=${Dataset}: $InputDir"
    Write-Warning "PDT, ecological redline, and permanent basic farmland were not evaluated. Results are for exploratory technical validation only."
    Write-Host "Next: .\bin\run-paper9-windows.ps1 run -DataRoot `"$DataRoot`""
}

function Invoke-Pipeline {
    param([switch]$DryRun)
    Assert-FusedInputs
    Write-RuntimeConfig
    $PipelineArguments = @(
        (Join-Path $AppRoot "scripts\run_full_pipeline.py"),
        $RuntimeConfig,
        "--log-dir", (Join-Path $OutputsDir "logs")
    )
    if ($DryRun) {
        $PipelineArguments += "--dry-run"
    }
    Invoke-Paper9Python -CommandArguments $PipelineArguments
}

$VerifyScript = Join-Path $PSScriptRoot "verify-paper9-package.ps1"
if ($Action -eq "check" -and (Test-Path -LiteralPath $VerifyScript) -and (Test-Path -LiteralPath (Join-Path $BundleRoot "SHA256SUMS.txt"))) {
    & $VerifyScript -BundleRoot $BundleRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Package checksum verification failed."
    }
}

Initialize-Paper9Runtime
Push-Location $AppRoot
try {
    switch ($Action) {
        "fuse" {
            Invoke-Fusion
        }
        "all" {
            Invoke-Fusion
            Invoke-Pipeline
        }
        "check" {
            Invoke-Paper9Python -CommandArguments @((Join-Path $AppRoot "scripts\00_check_env.py"))
            Invoke-Paper9Python -CommandArguments @("-m", "paper9_mnr.cli", "check-config", $TemplateConfig)
        }
        "check-config" {
            $ConfigToCheck = if (Test-Path -LiteralPath $RuntimeConfig) { $RuntimeConfig } else { $TemplateConfig }
            Invoke-Paper9Python -CommandArguments @("-m", "paper9_mnr.cli", "check-config", $ConfigToCheck)
        }
        "dry-run" {
            Invoke-Pipeline -DryRun
        }
        "run" {
            Invoke-Pipeline
        }
        "audit" {
            Assert-FusedInputs
            Write-RuntimeConfig
            Invoke-Paper9Python -CommandArguments @((Join-Path $AppRoot "scripts\05_audit.py"), $RuntimeConfig, "--write")
        }
    }
} finally {
    Pop-Location
}
