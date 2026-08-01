#!/usr/bin/env bash
# Phase 2 attribution across a list of ontologies.
#   attribute-all.sh <listfile> <out.jsonl> [parallel] [cap]
#
# TRADE-OFF STATED, not hidden: attribute.sh runs its four probes sequentially WITHIN one
# ontology (so a single row is internally consistent), but rows are produced in parallel
# ACROSS ontologies. That inflates wall figures. It is acceptable here only because the
# clustering key is `last_phase` + OUTCOME + structural counts -- none of which are
# wall-derived. Do NOT quote walls from this run; re-measure sequentially if a wall matters.
set -u
H=/data/dumontier/owl-reasoner-harness
LIST=$1; OUT=$2; P=${3:-6}; CAP=${4:-45}
: > "$OUT"
export CAP
# attribute.sh pretty-prints; compact each record to ONE line AT THE SOURCE, because under
# xargs -P multi-line records interleave and corrupt the file. Short single lines are written
# atomically, so parallel appends stay well-formed.
grep -v '^#' "$LIST" | grep -v '^$' | \
  xargs -P "$P" -I{} sh -c \
    "$H/scripts/attribute.sh {} 2>/dev/null | python3 -c 'import json,sys
try: print(json.dumps(json.load(sys.stdin)))
except Exception: pass'" >> "$OUT"
echo "ATTRIBUTION DONE: $(grep -c '^{' "$OUT") rows"
