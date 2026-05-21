#!/usr/bin/env bash
# drawio → SVG export wrapper.
#
# Wraps the Xvfb + drawio invocation so the caller only needs to run a single
# simple command. This keeps Claude Code's permission rules simple (one
# allowlist entry covers all uses) and avoids the per-call "simple_expansion"
# prompt caused by inline `$!`, `$XVFB_PID`, pipes, etc.
#
# Usage:
#   run-drawio-export.sh <input1.drawio> <output1.svg> [<input2.drawio> <output2.svg> ...]
#   run-drawio-export.sh --page <index> <input.drawio> <output.svg>
#
# Notes:
# - Pairs of (drawio, svg) arguments are converted in order, sharing one Xvfb.
# - --page selects a single page (0-based) for multi-page drawio files.
# - Errors from MESA/GPU/D-Bus during export are non-fatal and ignored here.

set -u

PAGE_INDEX=""

while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --page)
      PAGE_INDEX="$2"
      shift 2
      ;;
    --help|-h)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $1" >&2
      exit 64
      ;;
  esac
done

if (( $# < 2 )) || (( $# % 2 != 0 )); then
  echo "Usage: $(basename "$0") [--page <index>] <input.drawio> <output.svg> [<input2.drawio> <output2.svg> ...]" >&2
  exit 64
fi

if ! command -v drawio >/dev/null; then
  echo "drawio CLI not found in PATH" >&2
  exit 127
fi

if ! command -v Xvfb >/dev/null; then
  echo "Xvfb not found in PATH" >&2
  exit 127
fi

# Start Xvfb on a free display, captured for cleanup.
Xvfb :99 -screen 0 1024x768x24 -ac >/dev/null 2>&1 &
XVFB_PID=$!
trap 'kill "$XVFB_PID" 2>/dev/null' EXIT
sleep 3
export DISPLAY=:99

EXIT_CODE=0
while (( $# >= 2 )); do
  INPUT="$1"
  OUTPUT="$2"
  shift 2

  if [[ -n "$PAGE_INDEX" ]]; then
    drawio --no-sandbox --export --format svg \
      --page-index "$PAGE_INDEX" \
      --output "$OUTPUT" "$INPUT" \
      2>&1 | tail -2 || EXIT_CODE=$?
  else
    drawio --no-sandbox --export --format svg \
      --output "$OUTPUT" "$INPUT" \
      2>&1 | tail -2 || EXIT_CODE=$?
  fi

  if [[ ! -s "$OUTPUT" ]]; then
    echo "ERROR: $OUTPUT was not created or is empty" >&2
    EXIT_CODE=1
  fi
done

exit "$EXIT_CODE"
