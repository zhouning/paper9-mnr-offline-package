[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimeArchive,
    [string]$EnvironmentLock,
    [string]$DemDir,
    [string]$AdminReference,
    [string]$Output,
    [string]$GitCommit = "unknown"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$RuntimeArchive = (Resolve-Path -LiteralPath $RuntimeArchive).Path
$DemDir = if ($DemDir) {
    (Resolve-Path -LiteralPath $DemDir).Path
} else {
    Join-Path $RepoRoot "dist\dem\copernicus_glo30_zhongning"
}
$AdminReference = if ($AdminReference) {
    (Resolve-Path -LiteralPath $AdminReference).Path
} else {
    Join-Path $RepoRoot "reference\admin\xiangzhen_zhongning.gpkg"
}
$Output = if ($Output) {
    [IO.Path]::GetFullPath($Output)
} else {
    Join-Path $RepoRoot "dist\paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64.zip"
}

if (-not $Output.EndsWith(".zip", [StringComparison]::OrdinalIgnoreCase)) {
    throw "-Output must end with .zip."
}
if (Test-Path -LiteralPath $Output) {
    throw "Output already exists: $Output"
}
if (-not (Test-Path -LiteralPath $DemDir -PathType Container)) {
    throw "DEM directory is missing: $DemDir"
}
if (-not (Test-Path -LiteralPath (Join-Path $DemDir "DEM_MANIFEST.json") -PathType Leaf)) {
    throw "DEM manifest is missing: $DemDir\DEM_MANIFEST.json"
}
$RequiredDemTiles = @(
    "Copernicus_DSM_COG_10_N36_00_E105_00_DEM.tif",
    "Copernicus_DSM_COG_10_N36_00_E106_00_DEM.tif",
    "Copernicus_DSM_COG_10_N37_00_E105_00_DEM.tif",
    "Copernicus_DSM_COG_10_N37_00_E106_00_DEM.tif"
)
foreach ($Tile in $RequiredDemTiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $DemDir $Tile) -PathType Leaf)) {
        throw "Required DEM tile is missing: $Tile"
    }
}
if (-not (Test-Path -LiteralPath $AdminReference -PathType Leaf)) {
    throw "Administrative reference is missing: $AdminReference"
}

$BundleName = [IO.Path]::GetFileNameWithoutExtension($Output)
$StagingParent = Join-Path ([IO.Path]::GetTempPath()) ("paper9-windows-" + [Guid]::NewGuid().ToString("N"))
$Staging = Join-Path $StagingParent $BundleName
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

try {
    foreach ($Directory in @(
        $Staging,
        (Join-Path $Staging "app"),
        (Join-Path $Staging "bin"),
        (Join-Path $Staging "runtime"),
        (Join-Path $Staging "datasets"),
        (Join-Path $Staging "dem\copernicus_glo30"),
        (Join-Path $Staging "dem\copernicus_glo30_zhongning"),
        (Join-Path $Staging "reference\admin"),
        (Join-Path $Staging "docs")
    )) {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    }

    Expand-Archive -LiteralPath $RuntimeArchive -DestinationPath (Join-Path $Staging "runtime")
    foreach ($DirectoryName in @("src", "scripts", "configs")) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot $DirectoryName) -Destination (Join-Path $Staging "app") -Recurse
    }
    Get-ChildItem -LiteralPath (Join-Path $Staging "app") -Directory -Filter "__pycache__" -Recurse |
        Remove-Item -Recurse -Force
    foreach ($FileName in @("pyproject.toml", "README.md")) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot $FileName) -Destination (Join-Path $Staging "app")
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "run-paper9-windows.ps1") -Destination (Join-Path $Staging "bin")
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "verify-paper9-package.ps1") -Destination (Join-Path $Staging "bin")
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "environment-windows-x86_64.yml") -Destination (Join-Path $Staging "docs")
    foreach ($DocName in @("21_paper9v23_dltb_only_release.md", "22_windows_native_airgap.md", "23_windows_native_validation_20260808.md", "26_windows_native_pre_extract_deployment.md")) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot "docs\$DocName") -Destination (Join-Path $Staging "docs")
    }
    Copy-Item -Path (Join-Path $DemDir "*") -Destination (Join-Path $Staging "dem\copernicus_glo30_zhongning") -Recurse
    $CommonDemDir = Join-Path $RepoRoot "dist\dem\copernicus_glo30"
    if (-not (Test-Path -LiteralPath (Join-Path $CommonDemDir "DEM_MANIFEST.json") -PathType Leaf)) {
        throw "Common Dongxing/Bishan DEM directory is missing: $CommonDemDir"
    }
    Copy-Item -Path (Join-Path $CommonDemDir "*") -Destination (Join-Path $Staging "dem\copernicus_glo30") -Recurse
    $SampleDatasetDir = Join-Path $RepoRoot "dist\datasets"
    if (-not (Test-Path -LiteralPath (Join-Path $SampleDatasetDir "MANIFEST.json") -PathType Leaf)) {
        throw "Built-in sample dataset manifest is missing: $SampleDatasetDir\MANIFEST.json"
    }
    Copy-Item -Path (Join-Path $SampleDatasetDir "*") -Destination (Join-Path $Staging "datasets") -Recurse
    Copy-Item -LiteralPath $AdminReference -Destination (Join-Path $Staging "reference\admin\xiangzhen_zhongning.gpkg")
    Copy-Item -LiteralPath (Join-Path $RepoRoot "reference\admin\MANIFEST_ZHONGNING.json") -Destination (Join-Path $Staging "reference\admin")
    Copy-Item -LiteralPath (Join-Path $RepoRoot "reference\admin\xiangzhen_dongxing_bishan.gpkg") -Destination (Join-Path $Staging "reference\admin")
    Copy-Item -LiteralPath (Join-Path $RepoRoot "reference\admin\MANIFEST.json") -Destination (Join-Path $Staging "reference\admin")
    if ($EnvironmentLock) {
        Copy-Item -LiteralPath (Resolve-Path -LiteralPath $EnvironmentLock).Path -Destination (Join-Path $Staging "docs\windows-runtime-explicit.txt")
    }

    $RuntimeHash = (Get-FileHash -LiteralPath $RuntimeArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    $Manifest = [ordered]@{
        schema_version = "paper9.windows_bundle.v1"
        package_version = "0.4.0"
        algorithm_name = "paper9v2"
        algorithm_version = "2.3.0"
        profile = "dltb_dem_only"
        evidence_tier = "exploratory_data_limited"
        decision_use = "exploratory_technical_validation_only"
        platform = "windows/x86_64"
        runtime = [ordered]@{
            type = "conda-pack-portable"
            archive_sha256 = $RuntimeHash
            target_python_or_conda_required = $false
            administrator_rights_required = $false
            container_required = $false
        }
        customer_inputs = @("province-wide DLTB containing county code 640521")
        unavailable_authority_data = [ordered]@{
            pdt = "not_provided_not_evaluated"
            eco_redline = "not_provided_not_evaluated"
            permanent_basic_farmland = "not_provided_not_evaluated"
        }
        offline_dem = [ordered]@{
            directories = @(
                "dem/copernicus_glo30_zhongning",
                "dem/copernicus_glo30"
            )
            manifests = @(
                "dem/copernicus_glo30_zhongning/DEM_MANIFEST.json",
                "dem/copernicus_glo30/DEM_MANIFEST.json"
            )
        }
        built_in_sample_datasets = [ordered]@{
            manifest = "datasets/MANIFEST.json"
            datasets = @("datasets/dongxing", "datasets/bishan")
        }
        offline_admin_reference = [ordered]@{
            path = "reference/admin/xiangzhen_zhongning.gpkg"
            layer = "admin_reference"
            county_code = "640521"
            feature_count = 13
        }
        default_config = "app/configs/paper9v23_zhongning_dltb_only.yml"
        git_commit = $GitCommit
        build_time_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    }
    [IO.File]::WriteAllText(
        (Join-Path $Staging "MANIFEST.json"),
        ($Manifest | ConvertTo-Json -Depth 8),
        $Utf8NoBom
    )

    $Readme = @"
Paper9v2.3 Zhongning Windows offline package

1. Extract this ZIP to a short local path, for example D:\paper9_zhongning.
2. Open Windows PowerShell 5.1+ in that directory. The target machine uses only
   PowerShell; cmd.exe, batch files, and WSL are not required. The complete manual is in
   docs\22_windows_native_airgap.md; the validation record is in
   docs\23_windows_native_validation_20260808.md.
3. Verify the outer ZIP hash, then verify the extracted package:
   Get-FileHash .\paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64.zip -Algorithm SHA256
   .\bin\verify-paper9-package.ps1
   .\bin\run-paper9-windows.ps1 check

Built-in data assets:
- Dongxing: DLTB, 2 DEM tiles, and 29 township reference polygons.
  Run: .\bin\run-paper9-windows.ps1 all -Dataset dongxing
- Bishan: DLTB, 1 DEM tile, and 15 township reference polygons. The bundled DLTB
  uses source code 500227 and maps to current reference code 500120.
  Run: .\bin\run-paper9-windows.ps1 all -Dataset bishan
- Zhongning: no DLTB is bundled; provide the customer DLTB with -DltbSource.
  The package includes 4 DEM tiles and 13 township reference polygons for county
  code 640521.
  The source must be a complete Esri File Geodatabase directory ending in .gdb;
  a single file, archive, or GeoPackage is rejected by the PowerShell wrapper.


For a customer DLTB:
   .\bin\run-paper9-windows.ps1 all -DltbSource "E:\authority\DLTB.gdb" -DataRoot "E:\paper9-work\640521"
After fusion, use the same -DataRoot for separate stages if needed:
   .\bin\run-paper9-windows.ps1 dry-run -DataRoot "E:\paper9-work\640521"
   .\bin\run-paper9-windows.ps1 run -DataRoot "E:\paper9-work\640521"
   .\bin\run-paper9-windows.ps1 audit -DataRoot "E:\paper9-work\640521"

No Docker, Python, Conda, administrator rights, cmd.exe, or network connection is required
on the target machine. Results are exploratory because PDT, ecological redline,
and permanent basic farmland are not evaluated.
"@
    [IO.File]::WriteAllText((Join-Path $Staging "README.txt"), $Readme, $Utf8NoBom)

    $ChecksumLines = New-Object System.Collections.Generic.List[string]
    Get-ChildItem -LiteralPath $Staging -File -Recurse |
        Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
        Sort-Object FullName |
        ForEach-Object {
            $Relative = $_.FullName.Substring($Staging.Length + 1)
            $Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            $ChecksumLines.Add("$Hash *$Relative")
        }
    [IO.File]::WriteAllLines((Join-Path $Staging "SHA256SUMS.txt"), $ChecksumLines, $Utf8NoBom)

    New-Item -ItemType Directory -Path (Split-Path $Output -Parent) -Force | Out-Null
    # Archive the bundle contents so extraction places bin\, runtime\, and app\
    # directly under the operator-selected deployment directory.
    Compress-Archive -Path (Join-Path $Staging "*") -DestinationPath $Output -CompressionLevel Optimal
    $BundleHash = (Get-FileHash -LiteralPath $Output -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$Output.sha256", "$BundleHash *$([IO.Path]::GetFileName($Output))`r`n", $Utf8NoBom)
    Copy-Item -LiteralPath (Join-Path $RepoRoot "docs\26_windows_native_pre_extract_deployment.md") -Destination (Join-Path (Split-Path $Output -Parent) "$BundleName-pre-extract-deployment.md") -Force
    Write-Host "Wrote Windows bundle: $Output"
    Write-Host "SHA-256: $BundleHash"
} finally {
    if (Test-Path -LiteralPath $StagingParent) {
        Remove-Item -LiteralPath $StagingParent -Recurse -Force
    }
}
