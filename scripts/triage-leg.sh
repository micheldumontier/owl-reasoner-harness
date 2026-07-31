#!/usr/bin/env bash
# One peer-triage leg over the 257 genuine-DNF set.
#
#   $1 reasoner tag   $2 wrapper path   $3 args template   $4 cap seconds
#
# TWO THINGS THIS SCRIPT EXISTS TO GET RIGHT:
#
# 1. OUTPUT IS CAPTURED, because a peer's exit code does not answer the triage
#    question. Konclude exits 0 on a nonexistent file, on junk, and on a real
#    ontology alike. The verdict comes from scripts/triage.py reading the output.
#
# 2. RAW OUTPUT GOES TO THE SHARED DRIVE, NOT THE ROOT FILESYSTEM. The root fs was at
#    97% (14 GB free) when this was written, and these are the corpus's HARDEST
#    ontologies -- one produced an 11 MB hierarchy, so 257 x 3 reasoners would have
#    filled it and taken any running sweep down. /mnt/um-share-drive has 156 GB and
#    measured 100 MB/s, so the hierarchies are RETAINED there: Set A members' outputs
#    are exactly what the FP/MISSED comparison needs later, and re-running a peer over
#    the hard tail to recover them would cost hours. A disk guard still aborts the leg
#    rather than filling a shared volume.
set -u
H=/data/dumontier/owl-reasoner-harness
SCRATCH=/mnt/um-share-drive/dumontier/rustdl-triage-scratch
CORPUS=/data/dumontier/ore-run/pool_sample/files
tag=$1; wrap=$2; args=$3; cap=$4
BATCH=$H/runs/triage/batches
mkdir -p "$BATCH" "$H/runs/triage/parts"

# Split once, shared by every leg, so all reasoners see identical batches.
if [ ! -f "$BATCH/.done" ]; then
  split -l 16 -d -a 2 "$H/baselines/2026-08-01-dnf257-list.txt" "$BATCH/b"
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
    --out "$H/runs/triage/parts/$tag-$name.jsonl" \
    > "$H/runs/triage/parts/$tag-$name.log" 2>&1
  python3 "$H/scripts/triage.py" \
    --jsonl "$H/runs/triage/parts/$tag-$name.jsonl" \
    --out-dir "$odir" --format "$tag" --pairs $extra \
    -o "$H/runs/triage/parts/$tag-$name.triage.jsonl" \
    >> "$H/runs/triage/parts/$tag-$name.log" 2>&1
  # Raw output is RETAINED under $SCRATCH -- it is the input to the later FP/MISSED
  # comparison on Set A. Nothing to delete here.
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
cat "$H"/runs/triage/parts/$tag-b??.triage.jsonl > "$H/runs/triage/$tag-triage.jsonl"
echo "LEG $tag DONE: $(wc -l < "$H/runs/triage/$tag-triage.jsonl") cases"
python3 - "$H/runs/triage/$tag-triage.jsonl" <<'PY'
import json,sys
from collections import Counter
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print(Counter(r['verdict'] for r in rows))
PY
