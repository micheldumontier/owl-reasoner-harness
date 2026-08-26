#!/usr/bin/env bash
# One peer-triage leg over the v0.4.14 151-ontology DNF tail (2026-08-04).
#
# Adapted from scripts/triage-leg.sh (which is pinned to the 2026-08-01 257 list).
# Everything that script exists to get right is preserved verbatim:
#
# 1. OUTPUT IS CAPTURED, because a peer's exit code does not answer the triage
#    question. Konclude exits 0 on a nonexistent file, on junk, and on a real
#    ontology alike. The verdict comes from scripts/triage.py reading the output.
#
# 2. RAW OUTPUT GOES TO THE SHARED DRIVE, NOT THE ROOT FILESYSTEM. Root fs was at
#    95% (22 GB free) when this run was launched; these are the corpus's hardest
#    ontologies and one previously produced an 11 MB hierarchy. Raw hierarchies are
#    RETAINED on /mnt/um-share-drive (477 GB free) because Set A's outputs are
#    exactly what a later FP/MISSED comparison needs. A disk guard aborts the leg
#    rather than filling a shared volume.
#
# 3. ONE OUTPUT FILE PER CHUNK, concatenated at the end. Concurrent workers never
#    append to a shared file (a prior sweep lost 73 ontologies that way).
#
# CHANGES vs triage-leg.sh, all deliberate:
#   - list      -> baselines/2026-08-04-tail-v0414-list.txt (151 onts)
#   - batches   -> 8 lines each (19 batches) for better load balance across the
#                  SAME 4-in-flight concurrency the 2026-08-01 leg used, so peer
#                  walls stay comparable to that baseline.
#   - all paths tagged 2026-08-04 so the 2026-08-01 baselines are never overwritten.
#
#   $1 reasoner tag   $2 wrapper path   $3 args template   $4 cap seconds
set -u
H=/data/dumontier/owl-reasoner-harness
STAMP=2026-08-04
SCRATCH=/mnt/um-share-drive/dumontier/rustdl-triage-scratch-$STAMP
CORPUS=/data/dumontier/ore-run/pool_sample/files
LIST=$H/baselines/$STAMP-tail-v0414-list.txt
tag=$1; wrap=$2; args=$3; cap=$4
RUN=$H/runs/triage-$STAMP
BATCH=$RUN/batches
mkdir -p "$BATCH" "$RUN/parts" "$SCRATCH"

# Split once, shared by every leg, so all reasoners see identical batches.
if [ ! -f "$BATCH/.done" ]; then
  split -l 8 -d -a 2 "$LIST" "$BATCH/b"
  touch "$BATCH/.done"
fi

extra=""
[ "$tag" = km ] && extra="--corpus $CORPUS"

run_batch() {
  local b=$1 name odir
  name=$(basename "$b")
  odir=$SCRATCH/$tag/$name
  rm -rf "$odir"; mkdir -p "$odir"
  HARNESS_OUT_DIR="$odir" $H/target/release/owl-reasoner-harness run \
    --corpus "$CORPUS" --only "$b" \
    --reasoner "$wrap" --args "$args" \
    --cap-secs "$cap" --threads 1 --ext owl \
    --out "$RUN/parts/$tag-$name.jsonl" \
    > "$RUN/parts/$tag-$name.log" 2>&1
  python3 "$H/scripts/triage.py" \
    --jsonl "$RUN/parts/$tag-$name.jsonl" \
    --out-dir "$odir" --format "$tag" --pairs $extra \
    -o "$RUN/parts/$tag-$name.triage.jsonl" \
    >> "$RUN/parts/$tag-$name.log" 2>&1
  # Raw output is RETAINED under $SCRATCH -- input to any later FP/MISSED work.
}

# 4 batches in flight; a leg runs alone so peer walls are not contention-inflated.
n=0
for b in "$BATCH"/b??; do
  run_batch "$b" &
  n=$((n+1))
  if [ $((n % 4)) -eq 0 ]; then wait; fi
  # Refuse to fill either volume: bail out loudly rather than take a shared host down.
  for vol in / "$SCRATCH"; do
    avail=$(df --output=avail -k "$vol" | tail -1)
    if [ "$avail" -lt 5242880 ]; then
      echo "ABORT $tag: free space on $vol below 5 GB ($avail kB). Batches launched: $n" >&2
      wait; exit 3
    fi
  done
done
wait
cat "$RUN"/parts/$tag-b??.triage.jsonl > "$RUN/$tag-triage.jsonl"
echo "LEG $tag DONE: $(wc -l < "$RUN/$tag-triage.jsonl") cases"
python3 - "$RUN/$tag-triage.jsonl" <<'PY'
import json,sys
from collections import Counter
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print(Counter(r['verdict'] for r in rows))
PY
