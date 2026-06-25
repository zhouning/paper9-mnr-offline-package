#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Assemble an air-gapped Paper9 container-runtime deployment bundle.

Usage:
  package-container-runtime-bundle.sh --arch amd64|arm64 --image-tar PATH --runtime-packages-dir DIR --out PATH

Example:
  ./deploy/container-runtime/package-container-runtime-bundle.sh \
    --arch amd64 \
    --image-tar dist/paper9-mnr-offline-linux-amd64.tar \
    --runtime-packages-dir /tmp/docker-rpms/rocky9-amd64 \
    --out dist/paper9-mnr-container-runtime-amd64.tar.gz
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

arch=""
image_tar=""
runtime_packages_dir=""
out=""

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
    --out)
      out="${2:-}"
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
[ -n "$out" ] || die "--out is required"

case "$out" in
  *.tar.gz|*.tgz) ;;
  *) die "--out must end with .tar.gz or .tgz" ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bundle_name="paper9-mnr-container-runtime-${arch}"
staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/paper9-container-runtime.XXXXXX")"
staging="$staging_parent/$bundle_name"

cleanup() {
  rm -rf "$staging_parent"
}
trap cleanup EXIT

mkdir -p "$staging/images" "$staging/runtime-packages" "$staging/bin" "$staging/docs"

cp "$image_tar" "$staging/images/paper9-mnr-offline-linux-${arch}.tar"
cp -R "$runtime_packages_dir"/. "$staging/runtime-packages/"
cp "$repo_root/deploy/container-runtime/install-container-runtime.sh" "$staging/bin/"
cp "$repo_root/deploy/container-runtime/run-paper9-container.sh" "$staging/bin/"
cp "$repo_root/docs/12_container_runtime_airgap.md" "$staging/docs/"

cat > "$staging/README.txt" <<README
Paper9 MNR container-runtime offline bundle (${arch})

1. Install container runtime from local packages:
   sudo ./bin/install-container-runtime.sh --runtime docker --packages-dir runtime-packages

2. Prepare data:
   mkdir -p /data/paper9/input /data/paper9/working /data/paper9/outputs
   Place DLTB_with_authority_slope.gpkg, admin_units.gpkg, and DEM_placeholder.tif under /data/paper9/input.

3. Load image and verify:
   ./bin/run-paper9-container.sh check --runtime docker --arch ${arch} --image-tar images/paper9-mnr-offline-linux-${arch}.tar

4. Run:
   ./bin/run-paper9-container.sh dry-run --runtime docker --arch ${arch}
   ./bin/run-paper9-container.sh run --runtime docker --arch ${arch}
   ./bin/run-paper9-container.sh audit --runtime docker --arch ${arch}
README

mkdir -p "$(dirname "$out")"
tar -C "$staging_parent" -czf "$out" "$bundle_name"
echo "Wrote $out"
