#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Install Docker or Podman from local RPM/DEB packages on an air-gapped Linux host.

Usage:
  install-container-runtime.sh --runtime docker|podman --packages-dir DIR [--skip-start]

Examples:
  ./install-container-runtime.sh --runtime docker --packages-dir runtime-packages/amd64/rocky9
  ./install-container-runtime.sh --runtime podman --packages-dir runtime-packages/arm64/kylin

Notes:
  - DIR must contain all RPM/DEB dependency packages for the target OS and CPU architecture.
  - This script never downloads packages from the network.
  - Root is required; if sudo exists, the script re-runs itself through sudo.
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

runtime=""
packages_dir=""
skip_start=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --runtime)
      runtime="${2:-}"
      shift 2
      ;;
    --packages-dir)
      packages_dir="${2:-}"
      shift 2
      ;;
    --skip-start)
      skip_start=1
      shift
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

[ "$runtime" = "docker" ] || [ "$runtime" = "podman" ] || die "--runtime must be docker or podman"
[ -n "$packages_dir" ] || die "--packages-dir is required"
[ -d "$packages_dir" ] || die "packages directory not found: $packages_dir"

if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || die "root is required and sudo is not available"
  sudo_args=(--runtime "$runtime" --packages-dir "$packages_dir")
  [ "$skip_start" -eq 1 ] && sudo_args+=(--skip-start)
  exec sudo "$0" "${sudo_args[@]}"
fi

runtime_binary="$runtime"
if [ "$runtime" = "docker" ] && command -v docker >/dev/null 2>&1; then
  echo "docker is already installed: $(docker --version)"
  installed=1
elif [ "$runtime" = "podman" ] && command -v podman >/dev/null 2>&1; then
  echo "podman is already installed: $(podman --version)"
  installed=1
else
  installed=0
fi

install_rpm_packages() {
  rpm_count=$(find "$packages_dir" -maxdepth 1 -type f -name '*.rpm' | wc -l | tr -d ' ')
  [ "$rpm_count" -gt 0 ] || die "no .rpm packages found under $packages_dir"

  if command -v dnf >/dev/null 2>&1; then
    dnf install -y --disablerepo='*' "$packages_dir"/*.rpm
  elif command -v yum >/dev/null 2>&1; then
    yum localinstall -y --disablerepo='*' "$packages_dir"/*.rpm
  else
    rpm -Uvh --replacepkgs "$packages_dir"/*.rpm
  fi
}

install_deb_packages() {
  deb_count=$(find "$packages_dir" -maxdepth 1 -type f -name '*.deb' | wc -l | tr -d ' ')
  [ "$deb_count" -gt 0 ] || die "no .deb packages found under $packages_dir"

  dpkg -i "$packages_dir"/*.deb || apt-get -o Dir::Cache::archives="$packages_dir" -f install -y --no-download
}

if [ "$installed" -eq 0 ]; then
  if find "$packages_dir" -maxdepth 1 -type f -name '*.rpm' | grep -q .; then
    install_rpm_packages
  elif find "$packages_dir" -maxdepth 1 -type f -name '*.deb' | grep -q .; then
    install_deb_packages
  else
    die "packages directory must contain .rpm or .deb files"
  fi
fi

if [ "$runtime" = "docker" ]; then
  command -v docker >/dev/null 2>&1 || die "docker binary not found after installation"
  runtime_binary="docker"
  if [ "$skip_start" -eq 0 ] && command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now docker
  fi
  docker version
else
  command -v podman >/dev/null 2>&1 || die "podman binary not found after installation"
  runtime_binary="podman"
  podman info
fi

echo "Container runtime is ready: $runtime_binary"
