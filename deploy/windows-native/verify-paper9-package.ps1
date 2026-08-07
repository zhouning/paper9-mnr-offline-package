[CmdletBinding()]
param(
    [string]$BundleRoot = ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..")))
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$ChecksumFile = Join-Path $BundleRoot "SHA256SUMS.txt"
if (-not (Test-Path -LiteralPath $ChecksumFile -PathType Leaf)) {
    throw "Checksum manifest is missing: $ChecksumFile"
}

$Failures = New-Object System.Collections.Generic.List[string]
$RuntimeRelocated = Test-Path -LiteralPath (Join-Path $BundleRoot "runtime\.paper9-conda-unpacked")
$SkippedRuntimeFiles = 0
foreach ($Line in [IO.File]::ReadAllLines($ChecksumFile)) {
    if ([string]::IsNullOrWhiteSpace($Line)) {
        continue
    }
    if ($Line -notmatch '^([0-9a-fA-F]{64}) \*(.+)$') {
        $Failures.Add("Malformed checksum line: $Line")
        continue
    }
    $Expected = $Matches[1].ToLowerInvariant()
    $RelativePath = $Matches[2]
    if ($RuntimeRelocated -and $RelativePath.StartsWith("runtime\", [StringComparison]::OrdinalIgnoreCase)) {
        $SkippedRuntimeFiles += 1
        continue
    }
    $Target = Join-Path $BundleRoot $RelativePath
    if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
        $Failures.Add("Missing file: $RelativePath")
        continue
    }
    $Actual = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected) {
        $Failures.Add("Checksum mismatch: $RelativePath")
    }
}

if ($Failures.Count -gt 0) {
    $Failures | ForEach-Object { Write-Error $_ }
    exit 2
}

if ($RuntimeRelocated) {
    Write-Warning "The portable runtime has already been relocated by conda-unpack; skipped $SkippedRuntimeFiles mutable runtime files. Application, DEM, reference, and documentation files were still verified."
}
Write-Host "Package checksums verified: $ChecksumFile"
exit 0
