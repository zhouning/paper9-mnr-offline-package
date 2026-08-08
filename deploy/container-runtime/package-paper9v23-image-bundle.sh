#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Assemble the Paper9v2.3 Docker image and built-in data into one offline bundle.

Usage:
  package-paper9v23-image-bundle.sh --image-tar PATH [--out PATH] [--git-commit COMMIT]

Defaults:
  --out dist/paper9-mnr-offline-container-paper9v2-2.3.0-legacy-amd64.tar.gz
  --image-ref paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

image_tar=""
out="dist/paper9-mnr-offline-container-paper9v2-2.3.0-legacy-amd64.tar.gz"
image_ref="paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64"
git_commit="unknown"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --image-tar)
      image_tar="${2:-}"
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
    --git-commit)
      git_commit="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[ -f "$image_tar" ] || die "image tar not found: $image_tar"
case "$out" in
  *.tar.gz|*.tgz) ;;
  *) die "--out must end with .tar.gz or .tgz" ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
datasets="$repo_root/dist/datasets"
dem_common="$repo_root/dist/dem/copernicus_glo30"
dem_zhongning="$repo_root/dist/dem/copernicus_glo30_zhongning"
admin_dir="$repo_root/reference/admin"

required_paths=(
  "$datasets/MANIFEST.json"
  "$datasets/dongxing/DLTB_with_slope.gpkg"
  "$datasets/bishan/DLTB_with_slope.gpkg"
  "$dem_common/DEM_MANIFEST.json"
  "$dem_zhongning/DEM_MANIFEST.json"
  "$admin_dir/xiangzhen_dongxing_bishan.gpkg"
  "$admin_dir/xiangzhen_zhongning.gpkg"
)
for required_path in "${required_paths[@]}"; do
  [ -f "$required_path" ] || die "required bundle asset is missing: $required_path"
done

bundle_name="$(basename "${out%.tar.gz}")"
if [ "$bundle_name" = "$(basename "$out")" ]; then
  bundle_name="$(basename "${out%.tgz}")"
fi
staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/paper9-v23-container.XXXXXX")"
staging="$staging_parent/$bundle_name"

cleanup() {
  rm -rf "$staging_parent"
}
trap cleanup EXIT

mkdir -p \
  "$staging/images" \
  "$staging/bin" \
  "$staging/configs" \
  "$staging/datasets/dongxing" \
  "$staging/datasets/bishan" \
  "$staging/dem/copernicus_glo30" \
  "$staging/dem/copernicus_glo30_zhongning" \
  "$staging/reference/admin" \
  "$staging/docs"

image_tar_name="paper9-mnr-offline-paper9v2-2.3.0-legacy-linux-amd64.tar"
cp "$image_tar" "$staging/images/$image_tar_name"
cp "$repo_root/deploy/windows-docker/run-paper9v23-docker.ps1" "$staging/bin/"
cp "$repo_root/scripts/smoke_paper9v23_container.sh" "$staging/bin/"
cp "$repo_root/configs"/paper9v23_*.yml "$staging/configs/"
cp "$datasets/MANIFEST.json" "$staging/datasets/"
cp "$datasets/dongxing/DLTB_with_slope.gpkg" "$staging/datasets/dongxing/"
cp "$datasets/bishan/DLTB_with_slope.gpkg" "$staging/datasets/bishan/"
cp -R "$dem_common"/. "$staging/dem/copernicus_glo30/"
cp -R "$dem_zhongning"/. "$staging/dem/copernicus_glo30_zhongning/"
cp "$admin_dir/xiangzhen_dongxing_bishan.gpkg" "$staging/reference/admin/"
cp "$admin_dir/xiangzhen_zhongning.gpkg" "$staging/reference/admin/"
cp "$admin_dir/MANIFEST.json" "$staging/reference/admin/"
cp "$admin_dir/MANIFEST_ZHONGNING.json" "$staging/reference/admin/"
cp "$repo_root/docs/21_paper9v23_dltb_only_release.md" "$staging/docs/"
cp "$repo_root/docs/24_paper9v23_windows_docker.md" "$staging/docs/"

if command -v sha256sum >/dev/null 2>&1; then
  image_sha256="$(sha256sum "$image_tar" | awk '{print $1}')"
else
  image_sha256="$(shasum -a 256 "$image_tar" | awk '{print $1}')"
fi
build_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "$staging/MANIFEST.json" <<MANIFEST
{
  "schema_version": "paper9.container_bundle.v2",
  "package_version": "0.4.0",
  "algorithm_name": "paper9v2",
  "algorithm_version": "2.3.0",
  "input_profile": "dltb_dem_only",
  "image_ref": "${image_ref}",
  "platform": "linux/amd64",
  "cpu_compatibility": "legacy-x86_64-without-x86-64-v2",
  "git_commit": "${git_commit}",
  "build_time_utc": "${build_time}",
  "image_tar": {
    "path": "images/${image_tar_name}",
    "sha256": "${image_sha256}"
  },
  "built_in_datasets": ["dongxing", "bishan"],
  "zhongning_dltb_bundled": false,
  "runtime_network_required": false,
  "regulatory_compliance_claim_allowed": false
}
MANIFEST

cat > "$staging/README.txt" <<README
Paper9v2.3 Docker offline bundle

1. Use Docker Desktop in Linux containers mode on Windows x64.
2. In Windows PowerShell, load the image:
   docker load -i .\images\${image_tar_name}
3. Check the image and package:
   .\bin\run-paper9v23-docker.ps1 check -Dataset dongxing
4. Run the reduced Dongxing end-to-end smoke:
   .\bin\run-paper9v23-docker.ps1 all -Dataset dongxing -Config configs/paper9v23_dongxing_container_smoke.yml
5. Run the formal Dongxing parameters:
   .\bin\run-paper9v23-docker.ps1 all -Dataset dongxing
6. Zhongning requires a customer FileGDB:
   .\bin\run-paper9v23-docker.ps1 all -Dataset zhongning -DltbSource E:\authority\DLTB.gdb -DataRoot D:\paper9-data\zhongning

PDT, ecological redline, and permanent basic farmland are not evaluated in this profile.
Outputs are for exploratory technical validation only.
README

(
  cd "$staging"
  if command -v sha256sum >/dev/null 2>&1; then
    find . -type f ! -name SHA256SUMS.txt | LC_ALL=C sort | while IFS= read -r file; do
      sha256sum "$file"
    done > SHA256SUMS.txt
  else
    find . -type f ! -name SHA256SUMS.txt | LC_ALL=C sort | while IFS= read -r file; do
      shasum -a 256 "$file"
    done > SHA256SUMS.txt
  fi
)

mkdir -p "$(dirname "$out")"
tar -C "$staging_parent" -czf "$out" "$bundle_name"
echo "Wrote $out"
