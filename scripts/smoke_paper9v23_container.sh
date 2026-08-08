#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Run the Paper9v2.3 linux/amd64 image against the built-in Dongxing data.

Usage:
  smoke_paper9v23_container.sh [--image REF] [--data-root DIR] [--platform PLATFORM]

Defaults:
  --image paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64
  --data-root /tmp/paper9-v23-container-smoke-<timestamp>
  --platform linux/amd64
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

image="paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64"
data_root=""
platform="linux/amd64"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --image)
      image="${2:-}"
      shift 2
      ;;
    --data-root)
      data_root="${2:-}"
      shift 2
      ;;
    --platform)
      platform="${2:-}"
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

command -v docker >/dev/null 2>&1 || die "docker is required"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dltb="$repo_root/dist/datasets/dongxing/DLTB_with_slope.gpkg"
dem_dir="$repo_root/dist/dem/copernicus_glo30"
admin="$repo_root/reference/admin/xiangzhen_dongxing_bishan.gpkg"

[ -f "$dltb" ] || die "Dongxing DLTB is missing: $dltb"
[ -f "$dem_dir/DEM_MANIFEST.json" ] || die "DEM manifest is missing: $dem_dir/DEM_MANIFEST.json"
[ -f "$admin" ] || die "administrative reference is missing: $admin"

if [ -z "$data_root" ]; then
  data_root="${TMPDIR:-/tmp}/paper9-v23-container-smoke-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "$data_root"
data_root="$(cd "$data_root" && pwd -P)"
if find "$data_root" -mindepth 1 -maxdepth 1 | grep -q .; then
  die "data root must be empty: $data_root"
fi
mkdir -p "$data_root/input" "$data_root/working" "$data_root/outputs/logs"

docker image inspect "$image" >/dev/null || die "image is not loaded: $image"

common_args=(
  run --rm
  --network none
  --platform "$platform"
  -e PAPER9_OFFLINE=1
  -e "PAPER9_IMAGE_REF=$image"
  -e PYTHONIOENCODING=utf-8
  -e PYTHONUTF8=1
  --mount "type=bind,source=$data_root,target=/paper9-data"
)

run_image() {
  docker "${common_args[@]}" "$image" "$@"
}

echo "image=$image"
echo "platform=$platform"
echo "data_root=$data_root"
docker image inspect --format \
  'version={{index .Config.Labels "org.opencontainers.image.version"}} algorithm={{index .Config.Labels "io.paper9.algorithm.version"}} revision={{index .Config.Labels "org.opencontainers.image.revision"}} profile={{index .Config.Labels "io.paper9.input.profile"}}' \
  "$image"

run_image python scripts/00_check_env.py --include-notebook
run_image python -m pytest tests -q
run_image python -m paper9_mnr.cli check-config /app/configs/paper9v23_dongxing_container_smoke.yml

asset_args=(
  --mount "type=bind,source=$dltb,target=/paper9-assets/dltb.gpkg,readonly"
  --mount "type=bind,source=$dem_dir,target=/paper9-assets/dem,readonly"
  --mount "type=bind,source=$admin,target=/paper9-assets/admin.gpkg,readonly"
)

docker "${common_args[@]}" "${asset_args[@]}" "$image" \
  python scripts/fuse_dltb_dem_county.py \
    --dltb-source /paper9-assets/dltb.gpkg \
    --county-code 511011 \
    --county-name 四川省内江市东兴区 \
    --output-dir /paper9-data/input \
    --dem \
      /paper9-assets/dem/Copernicus_DSM_COG_10_N29_00_E104_00_DEM.tif \
      /paper9-assets/dem/Copernicus_DSM_COG_10_N29_00_E105_00_DEM.tif \
    --admin-reference /paper9-assets/admin.gpkg \
    --log-dir /paper9-data/outputs/logs

run_image python scripts/render_dltb_only_runtime_config.py \
  --template /app/configs/paper9v23_dongxing_container_smoke.yml \
  --output /paper9-data/paper9v23_dongxing_container_smoke.runtime.yml \
  --data-root /paper9-data \
  --run-name dongxing-container-smoke

run_image python scripts/run_full_pipeline.py \
  /paper9-data/paper9v23_dongxing_container_smoke.runtime.yml \
  --log-dir /paper9-data/outputs/logs

run_image python -c '
import json
from pathlib import Path
root = Path("/paper9-data")
availability = json.loads((root / "input/input_availability.json").read_text())
audit = json.loads((root / "outputs/audit_summary.json").read_text())
assert availability["profile"] == "dltb_dem_only"
assert availability["regulatory_compliance_evaluated"] is False
assert audit["all_expected_outputs_exist"] is True
assert audit["constraint_status"]["hard_constraint_passed"] is True
assert audit["input_profile_status"]["regulatory_compliance_claim_allowed"] is False
print(json.dumps({
    "data_root": str(root),
    "all_expected_outputs_exist": audit["all_expected_outputs_exist"],
    "hard_constraint_passed": audit["constraint_status"]["hard_constraint_passed"],
    "regulatory_compliance_claim_allowed": audit["input_profile_status"]["regulatory_compliance_claim_allowed"],
}, ensure_ascii=False))
'

echo "Paper9v2.3 container smoke passed: $data_root"
