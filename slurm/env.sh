# Source this BEFORE invoking ./slurm/sbatch_all.sh and again inside the
# SLURM job (submit_array.sh does this automatically). Detects whether
# FreeSurfer is installed locally; if not, falls back to an Apptainer
# image (pulled on demand on first use).
#
# Usage:
#   source ./slurm/env.sh
#   ./slurm/sbatch_all.sh subjects.tsv
#
# FastSurfer (optional, use --fastsurfer on run_subject.sh):
#   FASTSURFER_SIF defaults to containers/fastsurfer-cpu-2.5.0.sif
#   Set FASTSURFER_GPU=1 on a GPU node for faster segmentation.

# ---------------------------------------------------------------------------
# Paths (URMC defaults; edit if you move the pipeline elsewhere)
# ---------------------------------------------------------------------------
_HOST_FS=/opt/freesurfer-7.2.0
_FS_DOCKER_REF="docker://freesurfer/freesurfer:7.2.0"
_FASTSURFER_DOCKER_REF="${FASTSURFER_DOCKER_REF:-docker://deepmi/fastsurfer:cpu-v2.5.0}"

# License path required either way (FreeSurfer reads it from
# $FS_LICENSE on host or from /opt/freesurfer/license.txt inside the
# container, which we bind-mount the host file to).
export FS_LICENSE="${FS_LICENSE:-/mnt/nfs/home/urmc-sh.rochester.edu/pndagiji/Documents/Meld_Graph/meld_graph/meld_data/docker_version/freesurfer_license.txt}"

# ---------------------------------------------------------------------------
# Repo root + project-local paths
# ---------------------------------------------------------------------------
_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ASL_AI_REPO_ROOT="$_repo_root"
export SUBJECTS_DIR="${SUBJECTS_DIR:-$_repo_root/freesurfer_subjects}"
mkdir -p "$SUBJECTS_DIR"

_container_dir="$_repo_root/containers"
_container_bin="$_container_dir/bin"
export FREESURFER_SIF="$_container_dir/freesurfer-7.2.0.sif"
export FASTSURFER_SIF="${FASTSURFER_SIF:-$_container_dir/fastsurfer-cpu-2.5.0.sif}"

export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-$HOME/.cache/apptainer/cache}"
mkdir -p "$APPTAINER_CACHEDIR"

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

  mkdir -p "$_container_bin"
  for _cmd in recon-all bbregister mri_segstats mri_vol2vol asegstats2table \
              mri_convert tkregister2 mri_info; do
    ln -sf "$_container_dir/freesurfer-wrap.sh" "$_container_bin/$_cmd"
  done
  unset _cmd
  export PATH="$_container_bin:$PATH"

  export FREESURFER_HOME="/usr/local/freesurfer"
  export ASL_AI_FS_MODE="container"
  echo "[env] FreeSurfer: container at $FREESURFER_SIF (host path missing)"
else
  echo "[env] ERROR: no host FreeSurfer at $_HOST_FS and apptainer not found" >&2
  echo "[env]        install apptainer or set _HOST_FS to a working install" >&2
  return 1 2>/dev/null || exit 1
fi

# Optional containerized Python compute (run ./compute_setup.sh once).
if [ -x "$ASL_AI_REPO_ROOT/compute/run_in_container.sh" ]; then
  # shellcheck source=/dev/null
  source "$ASL_AI_REPO_ROOT/compute/env.sh"
fi

unset _HOST_FS _FS_DOCKER_REF _FASTSURFER_DOCKER_REF _container_dir _container_bin _repo_root
