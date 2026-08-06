#!/bin/bash
# Build and push the ASL-AI compute image to Docker Hub.
#
# Usage:
#   export DOCKERHUB_USER=phindagijimana
#   export DOCKERHUB_TOKEN=<docker hub access token>
#   ./container/push_dockerhub.sh [tag]
#
# On URMC OOD/compute nodes, podman/docker build often fails (no subuid).
# This script falls back to Kaniko via Apptainer, which works on the cluster.
#
# Default image: docker.io/phindagijimana/asl-ai-compute:<tag>
# Override with ASL_AI_DOCKER_IMAGE (full name without tag).
# Force Kaniko: ASL_AI_USE_KANIKO=1 ./container/push_dockerhub.sh

set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
tag="${1:-latest}"
image_base="${ASL_AI_DOCKER_IMAGE:-docker.io/phindagijimana/asl-ai-compute}"
image="${image_base}:${tag}"
user="${DOCKERHUB_USER:-phindagijimana}"

build_tmp="$repo_dir/compute/build-tmp"
mkdir -p "$build_tmp" "$repo_dir/compute/cache"
export APPTAINER_TMPDIR="$build_tmp"
export APPTAINER_CACHEDIR="$repo_dir/compute/cache"
export PROOT_TMP_DIR="$build_tmp"
export TMPDIR="$build_tmp"

apptainer_cmd() {
  command -v apptainer >/dev/null || command -v singularity >/dev/null || {
    echo "Apptainer/Singularity required for Kaniko fallback" >&2
    exit 3
  }
  command -v apptainer || command -v singularity
}

docker_config_dir() {
  local cfg="$build_tmp/kaniko-docker-config"
  mkdir -p "$cfg"
  if [[ -n "${DOCKERHUB_TOKEN:-}" ]]; then
    local auth
    auth="$(printf '%s:%s' "$user" "$DOCKERHUB_TOKEN" | base64 | tr -d '\n')"
    cat > "$cfg/config.json" <<EOF
{
  "auths": {
    "https://index.docker.io/v1/": {
      "auth": "$auth"
    }
  }
}
EOF
  elif [[ -f "${HOME}/.config/containers/auth.json" ]]; then
    cp "${HOME}/.config/containers/auth.json" "$cfg/config.json"
  elif [[ -f "${XDG_RUNTIME_DIR:-}/containers/auth.json" ]]; then
    cp "${XDG_RUNTIME_DIR}/containers/auth.json" "$cfg/config.json"
  else
    cat >&2 <<EOF
Docker Hub credentials required. Either:

  export DOCKERHUB_USER=$user
  export DOCKERHUB_TOKEN=<access token from hub.docker.com/settings/security>

or run once:

  podman login docker.io

Then rerun: ./container/push_dockerhub.sh $tag
EOF
    exit 4
  fi
  echo "$cfg"
}

push_with_kaniko() {
  local apptainer kaniko_cfg
  apptainer="$(apptainer_cmd)"
  kaniko_cfg="$(docker_config_dir)"
  local kaniko_image="${ASL_AI_KANIKO_IMAGE:-docker://gcr.io/kaniko-project/executor:v1.23.2}"

  echo "Building and pushing with Kaniko (Apptainer)..."
  echo "  image:  $image"
  echo "  latest: ${image_base}:latest"
  echo "  tmp:    $build_tmp"

  "$apptainer" run --cleanenv \
    --bind "$repo_dir:/workspace" \
    --bind "$kaniko_cfg:/kaniko/.docker:ro" \
    --bind /mnt/nfs \
    "$kaniko_image" \
    --dockerfile=/workspace/container/Dockerfile \
    --context="dir:///workspace" \
    --destination="$image" \
    --destination="${image_base}:latest" \
    --cache=false
}

push_with_podman_or_docker() {
  local builder=()
  if command -v docker >/dev/null; then
    builder=(docker)
  elif command -v podman >/dev/null; then
    export CONTAINERS_STORAGE_DRIVER=vfs
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/xdg-runtime-${USER:-nobody}}"
    mkdir -p "$XDG_RUNTIME_DIR"
    local podman_root="${PODMAN_ROOT:-/tmp/podman-root-${USER:-nobody}}"
    mkdir -p "$podman_root"
    builder=(podman --root "$podman_root")
  else
    return 1
  fi

  echo "Building $image with ${builder[*]} ..."
  if ! "${builder[@]}" build \
    -f "$repo_dir/container/Dockerfile" \
    -t "$image" \
    -t "${image_base}:latest" \
    "$repo_dir"; then
    return 1
  fi

  if [[ -n "${DOCKERHUB_TOKEN:-}" ]]; then
    echo "$DOCKERHUB_TOKEN" | "${builder[@]}" login docker.io -u "$user" --password-stdin
  fi

  "${builder[@]}" push "$image"
  "${builder[@]}" push "${image_base}:latest"
}

main() {
  echo "Repo: $repo_dir"
  echo "Target: $image (+ ${image_base}:latest)"
  echo

  if [[ "${ASL_AI_USE_KANIKO:-}" == 1 ]]; then
    push_with_kaniko
  elif push_with_podman_or_docker 2>/dev/null; then
    :
  else
    echo "podman/docker build unavailable on this host (common on OOD - no subuid)." >&2
    echo "Falling back to Kaniko via Apptainer..." >&2
    push_with_kaniko
  fi

  echo
  echo "Published: $image"
  echo "Apptainer pull example:"
  echo "  apptainer pull docker://phindagijimana/asl-ai-compute:${tag}"
}

main "$@"
