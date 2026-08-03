#!/usr/bin/env bash
# One full-corpus sweep arm. sweep-arm.sh <pinned_binary> <tag> [listfile]
#
# WRITES ONE OUTPUT FILE PER CHUNK. The first attempt at this pointed four concurrent
# chunks at a SINGLE --out path; their appends interleaved and produced 40 unparseable
# records plus 73 silently missing ontologies. Per-chunk files, concatenated at the end,
# make that impossible.
set -u
H=/data/dumontier/owl-reasoner-harness
BIN=$1; TAG=$2; LIST=${3:-}
CORPUS=/data/dumontier/ore-run/pool_sample/files
D=$H/runs/$TAG; mkdir -p "$D"
if [ -n "$LIST" ]; then split -n l/4 -d "$LIST" "$D/c"; else
  ls $CORPUS/*.owl | xargs -n1 basename | sed 's/\.owl$//' > "$D/all.txt"
  split -n l/4 -d "$D/all.txt" "$D/c"
fi
for c in 00 01 02 03; do
  [ -s "$D/c$c" ] || continue
  $H/target/release/owl-reasoner-harness run \
    --corpus "$CORPUS" --only "$D/c$c" --reasoner "$BIN" --args 'classify {}' \
    --cap-secs 60 --threads 1 --ext owl --digest-output \
    --out "$D/$TAG-$c.jsonl" > "$D/$TAG-$c.log" 2>&1 &
done
wait
cat "$D"/$TAG-0?.jsonl > "$H/runs/full-$TAG.jsonl"
echo "SWEEP $TAG DONE: $(grep -c '\"kind\":\"case\"' "$H/runs/full-$TAG.jsonl") cases"
