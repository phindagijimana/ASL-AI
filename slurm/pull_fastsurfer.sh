#!/bin/bash
#
# One-time SLURM job that pulls the FastSurfer CPU container (~4 GB).
# Run on a compute node (login node may kill long apptainer pulls).
#
# Usage:
#   sbatch slurm/pull_fastsurfer.sh
#
# GPU variant: set FASTSURFER_DOCKER_REF=docker://deepmi/fastsurfer:gpu-v2.5.0
#              and FASTSURFER_SIF=containers/fastsurfer-gpu-2.5.0.sif before submit.

#SBATCH --job-name=pull-fastsurfer
#SBATCH --partition=general
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=01:00:00

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/slurm/env.sh"

_ref="${FASTSURFER_DOCKER_REF:-docker://deepmi/fastsurfer:cpu-v2.5.0}"
_sif="${FASTSURFER_SIF:-$repo_root/containers/fastsurfer-cpu-2.5.0.sif}"

if [ -f "$_sif" ]; then
  echo "FastSurfer SIF already present: $_sif"
  exit 0
fi

mkdir -p "$(dirname "$_sif")"
echo "pulling $_ref -> $_sif"
apptainer pull "$_sif" "$_ref"
echo "done: $_sif"
