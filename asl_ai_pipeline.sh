#!/bin/bash
#
# ASL -> FreeSurfer regional stats -> asymmetry index pipeline.
#
# recon-all:    ./asl_ai_pipeline.sh recon   <sub_id> <bids_root>
# Per-subject:  ./asl_ai_pipeline.sh subject <sub_id> <bids_root> [acq_label]
# Group table:  ./asl_ai_pipeline.sh group   <sublist.txt> <stats_filename> <out_table.txt>
# Asymmetry:    ./asl_ai_pipeline.sh ai      <input.txt> <output.csv>
#
# Default acq_label is "singleTI" (1.8 s PLD). Use "singleTI2100" for 2.1 s PLD.
#
# subject mode:
#   - extracts two derivatives from the raw 4D ASL via
#     extract_asl_derivatives.py (BIDS, idempotent):
#       mean-control  (high SNR; used as both bbregister --mov
#                      AND the mri_segstats input -- "ASL signal" path)
#       mean-deltaM   (perfusion-weighted; produced but not measured
#                      by default; switch by editing MEAS_IMG below)
#   - bbregisters mean-control -> T1, outputs the resampled image,
#   - runs mri_segstats on that resampled mean-control vs aparc+aseg.
#
# The scanner Perfusion_Weighted (CBF) map is NOT used: dcm2niix flags
# its spatial matrix as bogus on Siemens classic DICOM (the LTA from
# the raw ASL would mis-register the CBF). The mean-control image
# inherits the correct affine from the raw 4D ASL.
#
# Outputs to $SUBJECTS_DIR/<sub>/{asl,stats}/, all suffixed by acq.
#
# Requires: FreeSurfer on PATH (recon-all, bbregister, mri_segstats,
# asegstats2table), SUBJECTS_DIR and FREESURFER_HOME set.
#
# recon-all uses OMP_THREADS (default 4). It is long (~6-12 h):
#   OMP_THREADS=8 nohup ./asl_ai_pipeline.sh recon sub-XXX Data_ASL/ &> recon-sub-XXX.log &

set -euo pipefail

usage() { echo "usage: $0 {recon|subject|group|ai} ..." >&2; exit 1; }
[ $# -ge 1 ] || usage
mode="$1"

case "$mode" in
  recon)
    sub="${2:?subject id required}"
    bids_root="${3:?BIDS root required}"

    : "${SUBJECTS_DIR:?SUBJECTS_DIR must be set (source FreeSurfer)}"
    : "${FREESURFER_HOME:?FREESURFER_HOME must be set (source FreeSurfer)}"

    t1w="$bids_root/$sub/anat/${sub}_T1w.nii.gz"
    if [ ! -f "$t1w" ]; then
      echo "error: T1w not found at $t1w" >&2
      exit 1
    fi

    done_marker="$SUBJECTS_DIR/$sub/scripts/recon-all.done"
    if [ -f "$done_marker" ]; then
      echo "recon-all already complete for $sub (found $done_marker) -- skipping"
      exit 0
    fi

    threads="${OMP_THREADS:-4}"
    echo "running recon-all -all for $sub with -openmp $threads"
    echo "  input : $t1w"
    echo "  output: $SUBJECTS_DIR/$sub"
    recon-all -i "$t1w" -s "$sub" -all -openmp "$threads"
    ;;

  subject)
    sub="${2:?subject id required}"
    bids_root="${3:?BIDS root required}"
    acq="${4:-singleTI}"

    : "${SUBJECTS_DIR:?SUBJECTS_DIR must be set (source FreeSurfer)}"
    : "${FREESURFER_HOME:?FREESURFER_HOME must be set (source FreeSurfer)}"

    if [ ! -f "$SUBJECTS_DIR/$sub/mri/aparc+aseg.mgz" ]; then
      echo "error: $sub has no aparc+aseg.mgz -- run 'recon' first" >&2
      exit 1
    fi

    # Build the mean-control + mean-deltaM derivatives (idempotent).
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$script_dir/extract_asl_derivatives.py" "$bids_root" "$sub" "$acq"
    mean_ctrl="$bids_root/derivatives/asl-mean-control/$sub/perf/${sub}_acq-${acq}_desc-meanControl_asl.nii.gz"
    [ -f "$mean_ctrl" ] || { echo "error: mean-control not produced: $mean_ctrl" >&2; exit 1; }

    asl_FS_dir="$SUBJECTS_DIR/$sub/asl"
    mkdir -p "$asl_FS_dir" "$SUBJECTS_DIR/$sub/stats"

    lta="$asl_FS_dir/acq-${acq}_meanctrl_to_t1_9dof.lta"
    asl_in_t1="$asl_FS_dir/acq-${acq}_asl_in_t1_9dof.mgz"
    stats="$SUBJECTS_DIR/$sub/stats/asl-acq-${acq}-aparc+aseg.txt"

    echo "subject: $sub  acq: $acq"
    echo "  bbregister + segstats mov : $mean_ctrl"
    echo "  stats                     : $stats"

    # bbregister: ASL native -> T1 using mean control (T2-like contrast).
    # The resampled mean-control IS the measurement image -- same
    # workflow as the original ASL script (bbregister then segstats on
    # the registered image, no intermediate vol2vol step).
    bbregister \
      --s   "$sub" \
      --mov "$mean_ctrl" \
      --reg "$lta" \
      --t2 \
      --o   "$asl_in_t1" \
      --9

    mri_segstats \
      --ctab "$FREESURFER_HOME/FreeSurferColorLUT.txt" \
      --i    "$asl_in_t1" \
      --seg  "$SUBJECTS_DIR/$sub/mri/aparc+aseg.mgz" \
      --sum  "$stats"
    ;;

  group)
    sublist="${2:?sublist.txt required}"
    stats_filename="${3:?stats filename required (e.g. asl-acq-singleTI-aparc+aseg.txt)}"
    out_table="${4:?output table path required}"

    asegstats2table \
      --subjectsfile "$sublist" \
      --statsfile="$stats_filename" \
      --meas mean \
      --skip \
      --tablefile="$out_table"
    ;;

  ai)
    in_file="${2:?input stats file required}"
    out_file="${3:?output csv required}"

    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$script_dir/compute_asymmetry.py" "$in_file" "$out_file"
    ;;

  *)
    echo "usage: $0 {recon|subject|group|ai} ..." >&2
    exit 1
    ;;
esac
