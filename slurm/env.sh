# Source this BEFORE invoking ./slurm/sbatch_all.sh and again inside the
# SLURM job (submit_array.sh does this automatically). Detects whether
# FreeSurfer is installed locally; if not, falls back to an Apptainer
# image (pulled on demand on first use).
#
# Usage:
#   source ./slurm/env.sh
#   ./slurm/sbatch_all.sh subjects.tsv

# ---------------------------------------------------------------------------
# Paths — override via config.local.env or environment
# ---------------------------------------------------------------------------
_HOST_FS="${HOST_FREESURFER:-/opt/freesurfer-7.2.0}"
_FS_DOCKER_REF="docker://freesurfer/freesurfer:7.2.0"

# ---------------------------------------------------------------------------
# Repo root + project-local paths
# ---------------------------------------------------------------------------
_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$_repo_root/config.local.env" ]; then
  # shellcheck disable=SC1091
  source "$_repo_root/config.local.env"
fi
: "${FS_LICENSE:?Set FS_LICENSE in config.local.env or the environment}"

export ASL_AI_REPO_ROOT="$_repo_root"
export SUBJECTS_DIR="${SUBJECTS_DIR:-$_repo_root/freesurfer_subjects}"
mkdir -p "$SUBJECTS_DIR"

_container_dir="$_repo_root/containers"
_container_bin="$_container_dir/bin"
export FREESURFER_SIF="$_container_dir/freesurfer-7.2.0.sif"

# Apptainer cache: ~12 GB OCI blobs; persistent across jobs on NFS so
# we don't re-download.
export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-$HOME/.cache/apptainer/cache}"
mkdir -p "$APPTAINER_CACHEDIR"

# Apptainer TMPDIR for build / mksquashfs: MUST be on a local
# (non-NFS) filesystem. NFS4 ACL xattrs make mksquashfs abort with
# "Unrecognised xattr prefix system.nfs4_acl" when writing the SIF.
# Inside a SLURM job use compute-node-local /tmp; on the login node
# fall back to ~/.cache/apptainer/tmp (login pulls typically get killed
# by node policy anyway -- use slurm/pull_freesurfer.sh instead).
if [ -n "${SLURM_JOB_ID:-}" ]; then
  export APPTAINER_TMPDIR="/tmp/apptainer-$USER-$SLURM_JOB_ID"
else
  export APPTAINER_TMPDIR="${APPTAINER_TMPDIR:-$HOME/.cache/apptainer/tmp}"
fi
mkdir -p "$APPTAINER_TMPDIR"

# ---------------------------------------------------------------------------
# Resolve FreeSurfer: host install first, else container.
# ---------------------------------------------------------------------------
if [ -d "$_HOST_FS" ] && [ -f "$_HOST_FS/SetUpFreeSurfer.sh" ]; then
  export FREESURFER_HOME="$_HOST_FS"
  export ASL_AI_FS_MODE="host"
  echo "[env] FreeSurfer: host install at $_HOST_FS"
elif command -v apptainer >/dev/null 2>&1; then
  # Container mode. Pull on demand (one-time, ~5 GB).
  if [ ! -f "$FREESURFER_SIF" ]; then
    echo "[env] pulling FreeSurfer container from $_FS_DOCKER_REF"
    echo "[env]   this is a one-time download (~5 GB, several minutes)"
    mkdir -p "$_container_dir"
    if ! apptainer pull "$FREESURFER_SIF" "$_FS_DOCKER_REF"; then
      echo "[env] ERROR: apptainer pull failed" >&2
      rm -f "$FREESURFER_SIF"
      return 1 2>/dev/null || exit 1
    fi
  fi

  # Wire up shim binaries: PATH-prepended directory with symlinks to the
  # wrapper script, one per FreeSurfer command we call.
  mkdir -p "$_container_bin"
  for _cmd in recon-all bbregister mri_segstats mri_vol2vol asegstats2table \
              mri_convert tkregister2 mri_info; do
    ln -sf "$_container_dir/freesurfer-wrap.sh" "$_container_bin/$_cmd"
  done
  unset _cmd
  export PATH="$_container_bin:$PATH"

  # Path inside the SIF (docker://freesurfer/freesurfer:7.2.0). Pipeline
  # scripts expand $FREESURFER_HOME into command-line args before apptainer
  # runs, so this must match the container layout, not the host sentinel.
  export FREESURFER_HOME="/usr/local/freesurfer"
  export ASL_AI_FS_MODE="container"
  echo "[env] FreeSurfer: container at $FREESURFER_SIF (host path missing)"
else
  echo "[env] ERROR: no host FreeSurfer at $_HOST_FS and apptainer not found" >&2
  echo "[env]        install apptainer or set _HOST_FS to a working install" >&2
  return 1 2>/dev/null || exit 1
fi

unset _HOST_FS _FS_DOCKER_REF _container_dir _container_bin _repo_root
