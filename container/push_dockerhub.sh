#!/bin/bash
# Build and push the ASL-AI compute image to Docker Hub.
#
# Usage:
#   podman login docker.io -u phindagijimana321
#   ./container/push_dockerhub.sh [tag]
#
# Or:
#   export DOCKERHUB_USER=phindagijimana321
#   export DOCKERHUB_TOKEN=dckr_pat_xxxxxxxx
#   ./container/push_dockerhub.sh [tag]
#
# On URMC OOD nodes (no subuid), podman/docker build and skopeo SIF push
# usually fail. The script falls back to Kaniko via Apptainer with a writable
# --kaniko-dir (fixes "open /kaniko/Dockerfile: read-only file system").
#
# Default image: docker.io/phindagijimana321/asl-ai-compute:<tag>

set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
tag="${1:-latest}"
image_base="${ASL_AI_DOCKER_IMAGE:-docker.io/phindagijimana321/asl-ai-compute}"
image="${image_base}:${tag}"
user="${DOCKERHUB_USER:-phindagijimana321}"
sif="${ASL_AI_COMPUTE_SIF:-$repo_dir/compute/asl_ai_compute.sif}"

build_tmp="$repo_dir/compute/build-tmp"
mkdir -p "$build_tmp" "$repo_dir/compute/cache"
export APPTAINER_TMPDIR="$build_tmp"
export APPTAINER_CACHEDIR="$repo_dir/compute/cache"
export PROOT_TMP_DIR="$build_tmp"
export TMPDIR="$build_tmp"

apptainer_cmd() {
  command -v apptainer >/dev/null || command -v singularity >/dev/null || {
    echo "Apptainer/Singularity required on this host" >&2
    exit 3
  }
  command -v apptainer || command -v singularity
}

resolve_authfile() {
  if [[ -n "${DOCKERHUB_TOKEN:-}" ]]; then
    if [[ "$DOCKERHUB_TOKEN" == *"your Docker Hub"* ]] || [[ "$DOCKERHUB_TOKEN" == "<"* ]]; then
      echo "DOCKERHUB_TOKEN looks like a placeholder — paste your real token." >&2
      exit 4
    fi
    write_docker_authfile
    return 0
  fi
  local candidates=(
    "${DOCKER_AUTHFILE:-}"
    "${XDG_RUNTIME_DIR:-}/containers/auth.json"
    "/run/user/$(id -u)/containers/auth.json"
    "${HOME}/.config/containers/auth.json"
    "${XDG_CONFIG_HOME:-}/containers/auth.json"
    "${HOME}/.docker/config.json"
  )
  local c
  for c in "${candidates[@]}"; do
    if [[ -n "$c" && -f "$c" ]]; then
      echo "Using credentials from: $c" >&2
      echo "$c"
      return 0
    fi
  done
  cat >&2 <<EOF
Docker Hub credentials required. Either:

  export DOCKERHUB_USER=$user
  export DOCKERHUB_TOKEN=dckr_pat_xxxxxxxx

or log in once:

  podman login docker.io -u $user

Create a token at: https://hub.docker.com/settings/security
EOF
  exit 4
}

write_docker_authfile() {
  local authfile="$build_tmp/docker-auth.json"
  local auth
  auth="$(printf '%s:%s' "$user" "$DOCKERHUB_TOKEN" | base64 | tr -d '\n')"
  cat > "$authfile" <<EOF
{
  "auths": {
    "https://index.docker.io/v1/": {
      "auth": "$auth"
    }
  }
}
EOF
  echo "$authfile"
}

ensure_sif() {
  local apptainer def
  apptainer="$(apptainer_cmd)"
  def="$repo_dir/container/asl_ai_compute.def"
  [[ -f "$def" ]] || { echo "Missing Apptainer def: $def" >&2; exit 4; }

  if [[ -f "$sif" ]]; then
    echo "Using existing SIF: $sif"
    return 0
  fi

  echo "Building SIF (first time; ~2–5 min)..."
  echo "  def: $def"
  echo "  out: $sif"
  "$apptainer" build --force "$sif" "$def"
}

ensure_kaniko_sif() {
  local apptainer kaniko_sif="$repo_dir/compute/cache/kaniko-executor.sif"
  apptainer="$(apptainer_cmd)"
  local kaniko_ref="${ASL_AI_KANIKO_IMAGE:-docker://gcr.io/kaniko-project/executor:v1.23.2}"

  if [[ ! -f "$kaniko_sif" ]]; then
    echo "Pulling Kaniko executor (one-time)..."
    "$apptainer" pull "$kaniko_sif" "$kaniko_ref"
  fi
  echo "$kaniko_sif"
}

push_sif_to_dockerhub() {
  command -v skopeo >/dev/null || return 1
  local authfile uri
  authfile="$(resolve_authfile)"
  uri="docker://${image_base#docker.io/}:${tag}"

  echo "Pushing SIF to Docker Hub via skopeo..."
  echo "  sif:  $sif"
  echo "  uri:  $uri"

  skopeo copy --authfile "$authfile" "sif:$sif" "$uri"

  if [[ "$tag" != "latest" ]]; then
    echo "Tagging latest..."
    skopeo copy --authfile "$authfile" "sif:$sif" "docker://${image_base#docker.io/}:latest"
  fi
}

push_with_kaniko() {
  local apptainer kaniko_sif kaniko_work kaniko_cfg authfile
  apptainer="$(apptainer_cmd)"
  kaniko_sif="$(ensure_kaniko_sif)"
  kaniko_work="$build_tmp/kaniko-work"
  kaniko_cfg="$build_tmp/kaniko-docker-config"
  mkdir -p "$kaniko_work" "$kaniko_cfg"
  authfile="$(resolve_authfile)"
  cp "$authfile" "$kaniko_cfg/config.json"

  echo "Building and pushing with Kaniko (Apptainer)..."
  echo "  image:      $image"
  echo "  kaniko-dir: $kaniko_work"
  echo "  executor:   $kaniko_sif"

  # Writable --kaniko-dir avoids "open /kaniko/Dockerfile: read-only file system".
  # Arguments after "--" are passed to the Kaniko executor entrypoint.
  "$apptainer" run --cleanenv \
    --env "DOCKER_CONFIG=/docker-config" \
    --env "KANIKO_DIR=/kaniko-work" \
    --bind "$repo_dir:/workspace" \
    --bind "$kaniko_cfg:/docker-config:ro" \
    --bind "$kaniko_work:/kaniko-work" \
    --bind /mnt/nfs \
    "$kaniko_sif" \
    -- \
    --kaniko-dir=/kaniko-work \
    --dockerfile=container/Dockerfile \
    --context=dir:///workspace \
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

  local authfile
  authfile="$(resolve_authfile)"
  if [[ -n "${DOCKERHUB_TOKEN:-}" ]]; then
    echo "$DOCKERHUB_TOKEN" | "${builder[@]}" login docker.io -u "$user" --password-stdin
  fi
  "${builder[@]}" push --authfile "$authfile" "$image"
  "${builder[@]}" push --authfile "$authfile" "${image_base}:latest"
}

main() {
  echo "Repo: $repo_dir"
  echo "Target: $image (+ ${image_base}:latest)"
  echo

  if [[ "${ASL_AI_USE_DOCKER_BUILD:-}" == 1 ]]; then
    push_with_podman_or_docker
  elif push_with_podman_or_docker 2>/dev/null; then
    :
  elif push_sif_to_dockerhub 2>/dev/null; then
    :
  else
    echo "podman/skopeo unavailable on this host — using Kaniko via Apptainer." >&2
    ensure_sif
    push_with_kaniko
  fi

  echo
  echo "Published: $image"
  echo "Apptainer pull example:"
  echo "  apptainer pull docker://phindagijimana321/asl-ai-compute:${tag}"
}

main "$@"
