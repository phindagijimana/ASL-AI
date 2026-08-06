#!/bin/bash
#
# Run FastSurfer for one subject into $SUBJECTS_DIR (FreeSurfer layout).
#
# Usage:
#   ./run_fastsurfer_recon.sh <sub_id> <t1w_nii>
#
# Requires: apptainer, FASTSURFER_SIF, FS_LICENSE, SUBJECTS_DIR.
# Optional: FASTSURFER_GPU=1 to pass --nv to apptainer (GPU node).

set -euo pipefail

usage() { echo "usage: $0 <sub_id> <t1w_nii>" >&2; exit 1; }
[ $# -eq 2 ] || usage

sub="$1"
t1w="$2"

: "${SUBJECTS_DIR:?SUBJECTS_DIR must be set}"
: "${FS_LICENSE:?FS_LICENSE must be set}"
: "${FASTSURFER_SIF:?FASTSURFER_SIF must be set (source slurm/env.sh)}"

[ -f "$t1w" ] || { echo "T1w not found: $t1w" >&2; exit 1; }
[ -f "$FASTSURFER_SIF" ] || { echo "FastSurfer SIF missing: $FASTSURFER_SIF" >&2; exit 1; }
[ -f "$FS_LICENSE" ]     || { echo "FS_LICENSE missing: $FS_LICENSE" >&2; exit 1; }

t1w_abs="$(readlink -f "$t1w")"
t1w_dir="$(dirname "$t1w_abs")"
done_marker="$SUBJECTS_DIR/$sub/scripts/fastsurfer.done"
aparc="$SUBJECTS_DIR/$sub/mri/aparc+aseg.mgz"

if [ -f "$done_marker" ] && [ -f "$aparc" ]; then
  echo "FastSurfer already complete for $sub (found $done_marker) -- skipping"
  exit 0
fi

threads="${OMP_THREADS:-4}"
mkdir -p "$SUBJECTS_DIR/$sub/scripts"

echo "running FastSurfer for $sub with --threads $threads"
echo "  input : $t1w_abs"
echo "  output: $SUBJECTS_DIR/$sub"
echo "  sif   : $FASTSURFER_SIF"

nv_flag=()
[ "${FASTSURFER_GPU:-0}" = "1" ] && nv_flag=(--nv)

extra_binds=()
if [ -d /mnt/nfs/Gugger_Lab ]; then
  extra_binds+=(--bind /mnt/nfs/Gugger_Lab:/mnt/nfs/Gugger_Lab)
fi

apptainer exec \
  "${nv_flag[@]}" \
  --cleanenv \
  --env "SUBJECTS_DIR=$SUBJECTS_DIR" \
  --bind "$FS_LICENSE:/fs/license.txt:ro" \
  --bind "$SUBJECTS_DIR:$SUBJECTS_DIR" \
  --bind "$t1w_dir:$t1w_dir" \
  "${extra_binds[@]}" \
  "$FASTSURFER_SIF" \
  /fastsurfer/run_fastsurfer.sh \
    --fs_license /fs/license.txt \
    --t1 "$t1w_abs" \
    --sid "$sub" \
    --sd "$SUBJECTS_DIR" \
    --3T \
    --threads "$threads"

# FastSurfer writes aparc.DKTatlas+aseg.deep.mgz; downstream expects aparc+aseg.mgz.
sub_mri="$SUBJECTS_DIR/$sub/mri"
deep="$sub_mri/aparc.DKTatlas+aseg.deep.mgz"
if [ ! -f "$aparc" ]; then
  if [ -f "$deep" ]; then
    cp "$deep" "$aparc"
    echo "linked segmentation: aparc+aseg.mgz <- aparc.DKTatlas+aseg.deep.mgz"
  else
    echo "error: FastSurfer finished but no segmentation at $deep" >&2
    exit 1
  fi
fi

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$done_marker"
echo "FastSurfer complete for $sub"
