#!/bin/bash
#SBATCH --job-name=asl-docker-push
#SBATCH --partition=general
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=/mnt/nfs/home/urmc-sh.rochester.edu/pndagiji/Documents/ASL-AI/Data_ASL/logs/docker_push_%j.log

# Build ASL-AI compute image and push to Docker Hub from a compute node.
#
# One-time (persist credentials for batch jobs):
#   mkdir -p ~/.config/containers
#   podman login docker.io -u phindagijimana321 \
#     --authfile ~/.config/containers/auth.json
#
# Submit:
#   sbatch slurm/push_dockerhub.sh

set -euo pipefail

if [ -n "${SLURM_SUBMIT_DIR:-}" ]; then
  repo_root="$SLURM_SUBMIT_DIR"
else
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

tag="${ASL_AI_DOCKER_TAG:-latest}"

echo "Host: $(hostname)"
echo "Repo: $repo_root"
echo "Tag:  $tag"

# OOD login stores auth under /run/user/UID (not visible on compute nodes).
unset XDG_RUNTIME_DIR
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

cd "$repo_root"
./container/push_dockerhub.sh "$tag"

echo "Done."
