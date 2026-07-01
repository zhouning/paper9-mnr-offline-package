#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Assemble a lightweight Paper9 container image deployment bundle.

Usage:
  package-lightweight-container-bundle.sh --arch amd64 --image-tar PATH [--out PATH] [options]

Options:
  --image-ref REF                 Container image reference recorded in MANIFEST.json.
  --package-version VERSION       Package version. Default: 0.2.1.
  --algorithm-name NAME           Algorithm name. Default: paper9v2.
  --algorithm-version VERSION     Algorithm version. Default: 2.1.0.
  --cpu-compatibility VALUE       CPU compatibility note. Default: legacy-x86_64-without-x86-64-v2.
  --git-commit COMMIT             Git commit recorded in MANIFEST.json. Default: unknown.

Example:
  ./deploy/container-runtime/package-lightweight-container-bundle.sh \
    --arch amd64 \
    --image-tar dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar \
    --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
    --out dist/paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

arch=""
image_tar=""
out=""
package_version="0.2.1"
algorithm_name="paper9v2"
algorithm_version="2.1.0"
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
[ -n "$package_version" ] || die "--package-version must not be empty"
[ -n "$algorithm_name" ] || die "--algorithm-name must not be empty"
[ -n "$algorithm_version" ] || die "--algorithm-version must not be empty"
[ -n "$cpu_compatibility" ] || die "--cpu-compatibility must not be empty"
[ -n "$git_commit" ] || die "--git-commit must not be empty"

image_ref="${image_ref:-paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64}"
out="${out:-dist/paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz}"

case "$out" in
  *.tar.gz|*.tgz) ;;
  *) die "--out must end with .tar.gz or .tgz" ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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

mkdir -p "$staging/images" "$staging/bin" "$staging/configs" "$staging/docs" "$staging/notebooks"

cp "$image_tar" "$staging/images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar"
cp "$repo_root/deploy/container-runtime/run-paper9-container.sh" "$staging/bin/"
cp -R "$repo_root/configs"/. "$staging/configs/"
cp -R "$repo_root/docs"/. "$staging/docs/"
cp -R "$repo_root/notebooks"/. "$staging/notebooks/"
cp "$repo_root/README.md" "$staging/README.md"

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
  "default_config": "configs/paper9v2_no_net_loss_authority_slope.yml",
  "image_tar": "images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar"
}
MANIFEST

cat > "$staging/README_CONTAINER_IMAGE_BUNDLE.md" <<README
# Paper9v2.1 legacy amd64 container bundle

Image reference: \`${image_ref}\`

CPU compatibility: \`${cpu_compatibility}\`. This bundle is intended for older or virtualized x86_64 hosts that do not expose the full x86-64-v2 flag set, including hosts missing \`sse4_1\` or \`popcnt\`.

Load and check:

\`\`\`bash
./bin/run-paper9-container.sh check --runtime docker --arch amd64 \\
  --image-ref ${image_ref} \\
  --image-tar images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar \\
  --config configs/paper9v2_no_net_loss_authority_slope.yml \\
  --data-root /data/paper9
\`\`\`
README

cat > "$staging/PACKAGE_STATUS.md" <<STATUS
# Paper9v2.1 legacy amd64 package status

- Package version: \`${package_version}\`
- Algorithm: \`${algorithm_name}\` \`${algorithm_version}\`
- Image: \`${image_ref}\`
- CPU compatibility: \`${cpu_compatibility}\`
- Image tar: \`images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar\`
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
