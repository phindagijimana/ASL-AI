#!/bin/bash
#
# Validate a BIDS dataset using whichever bids-validator is available.
#
# Usage:
#   ./validate_bids.sh <bids_root>           # default: warn-only on errors
#   STRICT=1 ./validate_bids.sh <bids_root>  # exit non-zero on validation errors
#
# Resolution order (first match wins):
#   1. bids-validator   (npm: `npm install -g bids-validator`)
#   2. deno             (`deno run -A jsr:@bids/validator`)
#   3. apptainer        (docker://bids/validator pulled on first use)
#   4. docker           (bids/validator image)
# If none are installed, prints install hints and exits 0 in default mode
# (so the wrapper pipeline doesn't break on systems without a validator).

set -euo pipefail

usage() { echo "usage: $0 <bids_root>" >&2; exit 1; }
[ $# -eq 1 ] || usage

bids_root="$1"
[ -d "$bids_root" ] || { echo "not a directory: $bids_root" >&2; exit 1; }

strict="${STRICT:-0}"

run_validator() {
  local kind="$1"; shift
  echo "[validate_bids] using $kind"
  if "$@" "$bids_root"; then
    echo "[validate_bids] OK"
    return 0
  else
    local rc=$?
    if [ "$strict" = "1" ]; then
      echo "[validate_bids] FAILED (rc=$rc, STRICT=1)" >&2
      return "$rc"
    else
      echo "[validate_bids] validation reported issues (rc=$rc); continuing (STRICT=0)" >&2
      return 0
    fi
  fi
}

if command -v bids-validator >/dev/null 2>&1; then
  run_validator "bids-validator (npm)" bids-validator
elif command -v deno >/dev/null 2>&1; then
  run_validator "deno bids-validator" deno run -A jsr:@bids/validator
elif command -v apptainer >/dev/null 2>&1; then
  run_validator "apptainer bids/validator" apptainer run docker://bids/validator
elif command -v docker >/dev/null 2>&1; then
  echo "[validate_bids] using docker bids/validator"
  if docker run --rm -v "$(cd "$bids_root" && pwd)":/data:ro bids/validator /data; then
    echo "[validate_bids] OK"
  else
    rc=$?
    [ "$strict" = "1" ] && exit "$rc"
    echo "[validate_bids] validation reported issues; continuing" >&2
  fi
else
  cat >&2 <<'EOF'
[validate_bids] no validator found. Install one of:
    npm install -g bids-validator
    curl -fsSL https://deno.land/install.sh | sh
    (or use the bundled asl-ai.sif Apptainer image, which includes deno)
skipping validation.
EOF
  [ "$strict" = "1" ] && exit 1
fi
