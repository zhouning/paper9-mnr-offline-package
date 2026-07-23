#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Run Paper9 MNR offline package through Docker or Podman on an air-gapped host.

Usage:
  run-paper9-container.sh ACTION [options]

Actions:
  fuse          Fuse four county FileGDB inputs with the bundled offline DEM.
  check         Run environment check, tests, and config validation.
  check-config  Run config validation only.
  dry-run      Print full pipeline commands without executing them.
  run          Execute the full pipeline.
  audit        Audit generated outputs.
  notebook     Start JupyterLab for interactive review and visualization.
  shell        Open a shell in the container.

Options:
  --runtime docker|podman       Container runtime. Default: auto-detect.
  --arch amd64|arm64            Image architecture. Default: host architecture.
  --image-tar PATH              Image tar to load before running.
  --image NAME                  Image repository. Default: paper9-mnr-offline.
  --image-ref REF               Full image reference. Overrides --image and --arch tag selection.
  --config PATH                 Config path inside container. Default: configs/paper9v22_authority_constraints.yml
  --data-root DIR               Host data root. Default: auto per DLTB for fuse; /data/paper9 otherwise.
  --input-dir DIR               Host input dir. Default: DATA_ROOT/input
  --working-dir DIR             Host working dir. Default: DATA_ROOT/working
  --outputs-dir DIR             Host outputs dir. Default: DATA_ROOT/outputs
  --volume-suffix SUFFIX        Volume mode suffix such as ,Z for SELinux hosts.
  --notebook-port PORT          Host port for notebook mode. Default: 8888.
  --notebook-token TOKEN        Jupyter token for notebook mode. Default: paper9.
  --dltb-gdb DIR                DLTB FileGDB directory. Required for fuse.
  --pdt-gdb DIR                 PDT FileGDB directory. Required for fuse.
  --eco-redline-gdb DIR         Ecological-redline FileGDB directory. Required for fuse.
  --permanent-basic-farmland-gdb DIR
                                 Permanent-basic-farmland FileGDB. Required for fuse.
  --dem-dir DIR                 Bundled DEM directory. Default: BUNDLE_ROOT/dem/copernicus_glo30
  --admin-reference PATH        Bundled township reference. Default: BUNDLE_ROOT/reference/admin/xiangzhen_dongxing_bishan.gpkg

Examples:
  ./run-paper9-container.sh fuse --dltb-gdb /authority/dltb.gdb --pdt-gdb /authority/pdt.gdb --eco-redline-gdb /authority/stbhhx.gdb --permanent-basic-farmland-gdb /authority/yjjbnt.gdb
  ./run-paper9-container.sh check --runtime docker --arch amd64 --image-ref paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 --image-tar images/paper9-mnr-offline-paper9v2-2.2.2-legacy-linux-amd64.tar
  ./run-paper9-container.sh dry-run --runtime podman --arch amd64 --image-ref paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 --data-root /data/paper9
  ./run-paper9-container.sh run --runtime docker --arch amd64 --image-ref paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 --config configs/paper9v22_authority_constraints.yml
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

host_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    *) die "unsupported host architecture: $(uname -m)" ;;
  esac
}

detect_runtime() {
  if command -v docker >/dev/null 2>&1; then
    echo "docker"
  elif command -v podman >/dev/null 2>&1; then
    echo "podman"
  else
    die "docker or podman is required"
  fi
}

default_image_ref() {
  local repo="$1"
  local image_arch="$2"
  case "$image_arch" in
    amd64) echo "${repo}:paper9v2-2.2.2-legacy-amd64" ;;
    arm64) echo "${repo}:paper9v2-2.2.2-arm64" ;;
    *) die "unsupported image architecture: $image_arch" ;;
  esac
}

original_args=("$@")
action="${1:-}"
[ -n "$action" ] || { usage; exit 1; }
shift || true

runtime=""
arch=""
image="paper9-mnr-offline"
image_ref=""
image_tar=""
config="configs/paper9v22_authority_constraints.yml"
data_root=""
input_dir=""
working_dir=""
outputs_dir=""
volume_suffix=""
notebook_port="8888"
notebook_token="paper9"
dltb_gdb=""
pdt_gdb=""
eco_redline_gdb=""
permanent_basic_farmland_gdb=""
dem_dir=""
admin_reference=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --runtime)
      runtime="${2:-}"
      shift 2
      ;;
    --arch)
      arch="${2:-}"
      shift 2
      ;;
    --image)
      image="${2:-}"
      shift 2
      ;;
    --image-ref)
      image_ref="${2:-}"
      shift 2
      ;;
    --image-tar)
      image_tar="${2:-}"
      shift 2
      ;;
    --config)
      config="${2:-}"
      shift 2
      ;;
    --data-root)
      data_root="${2:-}"
      shift 2
      ;;
    --input-dir)
      input_dir="${2:-}"
      shift 2
      ;;
    --working-dir)
      working_dir="${2:-}"
      shift 2
      ;;
    --outputs-dir)
      outputs_dir="${2:-}"
      shift 2
      ;;
    --volume-suffix)
      volume_suffix="${2:-}"
      shift 2
      ;;
    --notebook-port)
      notebook_port="${2:-}"
      shift 2
      ;;
    --notebook-token)
      notebook_token="${2:-}"
      shift 2
      ;;
    --dltb-gdb)
      dltb_gdb="${2:-}"
      shift 2
      ;;
    --pdt-gdb)
      pdt_gdb="${2:-}"
      shift 2
      ;;
    --eco-redline-gdb)
      eco_redline_gdb="${2:-}"
      shift 2
      ;;
    --permanent-basic-farmland-gdb)
      permanent_basic_farmland_gdb="${2:-}"
      shift 2
      ;;
    --dem-dir)
      dem_dir="${2:-}"
      shift 2
      ;;
    --admin-reference)
      admin_reference="${2:-}"
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

case "$action" in
  fuse|check|check-config|dry-run|run|audit|notebook|shell) ;;
  *) die "unknown action: $action" ;;
esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$action" = "fuse" ] && [ -z "$data_root" ]; then
  if [ -n "$dltb_gdb" ]; then
    dltb_label="$(basename "${dltb_gdb%.gdb}")"
    dltb_parent="$(basename "$(dirname "$dltb_gdb")")"
    dltb_path_key="$(printf '%s' "$dltb_gdb" | cksum | awk '{print $1}')"
    county_key="$(printf '%s-%s-%s' "$dltb_parent" "$dltb_label" "$dltb_path_key" | tr -cs '[:alnum:]._' '-')"
    data_root="$PWD/paper9-data/${county_key%-}"
  else
    data_root="$PWD/paper9-data/unresolved-fuse"
  fi
fi
data_root="${data_root:-/data/paper9}"
input_dir="${input_dir:-$data_root/input}"
working_dir="${working_dir:-$data_root/working}"
outputs_dir="${outputs_dir:-$data_root/outputs}"
mkdir -p "$input_dir" "$working_dir" "$outputs_dir" "$outputs_dir/logs"

host_run_id="${PAPER9_WRAPPER_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
host_log="${PAPER9_WRAPPER_LOG_PATH:-$outputs_dir/logs/container-wrapper-${host_run_id}.log}"
if [ "${PAPER9_WRAPPER_LOGGING_ACTIVE:-0}" != "1" ]; then
  script_path="$script_dir/$(basename "${BASH_SOURCE[0]}")"
  set +e
  env \
    PAPER9_WRAPPER_LOGGING_ACTIVE=1 \
    PAPER9_WRAPPER_LOG_PATH="$host_log" \
    PAPER9_WRAPPER_RUN_ID="$host_run_id" \
    "$script_path" "${original_args[@]}" 2>&1 | tee -a "$host_log"
  wrapper_status=${PIPESTATUS[0]}
  set -e
  exit "$wrapper_status"
fi
log_exit() {
  status=$?
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) HOST RUN END run_id=$host_run_id action=$action status=$status log=$host_log"
}
trap log_exit EXIT
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) HOST RUN START run_id=$host_run_id action=$action"
echo "data_root=$data_root input_dir=$input_dir working_dir=$working_dir outputs_dir=$outputs_dir"
echo "host_uname=$(uname -a)"

[ -n "$runtime" ] || runtime="$(detect_runtime)"
[ "$runtime" = "docker" ] || [ "$runtime" = "podman" ] || die "--runtime must be docker or podman"
command -v "$runtime" >/dev/null 2>&1 || die "$runtime is not installed"

[ -n "$arch" ] || arch="$(host_arch)"
[ "$arch" = "amd64" ] || [ "$arch" = "arm64" ] || die "--arch must be amd64 or arm64"

current_arch="$(host_arch)"
[ "$current_arch" = "$arch" ] || die "host architecture is $current_arch, but --arch is $arch"
echo "runtime=$runtime runtime_version=$($runtime --version 2>&1 | head -1) arch=$arch"

if [ "$action" = "fuse" ]; then
  [ -d "$dltb_gdb" ] || die "--dltb-gdb is not a FileGDB directory: $dltb_gdb"
  [ -d "$pdt_gdb" ] || die "--pdt-gdb is not a FileGDB directory: $pdt_gdb"
  [ -d "$eco_redline_gdb" ] || die "--eco-redline-gdb is not a FileGDB directory: $eco_redline_gdb"
  [ -d "$permanent_basic_farmland_gdb" ] || die "--permanent-basic-farmland-gdb is not a FileGDB directory: $permanent_basic_farmland_gdb"
  dltb_gdb="$(cd "$dltb_gdb" && pwd -P)"
  pdt_gdb="$(cd "$pdt_gdb" && pwd -P)"
  eco_redline_gdb="$(cd "$eco_redline_gdb" && pwd -P)"
  permanent_basic_farmland_gdb="$(cd "$permanent_basic_farmland_gdb" && pwd -P)"
  dem_dir="${dem_dir:-$script_dir/../dem/copernicus_glo30}"
  [ -d "$dem_dir" ] || die "offline DEM directory not found: $dem_dir"
  dem_dir="$(cd "$dem_dir" && pwd -P)"
  [ -f "$dem_dir/DEM_MANIFEST.json" ] || die "offline DEM manifest not found: $dem_dir/DEM_MANIFEST.json"

  if [ -z "$admin_reference" ]; then
    bundle_admin_reference="$script_dir/../reference/admin/xiangzhen_dongxing_bishan.gpkg"
    repo_admin_reference="$script_dir/../../reference/admin/xiangzhen_dongxing_bishan.gpkg"
    if [ -f "$bundle_admin_reference" ]; then
      admin_reference="$bundle_admin_reference"
    else
      admin_reference="$repo_admin_reference"
    fi
  fi
  [ -f "$admin_reference" ] || die "bundled township reference not found: $admin_reference"
  admin_reference="$(cd "$(dirname "$admin_reference")" && pwd -P)/$(basename "$admin_reference")"

  dem_tile_names=(
    Copernicus_DSM_COG_10_N29_00_E104_00_DEM.tif
    Copernicus_DSM_COG_10_N29_00_E105_00_DEM.tif
    Copernicus_DSM_COG_10_N29_00_E106_00_DEM.tif
  )
  for dem_tile_name in "${dem_tile_names[@]}"; do
    [ -f "$dem_dir/$dem_tile_name" ] || die "required offline DEM tile not found: $dem_dir/$dem_tile_name"
  done

  echo "dltb_gdb=$dltb_gdb"
  echo "pdt_gdb=$pdt_gdb role=quality_control_only"
  echo "eco_redline_gdb=$eco_redline_gdb role=bidirectional_exchange_lock"
  echo "permanent_basic_farmland_gdb=$permanent_basic_farmland_gdb role=bidirectional_exchange_lock"
  echo "dem_dir=$dem_dir role=continuous_slope_source"
  echo "admin_reference=$admin_reference role=township_name_and_spatial_reference_only"
fi

tag="${image_ref:-$(default_image_ref "$image" "$arch")}"

if [ -n "$image_tar" ]; then
  [ -f "$image_tar" ] || die "image tar not found: $image_tar"
  "$runtime" load -i "$image_tar"
fi

if [ "$runtime" = "docker" ]; then
  "$runtime" image inspect "$tag" >/dev/null || die "image not loaded: $tag"
else
  "$runtime" image exists "$tag" || die "image not loaded: $tag"
fi

input_mode="ro"
[ "$action" != "fuse" ] || input_mode="rw"
volume_args=(
  -v "${input_dir}:/app/data/input:${input_mode}${volume_suffix}"
  -v "${working_dir}:/app/data/working:rw${volume_suffix}"
  -v "${outputs_dir}:/app/outputs:rw${volume_suffix}"
)

run_container() {
  "$runtime" run --rm --network none -e PAPER9_LOG_DIR=/app/outputs/logs -e PAPER9_IMAGE_REF="$tag" "${volume_args[@]}" "$tag" "$@"
}

case "$action" in
  fuse)
    dem_container_paths=()
    for dem_tile_name in "${dem_tile_names[@]}"; do
      dem_container_paths+=("/app/data/dem/$dem_tile_name")
    done
    fusion_volume_args=(
      -v "${dltb_gdb}:/app/authority/dltb.gdb:ro${volume_suffix}"
      -v "${pdt_gdb}:/app/authority/pdt.gdb:ro${volume_suffix}"
      -v "${eco_redline_gdb}:/app/authority/eco_redline.gdb:ro${volume_suffix}"
      -v "${permanent_basic_farmland_gdb}:/app/authority/permanent_basic_farmland.gdb:ro${volume_suffix}"
      -v "${dem_dir}:/app/data/dem:ro${volume_suffix}"
      -v "${admin_reference}:/app/reference/xiangzhen_dongxing_bishan.gpkg:ro${volume_suffix}"
    )
    volume_args+=("${fusion_volume_args[@]}")
    run_container python scripts/fuse_authoritative_county_inputs.py \
      --dltb-gdb /app/authority/dltb.gdb \
      --pdt-gdb /app/authority/pdt.gdb \
      --eco-redline-gdb /app/authority/eco_redline.gdb \
      --permanent-basic-farmland-gdb /app/authority/permanent_basic_farmland.gdb \
      --output-dir /app/data/input \
      --dem "${dem_container_paths[@]}" \
      --admin-reference /app/reference/xiangzhen_dongxing_bishan.gpkg \
      --admin-reference-layer admin_reference \
      --log-dir /app/outputs/logs \
      --run-id "$host_run_id"
    echo "Fusion complete. Data root: $data_root"
    echo "Detailed logs: $outputs_dir/logs"
    echo "Copy and run the following commands in order:"
    echo "$0 check --data-root '$data_root' --image-ref '$tag'"
    echo "$0 dry-run --data-root '$data_root' --image-ref '$tag'"
    echo "$0 run --data-root '$data_root' --image-ref '$tag'"
    echo "$0 audit --data-root '$data_root' --image-ref '$tag'"
    ;;
  check)
    run_container python scripts/00_check_env.py --include-notebook
    run_container python -m pytest tests -q
    run_container python -m paper9_mnr.cli check-config "$config"
    ;;
  check-config)
    run_container python -m paper9_mnr.cli check-config "$config"
    ;;
  dry-run)
    run_container python scripts/run_full_pipeline.py "$config" --dry-run
    ;;
  run)
    run_container python scripts/run_full_pipeline.py "$config"
    ;;
  audit)
    run_container python scripts/05_audit.py "$config" --write
    ;;
  notebook)
    echo "JupyterLab URL: http://127.0.0.1:${notebook_port}/lab?token=${notebook_token}"
    "$runtime" run --rm --network none \
      -e PAPER9_LOG_DIR=/app/outputs/logs \
      -e PAPER9_CONFIG="${config}" \
      -e PAPER9_IMAGE_REF="$tag" \
      -p "${notebook_port}:8888" \
      "${volume_args[@]}" \
      "$tag" \
      jupyter lab \
        --ip=0.0.0.0 \
        --port=8888 \
        --no-browser \
        --allow-root \
        --notebook-dir=/app/notebooks \
        --ServerApp.token="${notebook_token}"
    ;;
  shell)
    "$runtime" run --rm -it -e PAPER9_LOG_DIR=/app/outputs/logs -e PAPER9_IMAGE_REF="$tag" "${volume_args[@]}" "$tag" /bin/bash
    ;;
esac
