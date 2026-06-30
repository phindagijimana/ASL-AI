#!/bin/bash
#
# One-time SLURM job that pulls the FreeSurfer container.
# Runs on a compute node (login node kills long apptainer pulls).
#
# Submit:
#   sbatch slurm/pull_freesurfer.sh
#
# After it succeeds, run ./slurm/sbatch_all.sh subjects.tsv as usual.
#
#SBATCH --job-name=fs-pull
#SBATCH --partition=general
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=1:00:00
#SBATCH --output=Data_ASL/logs/fs_pull_%j.log

set -euo pipefail

# Under SLURM the script is copied to /var/spool/slurmd; BASH_SOURCE
# points there, not at the repo. SLURM_SUBMIT_DIR is the directory the
# user ran sbatch from -- that's our repo root.
if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
  repo_root="$SLURM_SUBMIT_DIR"
else
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$repo_root"
[ -f slurm/env.sh ] || { echo "slurm/env.sh not found in $repo_root -- sbatch from repo root" >&2; exit 1; }

echo "==== FreeSurfer pull  $(date '+%F %T') ===="
echo "  node: $(hostname)"
echo "  cwd : $(pwd)"

# env.sh handles APPTAINER_CACHEDIR/TMPDIR and the pull itself when the SIF
# is absent. On a compute node with /opt/freesurfer-7.2.0 present it just
# returns "host mode" -- still fine (this script is then a no-op).
source slurm/env.sh

case "$ASL_AI_FS_MODE" in
  container)
    if [ -f "$FREESURFER_SIF" ]; then
      echo "SIF ready: $FREESURFER_SIF ($(du -h "$FREESURFER_SIF" | cut -f1))"
    else
      echo "env.sh returned without producing SIF" >&2
      exit 1
    fi
    ;;
  host)
    echo "this node has host FreeSurfer at $FREESURFER_HOME"
    echo "no pull needed; the pipeline will use host mode on nodes that have it"
    ;;
esac

echo "==== done  $(date '+%F %T') ===="
