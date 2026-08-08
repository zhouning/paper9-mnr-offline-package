[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("fuse", "all", "check", "check-config", "dry-run", "run", "audit")]
    [string]$Action,

    [ValidateSet("zhongning", "dongxing", "bishan")]
    [string]$Dataset = "zhongning",
    [string]$DockerExe = "docker",
    [string]$Image = "paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64",
    [string]$ImageTar,
    [string]$Platform = "linux/amd64",
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

function Get-BundledAsset {
    param(
        [Parameter(Mandatory = $true)][string]$BundleRelative,
        [Parameter(Mandatory = $true)][string]$RepoRelative
    )
    $BundleCandidate = Join-Path $script:BundleRoot $BundleRelative
    if (Test-Path -LiteralPath $BundleCandidate) {
        return $BundleCandidate
    }
    return Join-Path $script:RepoRoot $RepoRelative
}

function Invoke-DockerCommand {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & $DockerExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Paper9Container {
    param(
        [Parameter(Mandatory = $true)][string[]]$CommandArguments,
        [string[]]$MountSpecifications = @()
    )
    $DockerArguments = @(
        "run", "--rm",
        "--network", "none",
        "--platform", $Platform,
        "-e", "PAPER9_OFFLINE=1",
        "-e", "PAPER9_IMAGE_REF=$Image",
        "-e", "PYTHONIOENCODING=utf-8",
        "-e", "PYTHONUTF8=1",
        "--mount", "type=bind,source=$DataRoot,target=/paper9-data"
    )
    foreach ($MountSpecification in $MountSpecifications) {
        $DockerArguments += @("--mount", $MountSpecification)
    }
    $DockerArguments += $Image
    $DockerArguments += $CommandArguments
    Invoke-DockerCommand -Arguments $DockerArguments
}

$ParentOfScript = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$script:RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$script:BundleRoot = if (
    (Test-Path -LiteralPath (Join-Path $ParentOfScript "datasets") -PathType Container) -and
    (Test-Path -LiteralPath (Join-Path $ParentOfScript "dem") -PathType Container)
) {
    $ParentOfScript
} else {
    $script:RepoRoot
}

$ExternalDltbSource = -not [string]::IsNullOrWhiteSpace($DltbSource)
$DatasetDefaults = switch ($Dataset) {
    "zhongning" {
        [ordered]@{
            county_code = "640521"
            county_name = "中宁县"
            reference_county_code = "640521"
            config = "configs/paper9v23_zhongning_dltb_only.yml"
            dltb_bundle = $null
            dltb_repo = $null
            dem_bundle = "dem/copernicus_glo30_zhongning"
            dem_repo = "dist/dem/copernicus_glo30_zhongning"
            admin_bundle = "reference/admin/xiangzhen_zhongning.gpkg"
            admin_repo = "reference/admin/xiangzhen_zhongning.gpkg"
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
            config = "configs/paper9v23_dongxing_dltb_only.yml"
            dltb_bundle = "datasets/dongxing/DLTB_with_slope.gpkg"
            dltb_repo = "dist/datasets/dongxing/DLTB_with_slope.gpkg"
            dem_bundle = "dem/copernicus_glo30"
            dem_repo = "dist/dem/copernicus_glo30"
            admin_bundle = "reference/admin/xiangzhen_dongxing_bishan.gpkg"
            admin_repo = "reference/admin/xiangzhen_dongxing_bishan.gpkg"
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
            config = "configs/paper9v23_bishan_dltb_only.yml"
            dltb_bundle = "datasets/bishan/DLTB_with_slope.gpkg"
            dltb_repo = "dist/datasets/bishan/DLTB_with_slope.gpkg"
            dem_bundle = "dem/copernicus_glo30"
            dem_repo = "dist/dem/copernicus_glo30"
            admin_bundle = "reference/admin/xiangzhen_dongxing_bishan.gpkg"
            admin_repo = "reference/admin/xiangzhen_dongxing_bishan.gpkg"
            dem_tiles = @("Copernicus_DSM_COG_10_N29_00_E106_00_DEM.tif")
        }
    }
}

$CountyCode = if ($CountyCode) { $CountyCode } else { $DatasetDefaults.county_code }
$CountyName = if ($CountyName) { $CountyName } else { $DatasetDefaults.county_name }
$ReferenceCountyCode = if ($ReferenceCountyCode) { $ReferenceCountyCode } else { $DatasetDefaults.reference_county_code }
$DltbSource = if ($DltbSource) {
    Get-AbsolutePath $DltbSource
} elseif ($DatasetDefaults.dltb_bundle) {
    Get-BundledAsset -BundleRelative $DatasetDefaults.dltb_bundle -RepoRelative $DatasetDefaults.dltb_repo
} else {
    $null
}
$DemDir = if ($DemDir) {
    Get-AbsolutePath $DemDir
} else {
    Get-BundledAsset -BundleRelative $DatasetDefaults.dem_bundle -RepoRelative $DatasetDefaults.dem_repo
}
$AdminReference = if ($AdminReference) {
    Get-AbsolutePath $AdminReference
} else {
    Get-BundledAsset -BundleRelative $DatasetDefaults.admin_bundle -RepoRelative $DatasetDefaults.admin_repo
}
$DataRoot = if ($DataRoot) {
    Get-AbsolutePath $DataRoot
} else {
    Get-AbsolutePath (Join-Path "paper9-data" $Dataset)
}
$TemplateConfig = if ($Config) { $Config } else { $DatasetDefaults.config }
$TemplateConfigContainer = if ($TemplateConfig.StartsWith("/")) {
    $TemplateConfig
} else {
    "/app/" + $TemplateConfig.Replace("\", "/")
}
$RuntimeConfigName = "paper9v23_$Dataset.runtime.yml"
$RuntimeConfigHost = Join-Path $DataRoot $RuntimeConfigName
$RuntimeConfigContainer = "/paper9-data/$RuntimeConfigName"
$InputDir = Join-Path $DataRoot "input"
$OutputsDir = Join-Path $DataRoot "outputs"

function Initialize-DataDirectories {
    foreach ($Directory in @($DataRoot, $InputDir, (Join-Path $DataRoot "working"), $OutputsDir, (Join-Path $OutputsDir "logs"))) {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    }
}

function Initialize-DockerRuntime {
    if (-not (Get-Command $DockerExe -ErrorAction SilentlyContinue)) {
        throw "Docker CLI is not available: $DockerExe"
    }
    if ($ImageTar) {
        $ResolvedImageTar = (Resolve-Path -LiteralPath (Get-AbsolutePath $ImageTar)).Path
        Invoke-DockerCommand -Arguments @("load", "-i", $ResolvedImageTar)
    }
    Invoke-DockerCommand -Arguments @("image", "inspect", $Image)
}

function Write-RuntimeConfig {
    Initialize-DataDirectories
    Invoke-Paper9Container -CommandArguments @(
        "python", "scripts/render_dltb_only_runtime_config.py",
        "--template", $TemplateConfigContainer,
        "--output", $RuntimeConfigContainer,
        "--data-root", "/paper9-data",
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
        throw "-DltbSource is required for Zhongning; Dongxing and Bishan have built-in samples."
    }
    if ($ExternalDltbSource) {
        if (-not (Test-Path -LiteralPath $DltbSource -PathType Container)) {
            throw "-DltbSource must point to an existing Esri FileGDB directory (*.gdb), not a file."
        }
        if (-not $DltbSource.EndsWith(".gdb", [StringComparison]::OrdinalIgnoreCase)) {
            throw "-DltbSource must point to a complete Esri FileGDB directory whose path ends in .gdb."
        }
    } elseif (-not (Test-Path -LiteralPath $DltbSource -PathType Leaf)) {
        throw "Built-in DLTB is missing: $DltbSource"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $DemDir "DEM_MANIFEST.json") -PathType Leaf)) {
        throw "Bundled DEM manifest is missing: $DemDir\DEM_MANIFEST.json"
    }
    if (-not (Test-Path -LiteralPath $AdminReference -PathType Leaf)) {
        throw "Bundled administrative reference is missing: $AdminReference"
    }
    foreach ($TileName in $DatasetDefaults.dem_tiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $DemDir $TileName) -PathType Leaf)) {
            throw "Required $Dataset DEM tile is missing: $DemDir\$TileName"
        }
    }

    Initialize-DataDirectories
    $DltbContainerPath = if ($ExternalDltbSource) { "/paper9-assets/dltb.gdb" } else { "/paper9-assets/dltb.gpkg" }
    $Mounts = @(
        "type=bind,source=$DltbSource,target=$DltbContainerPath,readonly",
        "type=bind,source=$DemDir,target=/paper9-assets/dem,readonly",
        "type=bind,source=$AdminReference,target=/paper9-assets/admin.gpkg,readonly"
    )
    $FusionArguments = @(
        "python", "scripts/fuse_dltb_dem_county.py",
        "--dltb-source", $DltbContainerPath,
        "--county-code", $CountyCode,
        "--county-name", $CountyName,
        "--output-dir", "/paper9-data/input",
        "--dem"
    )
    foreach ($TileName in $DatasetDefaults.dem_tiles) {
        $FusionArguments += "/paper9-assets/dem/$TileName"
    }
    $FusionArguments += @(
        "--admin-reference", "/paper9-assets/admin.gpkg",
        "--log-dir", "/paper9-data/outputs/logs"
    )
    if ($ReferenceCountyCode -and $ReferenceCountyCode -ne $CountyCode) {
        $FusionArguments += @("--reference-county-code", $ReferenceCountyCode)
    }
    if ($DltbLayer) {
        $FusionArguments += @("--dltb-layer", $DltbLayer)
    }
    Invoke-Paper9Container -CommandArguments $FusionArguments -MountSpecifications $Mounts
    Write-RuntimeConfig

    Write-Host "Fusion completed for dataset=${Dataset}: $InputDir"
    Write-Warning "PDT, ecological redline, and permanent basic farmland were not evaluated. Results are for exploratory technical validation only."
}

function Invoke-Pipeline {
    param([switch]$DryRun)
    Assert-FusedInputs
    Write-RuntimeConfig
    $Arguments = @("python", "scripts/run_full_pipeline.py", $RuntimeConfigContainer, "--log-dir", "/paper9-data/outputs/logs")
    if ($DryRun) {
        $Arguments += "--dry-run"
    }
    Invoke-Paper9Container -CommandArguments $Arguments
}

Initialize-DataDirectories
Initialize-DockerRuntime

switch ($Action) {
    "fuse" {
        Invoke-Fusion
    }
    "all" {
        Invoke-Fusion
        Invoke-Pipeline
    }
    "check" {
        Invoke-Paper9Container -CommandArguments @("python", "scripts/00_check_env.py", "--include-notebook")
        Invoke-Paper9Container -CommandArguments @("python", "-m", "pytest", "tests", "-q")
        Invoke-Paper9Container -CommandArguments @("python", "-m", "paper9_mnr.cli", "check-config", $TemplateConfigContainer)
    }
    "check-config" {
        $ConfigToCheck = if (Test-Path -LiteralPath $RuntimeConfigHost) { $RuntimeConfigContainer } else { $TemplateConfigContainer }
        Invoke-Paper9Container -CommandArguments @("python", "-m", "paper9_mnr.cli", "check-config", $ConfigToCheck)
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
        Invoke-Paper9Container -CommandArguments @("python", "scripts/05_audit.py", $RuntimeConfigContainer, "--write")
    }
}
