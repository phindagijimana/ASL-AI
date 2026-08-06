#!/bin/bash
#SBATCH --job-name=asl-docker-push
#SBATCH --partition=general
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=/mnt/nfs/home/urmc-sh.rochester.edu/pndagiji/Documents/ASL-AI/Data_ASL/logs/docker_push_%j.log

# Build ASL-AI compute Docker image and push to Docker Hub.
# Run on a compute node (OOD lacks subuid/fakeroot for podman/skopeo).
#
#   podman login docker.io -u phindagijimana321   # before sbatch
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

cd "$repo_root"
./container/push_dockerhub.sh "$tag"

echo "Done."
