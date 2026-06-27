#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Run Paper9 MNR offline package through Docker or Podman on an air-gapped host.

Usage:
  run-paper9-container.sh ACTION [options]

Actions:
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
  --config PATH                 Config path inside container. Default: configs/paper9v2_no_net_loss_authority_slope.yml
  --data-root DIR               Host data root. Default: /data/paper9
  --input-dir DIR               Host input dir. Default: DATA_ROOT/input
  --working-dir DIR             Host working dir. Default: DATA_ROOT/working
  --outputs-dir DIR             Host outputs dir. Default: DATA_ROOT/outputs
  --volume-suffix SUFFIX        Volume mode suffix such as ,Z for SELinux hosts.
  --notebook-port PORT          Host port for notebook mode. Default: 8888.
  --notebook-token TOKEN        Jupyter token for notebook mode. Default: paper9.

Examples:
  ./run-paper9-container.sh check --runtime docker --arch amd64 --image-tar images/paper9-mnr-offline-linux-amd64.tar
  ./run-paper9-container.sh dry-run --runtime podman --data-root /data/paper9
  ./run-paper9-container.sh run --runtime docker --config configs/paper9v2_no_net_loss_authority_slope.yml
  ./run-paper9-container.sh notebook --runtime docker --arch amd64 --config configs/paper9v2_no_net_loss_authority_slope.yml --notebook-port 8888
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

action="${1:-}"
[ -n "$action" ] || { usage; exit 1; }
shift || true

runtime=""
arch=""
image="paper9-mnr-offline"
image_ref=""
image_tar=""
config="configs/paper9v2_no_net_loss_authority_slope.yml"
data_root="/data/paper9"
input_dir=""
working_dir=""
outputs_dir=""
volume_suffix=""
notebook_port="8888"
notebook_token="paper9"

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
  check|check-config|dry-run|run|audit|notebook|shell) ;;
  *) die "unknown action: $action" ;;
esac

[ -n "$runtime" ] || runtime="$(detect_runtime)"
[ "$runtime" = "docker" ] || [ "$runtime" = "podman" ] || die "--runtime must be docker or podman"
command -v "$runtime" >/dev/null 2>&1 || die "$runtime is not installed"

[ -n "$arch" ] || arch="$(host_arch)"
[ "$arch" = "amd64" ] || [ "$arch" = "arm64" ] || die "--arch must be amd64 or arm64"

current_arch="$(host_arch)"
[ "$current_arch" = "$arch" ] || die "host architecture is $current_arch, but --arch is $arch"

input_dir="${input_dir:-$data_root/input}"
working_dir="${working_dir:-$data_root/working}"
outputs_dir="${outputs_dir:-$data_root/outputs}"

mkdir -p "$input_dir" "$working_dir" "$outputs_dir"

tag="${image_ref:-$image:$arch}"

if [ -n "$image_tar" ]; then
  [ -f "$image_tar" ] || die "image tar not found: $image_tar"
  "$runtime" load -i "$image_tar"
fi

if [ "$runtime" = "docker" ]; then
  "$runtime" image inspect "$tag" >/dev/null || die "image not loaded: $tag"
else
  "$runtime" image exists "$tag" || die "image not loaded: $tag"
fi

volume_args=(
  -v "${input_dir}:/app/data/input:ro${volume_suffix}"
  -v "${working_dir}:/app/data/working:rw${volume_suffix}"
  -v "${outputs_dir}:/app/outputs:rw${volume_suffix}"
)

run_container() {
  "$runtime" run --rm -e PAPER9_LOG_DIR=/app/outputs/logs -e PAPER9_IMAGE_REF="$tag" "${volume_args[@]}" "$tag" "$@"
}

case "$action" in
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
    "$runtime" run --rm \
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
