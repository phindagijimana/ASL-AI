#!/bin/bash
#
# One-time SLURM job that builds the ASL-AI compute container (~200–500 MB).
# Run on a compute node (login node may kill long apptainer builds).
#
# Usage (from repo root):
#   sbatch slurm/pull_compute.sh
#
#SBATCH --job-name=asl-compute-pull
#SBATCH --partition=general
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00

set -euo pipefail

if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
  repo_root="$SLURM_SUBMIT_DIR"
else
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

log="$repo_root/Data_ASL/logs/compute_pull_${SLURM_JOB_ID:-local}.log"
mkdir -p "$(dirname "$log")"
exec > >(tee -a "$log") 2>&1

echo "==== ASL-AI compute image build  $(date '+%F %T') ===="
echo "  node: $(hostname)"
echo "  repo: $repo_root"

cd "$repo_root"
./compute_setup.sh

ls -lah "$repo_root/compute/asl_ai_compute.sif"
echo "SIF ready."
