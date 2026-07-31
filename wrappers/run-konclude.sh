#!/usr/bin/env bash
# Konclude v0.7.0-1138, native static binary. Reads .ofn directly (no ROBOT step).
# No container/JVM overhead to subtract.
# OUTPUT CAPTURE. Konclude exits 0 on a MISSING file, on junk, and on a real ontology
# alike, writing an 896-byte Thing/Nothing-only hierarchy in the failure cases. So an
# exit code says nothing about whether it classified anything, and a harness `ok` derived
# from it is meaningless. Capture the hierarchy so outcome can be decided from CONTENT.
#   HARNESS_OUT_DIR set -> hierarchy to $HARNESS_OUT_DIR/<stem>.owx
#   else                -> second positional arg, default /dev/null (timing-only)
if [ -n "${HARNESS_OUT_DIR:-}" ]; then
  mkdir -p "$HARNESS_OUT_DIR"
  out="$HARNESS_OUT_DIR/$(basename "${1%.*}").owx"
else
  out="${2:-/dev/null}"
fi
exec /data/dumontier/reasoners/konclude classification -i "$1" -o "$out"
