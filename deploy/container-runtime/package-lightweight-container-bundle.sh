#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Assemble a lightweight Paper9 container image deployment bundle.

Usage:
  package-lightweight-container-bundle.sh --arch amd64 --image-tar PATH --dem-dir DIR [--out PATH] [options]

Options:
  --image-ref REF                 Container image reference recorded in MANIFEST.json.
  --dem-dir DIR                   Directory containing offline DEM tiles and DEM_MANIFEST.json.
  --package-version VERSION       Package version. Default: 0.3.2.
  --algorithm-name NAME           Algorithm name. Default: paper9v2.
  --algorithm-version VERSION     Algorithm version. Default: 2.2.2.
  --cpu-compatibility VALUE       CPU compatibility note. Default: legacy-x86_64-without-x86-64-v2.
  --git-commit COMMIT             Git commit recorded in MANIFEST.json. Default: unknown.

Example:
  ./deploy/container-runtime/package-lightweight-container-bundle.sh \
    --arch amd64 \
    --image-tar dist/paper9-mnr-offline-paper9v2-2.2.2-legacy-linux-amd64.tar \
    --image-ref paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 \
    --dem-dir dist/dem/copernicus_glo30 \
    --out dist/paper9-mnr-offline-container-paper9v2-2.2.2-legacy-amd64.tar.gz
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

arch=""
image_tar=""
dem_dir=""
out=""
package_version="0.3.2"
algorithm_name="paper9v2"
algorithm_version="2.2.2"
cpu_compatibility="legacy-x86_64-without-x86-64-v2"
git_commit="unknown"
image_ref=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --arch)
      arch="${2:-}"
      shift 2
      ;;
    --image-tar)
      image_tar="${2:-}"
      shift 2
      ;;
    --dem-dir)
      dem_dir="${2:-}"
      shift 2
      ;;
    --out)
      out="${2:-}"
      shift 2
      ;;
    --image-ref)
      image_ref="${2:-}"
      shift 2
      ;;
    --package-version)
      package_version="${2:-}"
      shift 2
      ;;
    --algorithm-name)
      algorithm_name="${2:-}"
      shift 2
      ;;
    --algorithm-version)
      algorithm_version="${2:-}"
      shift 2
      ;;
    --cpu-compatibility)
      cpu_compatibility="${2:-}"
      shift 2
      ;;
    --git-commit)
      git_commit="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[ "$arch" = "amd64" ] || die "--arch must be amd64 for the legacy lightweight bundle"
[ -f "$image_tar" ] || die "image tar not found: $image_tar"
[ -d "$dem_dir" ] || die "DEM directory not found: $dem_dir"
[ -f "$dem_dir/DEM_MANIFEST.json" ] || die "DEM manifest not found: $dem_dir/DEM_MANIFEST.json"
for dem_tile_name in \
  Copernicus_DSM_COG_10_N29_00_E104_00_DEM.tif \
  Copernicus_DSM_COG_10_N29_00_E105_00_DEM.tif \
  Copernicus_DSM_COG_10_N29_00_E106_00_DEM.tif; do
  [ -f "$dem_dir/$dem_tile_name" ] || die "required DEM tile not found: $dem_dir/$dem_tile_name"
done
[ -n "$package_version" ] || die "--package-version must not be empty"
[ -n "$algorithm_name" ] || die "--algorithm-name must not be empty"
[ -n "$algorithm_version" ] || die "--algorithm-version must not be empty"
[ -n "$cpu_compatibility" ] || die "--cpu-compatibility must not be empty"
[ -n "$git_commit" ] || die "--git-commit must not be empty"

image_ref="${image_ref:-paper9-mnr-offline:${algorithm_name}-${algorithm_version}-legacy-amd64}"
out="${out:-dist/paper9-mnr-offline-container-${algorithm_name}-${algorithm_version}-legacy-amd64.tar.gz}"

case "$out" in
  *.tar.gz|*.tgz) ;;
  *) die "--out must end with .tar.gz or .tgz" ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
admin_reference="$repo_root/reference/admin/xiangzhen_dongxing_bishan.gpkg"
[ -f "$admin_reference" ] || die "bundled township reference not found: $admin_reference"
bundle_name="$(basename "${out%.tar.gz}")"
if [ "$bundle_name" = "$(basename "$out")" ]; then
  bundle_name="$(basename "${out%.tgz}")"
fi
staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/paper9-lightweight-container.XXXXXX")"
staging="$staging_parent/$bundle_name"

cleanup() {
  rm -rf "$staging_parent"
}
trap cleanup EXIT

mkdir -p "$staging/images" "$staging/bin" "$staging/configs" "$staging/docs" "$staging/notebooks" "$staging/dem/copernicus_glo30" "$staging/reference/admin"

image_tar_name="paper9-mnr-offline-${algorithm_name}-${algorithm_version}-legacy-linux-amd64.tar"
cp "$image_tar" "$staging/images/$image_tar_name"
cp "$repo_root/deploy/container-runtime/run-paper9-container.sh" "$staging/bin/"
cp -R "$repo_root/configs"/. "$staging/configs/"
cp -R "$repo_root/docs"/. "$staging/docs/"
cp -R "$repo_root/notebooks"/. "$staging/notebooks/"
cp "$repo_root/README.md" "$staging/README.md"
cp -R "$dem_dir"/. "$staging/dem/copernicus_glo30/"
cp -R "$repo_root/reference/admin"/. "$staging/reference/admin/"

build_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "$staging/MANIFEST.json" <<MANIFEST
{
  "package_version": "${package_version}",
  "algorithm_name": "${algorithm_name}",
  "algorithm_version": "${algorithm_version}",
  "image_ref": "${image_ref}",
  "platform": "linux/${arch}",
  "cpu_compatibility": "${cpu_compatibility}",
  "git_commit": "${git_commit}",
  "build_time": "${build_time}",
  "default_config": "configs/paper9v22_authority_constraints.yml",
  "image_tar": "images/${image_tar_name}",
  "offline_dem": {
    "directory": "dem/copernicus_glo30",
    "manifest": "dem/copernicus_glo30/DEM_MANIFEST.json",
    "required_for_fusion": true
  },
  "offline_admin_reference": {
    "path": "reference/admin/xiangzhen_dongxing_bishan.gpkg",
    "layer": "admin_reference",
    "feature_count": 44,
    "source_date": "2021-06-22",
    "role": "township name and spatial reference only"
  }
}
MANIFEST

cat > "$staging/README_CONTAINER_IMAGE_BUNDLE.md" <<README
# Paper9v2.2 legacy amd64 container bundle

Image reference: \`${image_ref}\`

CPU compatibility: \`${cpu_compatibility}\`. This bundle is intended for older or virtualized x86_64 hosts that do not expose the full x86-64-v2 flag set, including hosts missing \`sse4_1\` or \`popcnt\`.

The Copernicus DEM GLO-30 tiles and their source/checksum manifest are under \`dem/copernicus_glo30/\`. The 44-feature Dongxing/Bishan township reference is under \`reference/admin/\`. The \`fuse\` action selects both automatically; the customer does not download or name either dataset.

Load the image:

\`\`\`bash
docker load -i images/${image_tar_name}
\`\`\`

Fuse one county. These four FileGDB directory paths are the only customer data inputs:

\`\`\`bash
./bin/run-paper9-container.sh fuse \\
  --dltb-gdb /path/to/dltb.gdb \\
  --pdt-gdb /path/to/pdt.gdb \\
  --eco-redline-gdb /path/to/stbhhx.gdb \\
  --permanent-basic-farmland-gdb /path/to/yjjbntbhtb.gdb
\`\`\`

The wrapper selects Docker, amd64, the release image, the bundled DEM, the
township reference, and an isolated data root automatically. It prints the exact
\`check\`, \`dry-run\`, \`run\`, and \`audit\` commands after fusion.

Detailed host, fusion, pipeline, and failure diagnostics are written under
\`DATA_ROOT/outputs/logs/\`. Copy that complete directory out of the
air-gapped network when support analysis is required.
README

cat > "$staging/PACKAGE_STATUS.md" <<STATUS
# Paper9v2.2 legacy amd64 package status

- Package version: \`${package_version}\`
- Algorithm: \`${algorithm_name}\` \`${algorithm_version}\`
- Image: \`${image_ref}\`
- CPU compatibility: \`${cpu_compatibility}\`
- Image tar: \`images/${image_tar_name}\`
- Offline DEM: \`dem/copernicus_glo30/\`
- Offline township reference: \`reference/admin/xiangzhen_dongxing_bishan.gpkg\`
- Detailed diagnostics: \`DATA_ROOT/outputs/logs/\`
STATUS

(
  cd "$staging"
  checksum_tool=""
  if command -v sha256sum >/dev/null 2>&1; then
    checksum_tool="sha256sum"
  elif command -v shasum >/dev/null 2>&1; then
    checksum_tool="shasum -a 256"
  else
    die "sha256sum or shasum is required"
  fi

  find . -type f ! -name SHA256SUMS.txt | LC_ALL=C sort | while IFS= read -r file; do
    $checksum_tool "$file"
  done > SHA256SUMS.txt
)

mkdir -p "$(dirname "$out")"
tar -C "$staging_parent" -czf "$out" "$bundle_name"
echo "Wrote $out"
