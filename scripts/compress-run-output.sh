#!/usr/bin/env bash
# Compress a completed arm's captured output in place.
#
# RUN THIS AFTER AN ARM FINISHES, never by piping the reasoner through gzip. A
# pipeline returns the LAST command's status, and that is precisely how 22 KM
# failures were once recorded as `ok`: the wrapper ended in `| tee` and the harness,
# correctly deriving outcome from exit status, read tee's 0.
#
# Measured ratios: 36x on input OWL functional syntax, 17.9x on a real HermiT
# taxonomy. A full 1,920 x 7-arm repeat emits ~35 GB raw and ~1-2 GB compressed.
# scripts/normalise.py reads .gz transparently, so nothing downstream changes.
set -u
d=${1:?usage: compress-run-output.sh <HARNESS_OUT_DIR>}
# `du -sb` is GNU-only and fails on macOS -- the same portability class as the
# `/usr/bin/time -f` assumption that once made the harness fail EVERY case there.
# `du -sk` is in POSIX and works on both.
before=$(du -sk "$d" | cut -f1)
# STDERR STAYS UNCOMPRESSED. It is what you read when something breaks, and it is
# read by hand with head/grep -- which see gzip as binary garbage. It is also tiny
# next to the taxonomies, so compressing it saves nothing and costs legibility.
# (normalise.py reads .gz transparently; a human at a terminal does not.)
find "$d" -type f ! -name '*.gz' ! -name '*.stderr' -print0 \
  | xargs -0 -r -P "${JOBS:-4}" gzip -6
after=$(du -sk "$d" | cut -f1)
awk -v b="$before" -v a="$after" -v d="$d" \
  'BEGIN{ if (a<1) a=1; printf "compressed %s: %.1f MB -> %.1f MB (%.1fx)\n", d, b/1024, a/1024, b/a }'
