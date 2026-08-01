#!/usr/bin/env bash
# Re-measure the 257 genuine DNFs against a pinned binary, same 120 s cap as the triage.
#   remeasure-257.sh <pinned_binary> <tag>
# 4 batches concurrent. Contention biases toward MORE dnf, so any recovery found is a
# LOWER bound -- the safe direction for a claim of improvement. Stated, not hidden.
set -u
H=/data/dumontier/owl-reasoner-harness
BIN=$1; TAG=$2
CORPUS=/data/dumontier/ore-run/pool_sample/files
mkdir -p "$H/runs/$TAG"
split -n l/4 -d "$H/baselines/2026-08-01-dnf257-list.txt" "$H/runs/$TAG/c"
for c in 00 01 02 03; do
  $H/target/release/owl-reasoner-harness run \
    --corpus "$CORPUS" --only "$H/runs/$TAG/c$c" \
    --reasoner "$BIN" --args 'classify {}' \
    --cap-secs 120 --threads 1 --ext owl \
    --out "$H/runs/$TAG/$TAG-$c.jsonl" > "$H/runs/$TAG/$TAG-$c.log" 2>&1 &
done
wait
cat "$H/runs/$TAG"/$TAG-0?.jsonl > "$H/runs/$TAG.jsonl"
echo "REMEASURE $TAG DONE"
