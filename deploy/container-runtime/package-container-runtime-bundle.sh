#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Assemble an air-gapped Paper9 container-runtime deployment bundle.

Usage:
  package-container-runtime-bundle.sh --arch amd64|arm64 --image-tar PATH --runtime-packages-dir DIR --dem-dir DIR [--out PATH] [options]

Options:
  --image-ref REF                 Container image reference recorded in MANIFEST.json.
  --dem-dir DIR                   Directory containing offline DEM tiles and DEM_MANIFEST.json.
  --package-version VERSION       Package version. Default: 0.3.2.
  --algorithm-name NAME           Algorithm name. Default: paper9v2.
  --algorithm-version VERSION     Algorithm version. Default: 2.2.2.
  --git-commit COMMIT             Git commit recorded in MANIFEST.json. Default: unknown.

Example:
  ./deploy/container-runtime/package-container-runtime-bundle.sh \
    --arch amd64 \
    --image-tar dist/paper9-mnr-offline-paper9v2-2.2.2-legacy-linux-amd64.tar \
    --image-ref paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 \
    --runtime-packages-dir /tmp/docker-rpms/rocky9-amd64 \
    --dem-dir dist/dem/copernicus_glo30 \
    --out dist/paper9-mnr-container-runtime-paper9v2-2.2.2-legacy-amd64.tar.gz
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

arch=""
image_tar=""
runtime_packages_dir=""
dem_dir=""
out=""
package_version="0.3.2"
algorithm_name="paper9v2"
algorithm_version="2.2.2"
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
    --runtime-packages-dir)
      runtime_packages_dir="${2:-}"
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

[ "$arch" = "amd64" ] || [ "$arch" = "arm64" ] || die "--arch must be amd64 or arm64"
[ -f "$image_tar" ] || die "image tar not found: $image_tar"
[ -d "$runtime_packages_dir" ] || die "runtime packages directory not found: $runtime_packages_dir"
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
[ -n "$git_commit" ] || die "--git-commit must not be empty"

if [ -z "$image_ref" ]; then
  case "$arch" in
    amd64) image_ref="paper9-mnr-offline:${algorithm_name}-${algorithm_version}-legacy-amd64" ;;
    arm64) image_ref="paper9-mnr-offline:${algorithm_name}-${algorithm_version}-arm64" ;;
  esac
fi

case "$arch" in
  amd64) default_bundle_name="paper9-mnr-container-runtime-${algorithm_name}-${algorithm_version}-legacy-amd64" ;;
  arm64) default_bundle_name="paper9-mnr-container-runtime-${algorithm_name}-${algorithm_version}-arm64" ;;
esac
out="${out:-dist/${default_bundle_name}.tar.gz}"

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
staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/paper9-container-runtime.XXXXXX")"
staging="$staging_parent/$bundle_name"

cleanup() {
  rm -rf "$staging_parent"
}
trap cleanup EXIT

mkdir -p "$staging/images" "$staging/runtime-packages" "$staging/bin" "$staging/docs" "$staging/configs" "$staging/dem/copernicus_glo30" "$staging/reference/admin"

cp "$image_tar" "$staging/images/paper9-mnr-offline-linux-${arch}.tar"
cp -R "$runtime_packages_dir"/. "$staging/runtime-packages/"
cp "$repo_root/deploy/container-runtime/install-container-runtime.sh" "$staging/bin/"
cp "$repo_root/deploy/container-runtime/run-paper9-container.sh" "$staging/bin/"
cp "$repo_root/docs/12_container_runtime_airgap.md" "$staging/docs/"
cp -R "$repo_root/configs"/. "$staging/configs/"
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
  "git_commit": "${git_commit}",
  "build_time": "${build_time}",
  "default_config": "configs/paper9v22_authority_constraints.yml",
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

cat > "$staging/README.txt" <<README
Paper9 MNR container-runtime offline bundle (${arch})

1. Install container runtime from local packages:
   sudo ./bin/install-container-runtime.sh --runtime docker --packages-dir runtime-packages

2. Load the image:
   docker load -i images/paper9-mnr-offline-linux-${arch}.tar

3. Fuse the four customer FileGDB directories. These are the only customer data parameters; Docker, architecture, image, DEM, township reference, and data root are automatic:
   ./bin/run-paper9-container.sh fuse --dltb-gdb /path/to/dltb.gdb --pdt-gdb /path/to/pdt.gdb --eco-redline-gdb /path/to/stbhhx.gdb --permanent-basic-farmland-gdb /path/to/yjjbntbhtb.gdb

4. Copy the four exact check/dry-run/run/audit commands printed after fusion.

5. When support analysis is required, copy the complete directory:
   DATA_ROOT/outputs/logs/
README

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
