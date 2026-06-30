#!/bin/bash
#
# SLURM array submission: one task per subject from subjects.tsv.
#
# Submit with the helper:
#   ./slurm/sbatch_all.sh subjects.tsv
# or by hand:
#   sbatch --array=1-N slurm/submit_array.sh subjects.tsv
#                              N = non-comment/blank lines in subjects.tsv
#
# Required environment (set BEFORE sbatch, not inside this script):
#   FREESURFER_HOME   path to your FreeSurfer install
#   SUBJECTS_DIR      writable directory for recon-all output
#   FS_LICENSE        FreeSurfer license file (optional if license is in
#                     $FREESURFER_HOME/license.txt)
#
# Resource notes:
#   --cpus-per-task=8  -> passed to recon-all as -openmp 8
#   --mem=16G          -> recon-all peaks around 6 GB; 16 GB is headroom
#   --time=14:00:00    -> recon-all typically 6-12 h, plus Steps 1+3+5
#
#SBATCH --job-name=asl-ai
#SBATCH --partition=general
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=14:00:00

set -euo pipefail

# Under SLURM the script is copied to /var/spool/slurmd; BASH_SOURCE points
# there, not at the repo. SLURM_SUBMIT_DIR is the directory the user ran
# sbatch from -- that's our repo root.
if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
  repo_root="$SLURM_SUBMIT_DIR"
else
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
script_dir="$repo_root/slurm"
[ -f "$script_dir/env.sh" ] || { echo "slurm/env.sh not found at $script_dir -- sbatch from repo root" >&2; exit 1; }

# Re-source env.sh on the compute node: it re-detects host vs container
# FreeSurfer locally (the login node and the compute node may differ).
source "$script_dir/env.sh"
: "${SUBJECTS_DIR:?env.sh failed to set SUBJECTS_DIR}"
: "${ASL_AI_FS_MODE:?env.sh did not resolve FreeSurfer (host or container)}"

# Set up SLURM-managed log dir under the BIDS root (so logs live with the data).
bids_root="${BIDS_ROOT:-$repo_root/Data_ASL}"
mkdir -p "$bids_root/logs"

subjects_tsv="${1:?usage: sbatch --array=1-N $0 <subjects.tsv>}"
[ -f "$subjects_tsv" ] || { echo "not a file: $subjects_tsv" >&2; exit 1; }
: "${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID unset -- did you submit with --array?}"

# Pick this task's line (skipping comments and blanks); 1-indexed.
line=$(grep -vE '^[[:space:]]*(#|$)' "$subjects_tsv" | sed -n "${SLURM_ARRAY_TASK_ID}p")
if [ -z "$line" ]; then
  echo "no subject for array index $SLURM_ARRAY_TASK_ID in $subjects_tsv" >&2
  exit 1
fi
dicom_dir=$(printf '%s\n' "$line" | cut -f1)
sub_id=$(printf '%s\n'    "$line" | cut -f2)
[ -n "$dicom_dir" ] && [ -n "$sub_id" ] || { echo "bad line: $line" >&2; exit 1; }

# Per-task log file -- on top of the SLURM stdout/stderr captured by sbatch.
log="$bids_root/logs/slurm_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}_${sub_id}.log"
exec > >(tee -a "$log") 2>&1

echo "==== SLURM task ${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}  $(date '+%F %T') ===="
echo "  node           : $(hostname)"
echo "  subject        : $sub_id"
echo "  DICOM source   : $dicom_dir"
echo "  FS mode        : $ASL_AI_FS_MODE"
[ "$ASL_AI_FS_MODE" = "host" ]      && echo "  FREESURFER_HOME: $FREESURFER_HOME"
[ "$ASL_AI_FS_MODE" = "container" ] && echo "  FREESURFER_SIF : $FREESURFER_SIF"
echo "  SUBJECTS_DIR   : $SUBJECTS_DIR"
echo "  CPUs           : $SLURM_CPUS_PER_TASK"

# In host mode, source SetUpFreeSurfer.sh so e.g. PERL5LIB is set. In
# container mode, the container's own entrypoint handles that; we just
# call FreeSurfer commands via the shim binaries env.sh put on PATH.
if [ "$ASL_AI_FS_MODE" = "host" ]; then
  . "$FREESURFER_HOME/SetUpFreeSurfer.sh"
fi

export OMP_THREADS="${SLURM_CPUS_PER_TASK:-4}"
cd "$repo_root"
./run_subject.sh "$dicom_dir" "$sub_id"
