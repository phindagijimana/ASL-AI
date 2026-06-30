#!/bin/bash
#
# End-to-end ASL pipeline for one subject.
#
# Usage:
#   ./run_subject.sh <dicom_dir> <sub_id>
#
# Example:
#   export SUBJECTS_DIR=/path/to/freesurfer_subjects
#   OMP_THREADS=8 ./run_subject.sh /path/to/dicom sub-001
#
# Runs (idempotently, in this order):
#   1. dicom_to_bids.py            DICOM -> Data_ASL/ in BIDS format
#   2. asl_ai_pipeline.sh recon    FreeSurfer recon-all on T1w (~6-12 h)
#   3. asl_ai_pipeline.sh subject  bbregister + segstats, per ACQ
#   4. asl_ai_pipeline.sh ai       per-subject asymmetry index CSV, per ACQ
#
# Group-level aggregation (Step 4 in the docs) is intentionally NOT here --
# it runs once across all subjects after every subject is done.
#
# All output is tee'd to Data_ASL/logs/<sub>_pipeline.log.

set -euo pipefail

usage() { echo "usage: $0 <dicom_dir> <sub_id>" >&2; exit 1; }
[ $# -eq 2 ] || usage

dicom_dir="$1"
sub="$2"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bids_root="${BIDS_ROOT:-$script_dir/Data_ASL}"
acqs=("singleTI" "singleTI2100")

: "${SUBJECTS_DIR:?SUBJECTS_DIR must be set (source FreeSurfer first)}"
: "${FREESURFER_HOME:?FREESURFER_HOME must be set (source FreeSurfer first)}"
[ -d "$dicom_dir" ] || { echo "dicom_dir not found: $dicom_dir" >&2; exit 1; }
[[ "$sub" == sub-* ]] || { echo "sub_id must start with sub-: $sub" >&2; exit 1; }

mkdir -p "$bids_root/logs"
log="$bids_root/logs/${sub}_pipeline.log"
ai_dir="$bids_root/derivatives/asl-ai/$sub"
mkdir -p "$ai_dir"

step() { echo; echo "==== [$(date '+%F %T')] $* ===="; }

{
  step "STEP 1  DICOM -> BIDS"
  python3 "$script_dir/dicom_to_bids.py" "$dicom_dir" "$sub" "$bids_root"

  step "STEP 1b  bids-validator (non-fatal; set STRICT=1 to gate)"
  "$script_dir/validate_bids.sh" "$bids_root" || true

  step "STEP 2  recon-all"
  "$script_dir/asl_ai_pipeline.sh" recon "$sub" "$bids_root"

  for acq in "${acqs[@]}"; do
    step "STEP 3  bbregister + segstats   acq=$acq"
    "$script_dir/asl_ai_pipeline.sh" subject "$sub" "$bids_root" "$acq"

    step "STEP 5  asymmetry index         acq=$acq"
    stats="$SUBJECTS_DIR/$sub/stats/asl-acq-${acq}-aparc+aseg.txt"
    out="$ai_dir/${sub}_acq-${acq}_AI.csv"
    "$script_dir/asl_ai_pipeline.sh" ai "$stats" "$out"
  done

  step "DONE"
  echo "AI outputs: $ai_dir"
} 2>&1 | tee -a "$log"
