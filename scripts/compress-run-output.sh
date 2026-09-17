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
before=$(du -sb "$d" | cut -f1)
find "$d" -type f ! -name '*.gz' -print0 | xargs -0 -r -P "${JOBS:-4}" gzip -6
after=$(du -sb "$d" | cut -f1)
awk -v b="$before" -v a="$after" 'BEGIN{printf "compressed %s: %.2f GB -> %.2f GB (%.1fx)\n", "'"$d"'", b/1073741824, a/1073741824, b/a}'
