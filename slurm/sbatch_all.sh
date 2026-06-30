#!/bin/bash
#
# Submit one SLURM array job covering every subject in subjects.tsv.
#
# Usage:
#   export FREESURFER_HOME=/path/to/freesurfer
#   export SUBJECTS_DIR=/path/to/freesurfer_subjects
#   export FS_LICENSE=/path/to/license.txt          # optional
#   ./slurm/sbatch_all.sh subjects.tsv
#
# subjects.tsv format: TAB-separated <dicom_dir>\t<sub_id>, '#' comments and
# blank lines are skipped.

set -euo pipefail

subjects_tsv="${1:?usage: $0 <subjects.tsv>}"
[ -f "$subjects_tsv" ] || { echo "not a file: $subjects_tsv" >&2; exit 1; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
submit_script="$script_dir/submit_array.sh"

# Count real lines (excluding comments and blanks).
n=$(grep -cvE '^[[:space:]]*(#|$)' "$subjects_tsv" || true)
[ "$n" -ge 1 ] || { echo "no subjects in $subjects_tsv" >&2; exit 1; }

# Auto-source env.sh if the user hasn't already (this triggers the
# container pull on first invocation when host FreeSurfer is missing).
if [ -z "${ASL_AI_FS_MODE:-}" ]; then
  source "$script_dir/env.sh"
fi

echo "submitting array 1-$n on partition 'general'"
echo "  subjects.tsv    : $subjects_tsv"
echo "  FS mode         : $ASL_AI_FS_MODE"
echo "  SUBJECTS_DIR    : $SUBJECTS_DIR"
echo "  FS_LICENSE      : ${FS_LICENSE:-<unset>}"
[ "$ASL_AI_FS_MODE" = "container" ] && echo "  FREESURFER_SIF  : $FREESURFER_SIF"

# Use --export=ALL (the default) so the env above reaches the job.
sbatch \
  --array="1-$n" \
  --output="${BIDS_ROOT:-$(cd "$script_dir/.." && pwd)/Data_ASL}/logs/slurm_%A_%a.out" \
  --error="${BIDS_ROOT:-$(cd "$script_dir/.." && pwd)/Data_ASL}/logs/slurm_%A_%a.err" \
  "$submit_script" "$subjects_tsv"
