#!/bin/bash
#
# Shim that runs a single FreeSurfer command inside the Apptainer image.
# Symlinks created by slurm/env.sh (recon-all, bbregister, mri_segstats, ...)
# all point to this file; the dispatched command is read from $0.
#
# Required environment (set by slurm/env.sh):
#   FREESURFER_SIF      path to the FreeSurfer .sif image
#   FS_LICENSE          host path to the FreeSurfer license.txt
#   SUBJECTS_DIR        host directory for FreeSurfer subject output
#   ASL_AI_REPO_ROOT    host path to the ASL-AI repo (bind-mounted into container)

set -euo pipefail

: "${FREESURFER_SIF:?FREESURFER_SIF not set (source slurm/env.sh first)}"
: "${FS_LICENSE:?FS_LICENSE not set}"
: "${SUBJECTS_DIR:?SUBJECTS_DIR not set}"
: "${ASL_AI_REPO_ROOT:?ASL_AI_REPO_ROOT not set}"

[ -f "$FREESURFER_SIF" ] || { echo "FreeSurfer SIF missing: $FREESURFER_SIF" >&2; exit 1; }
[ -f "$FS_LICENSE" ]     || { echo "FS_LICENSE missing: $FS_LICENSE" >&2; exit 1; }
[ -d "$SUBJECTS_DIR" ]   || mkdir -p "$SUBJECTS_DIR"

cmd="$(basename "$0")"

# Optional DICOM mount (set ASL_DICOM_ROOT in config.local.env).
extra_binds=()
if [ -n "${ASL_DICOM_ROOT:-}" ] && [ -d "$ASL_DICOM_ROOT" ]; then
  extra_binds+=(--bind "$ASL_DICOM_ROOT:$ASL_DICOM_ROOT")
fi

exec apptainer exec \
  --cleanenv \
  --env "SUBJECTS_DIR=$SUBJECTS_DIR" \
  --env "FREESURFER_HOME=/usr/local/freesurfer" \
  --env "FS_LICENSE=/usr/local/freesurfer/.license" \
  --bind "$FS_LICENSE:/usr/local/freesurfer/.license:ro" \
  --bind "$SUBJECTS_DIR:$SUBJECTS_DIR" \
  --bind "$ASL_AI_REPO_ROOT:$ASL_AI_REPO_ROOT" \
  "${extra_binds[@]}" \
  "$FREESURFER_SIF" \
  "$cmd" "$@"
