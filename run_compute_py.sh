#!/bin/bash
# Run an ASL-AI Python script in the compute container when available, else host python3.
#
# Usage: ./run_compute_py.sh /path/to/script.py [args...]

set -euo pipefail

[[ $# -ge 1 ]] || { echo "Usage: run_compute_py.sh <script.py> [args...]" >&2; exit 2; }

script="$1"
shift
repo_dir="$(cd "$(dirname "$0")" && pwd)"
runner="$repo_dir/compute/run_in_container.sh"

if [[ -x "$runner" ]]; then
  exec "$runner" "$script" "$@"
fi

exec python3 "$script" "$@"
