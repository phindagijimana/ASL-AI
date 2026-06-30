#!/bin/bash
#
# Run the full ASL pipeline (run_subject.sh) over many subjects.
#
# Usage:
#   ./run_batch.sh <subjects.tsv>
#
# subjects.tsv format: two TAB-separated columns, no header.
#   /path/to/dicom/sub-001   sub-001
#   /path/to/dicom/sub-002   sub-002
# Lines beginning with '#' and blank lines are skipped.
#
# Sequential execution by default (recon-all is the long step; parallel
# recon-alls compete for $SUBJECTS_DIR locks and OpenMP threads). For
# cluster parallelism wrap each line as a separate SLURM job:
#
#   while IFS=$'\t' read -r dcm sub; do
#     [[ "$dcm" =~ ^# || -z "$dcm" ]] && continue
#     sbatch --job-name="asl-$sub" --cpus-per-task=8 \
#            --wrap="OMP_THREADS=8 ./run_subject.sh '$dcm' '$sub'"
#   done < subjects.tsv
#
# Each subject is idempotent (recon-all skips if .done marker exists;
# later steps overwrite their own outputs), so re-running the batch
# resumes from where it left off.

set -uo pipefail   # NOTE: no -e; we want to capture per-subject failures.

usage() { echo "usage: $0 <subjects.tsv>" >&2; exit 1; }
[ $# -eq 1 ] || usage

subjects_tsv="$1"
[ -f "$subjects_tsv" ] || { echo "not a file: $subjects_tsv" >&2; exit 1; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${SUBJECTS_DIR:?SUBJECTS_DIR must be set (source FreeSurfer first)}"
: "${FREESURFER_HOME:?FREESURFER_HOME must be set (source FreeSurfer first)}"

bids_root="${BIDS_ROOT:-$script_dir/Data_ASL}"
mkdir -p "$bids_root/logs"
summary="$bids_root/logs/batch_$(date +%Y%m%d_%H%M%S).log"

ok=()
failed=()

echo "=== ASL-AI batch  $(date '+%F %T') ===" | tee -a "$summary"
echo "subjects file: $subjects_tsv"           | tee -a "$summary"
echo "bids root    : $bids_root"              | tee -a "$summary"
echo "SUBJECTS_DIR : $SUBJECTS_DIR"           | tee -a "$summary"

while IFS=$'\t' read -r dcm sub _rest; do
  # Skip blanks and comments
  [[ -z "${dcm// }" || "$dcm" =~ ^# ]] && continue
  if [ -z "${sub:-}" ]; then
    echo "skip malformed line (no sub_id for $dcm)" | tee -a "$summary"
    continue
  fi

  echo                                          | tee -a "$summary"
  echo "---- $(date '+%F %T')  $sub  <-  $dcm ----" | tee -a "$summary"
  if "$script_dir/run_subject.sh" "$dcm" "$sub"; then
    ok+=("$sub")
    echo "[batch] $sub OK"  | tee -a "$summary"
  else
    rc=$?
    failed+=("$sub (rc=$rc)")
    echo "[batch] $sub FAILED (rc=$rc) -- continuing" | tee -a "$summary"
  fi
done < "$subjects_tsv"

echo                                              | tee -a "$summary"
echo "=== Summary  $(date '+%F %T') ==="          | tee -a "$summary"
echo "  succeeded (${#ok[@]}): ${ok[*]:-none}"    | tee -a "$summary"
echo "  failed    (${#failed[@]}): ${failed[*]:-none}" | tee -a "$summary"
echo "  log: $summary"

# Exit non-zero if any subject failed.
[ "${#failed[@]}" -eq 0 ]
