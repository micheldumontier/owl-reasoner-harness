#!/usr/bin/env bash
# Phase 2 attribution for ONE ontology: where does rustdl spend itself, and what shape is
# the input? Emits a single JSON line so N of these pool into a clusterable table.
#
#   attribute.sh <stem> [corpus_dir]
#
# METHOD NOTES THAT ARE LOAD-BEARING
# ----------------------------------
# * The `# wall breakdown ms:` banner PRINTS ONLY ON COMPLETION, so it is useless on
#   exactly the ontologies under study. RUSTDL_TRACE_RSS phase markers are used instead:
#   the LAST marker emitted localises the stall.
# * Component boundaries are probed SEPARATELY (tbox-stats = conversion, --saturation-only
#   = saturation without tableau) because in this codebase every wrong hypothesis about
#   this cluster was killed by a component-boundary isolation, and every hypothesis
#   supported only by a plausible arithmetic match survived longer than it deserved.
# * EVERY run is capped in BOTH wall and address space. One ontology here reaches 21.7 GB
#   and a historical one hit 158 GB; an uncapped run once OOM-killed this host and
#   corrupted a live sweep. Runs are SEQUENTIAL for the same reason.
set -u
stem=$1
CORPUS=${2:-/data/dumontier/ore-run/pool_sample/files}
F=$CORPUS/$stem.owl
R=${RUSTDL:-/data/dumontier/rustdl/target/release/rustdl}
CAP=${CAP:-120}
VCAP_KB=${VCAP_KB:-$((24*1024*1024))}     # 24 GB address-space ceiling per probe

j() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

# --- capped probe helper: prints "<exit> <wall_s>" and leaves output in $2 -------------
probe() {                      # probe <outfile> <cmd...>
  local out=$1; shift
  local t0 t1 rc
  t0=$(date +%s.%N)
  ( ulimit -v "$VCAP_KB"; timeout "$CAP" "$@" ) > "$out" 2>&1
  rc=$?
  t1=$(date +%s.%N)
  echo "$rc $(python3 -c "print(f'{$t1-$t0:.2f}')")"
}

D=$(mktemp -d); trap 'rm -rf "$D"' EXIT

# --- 1. structural profile (cheap, no reasoning) ---------------------------------------
# Counted from the functional-syntax source. A count is a count; the GATE is a different
# question and must never be inferred from these (grep != gate: a grep-based estimate of
# gate impact once gave 67 where the real gate-probe found ~40).
bytes=$(stat -c%s "$F" 2>/dev/null || echo 0)
# `grep -c` PRINTS "0" and EXITS 1 when there is no match, so a `|| echo 0` fallback
# emits "0\n0" and produces invalid JSON. Take the first line and default only when the
# output is genuinely empty (unreadable file).
cnt() { local c; c=$({ grep -c "$1" "$F" 2>/dev/null || true; } | head -1); echo "${c:-0}"; }
classes=$(grep -o 'Declaration(Class(' "$F" 2>/dev/null | wc -l)
read -r ts_rc ts_wall <<<"$(probe "$D/tbox" "$R" tbox-stats "$F")"
read -r sat_rc sat_wall <<<"$(probe "$D/sat" "$R" classify --saturation-only "$F")"

# --- 2. phase attribution on the FULL classify: last marker reached ---------------------
t0=$(date +%s.%N)
( ulimit -v "$VCAP_KB"; RAYON_NUM_THREADS=1 RUSTDL_TRACE_RSS=1 timeout "$CAP" \
    "$R" classify "$F" ) > "$D/full" 2> "$D/rss"
full_rc=$?
t1=$(date +%s.%N)
full_wall=$(python3 -c "print(f'{$t1-$t0:.2f}')")

last_phase=$(grep -o '\[rss\] [a-z_]*=' "$D/rss" 2>/dev/null | tail -1 | sed 's/\[rss\] //; s/=//')
peak_rss=$(grep -o '\[rss\] [a-z_]*=[0-9.]*' "$D/rss" 2>/dev/null | sed 's/.*=//' | sort -g | tail -1)
mode=$(grep -m1 '^# mode:' "$D/full" 2>/dev/null | sed 's/^# mode: *//')
frag=$(grep -m1 '^# fragment:' "$D/full" 2>/dev/null | sed 's/^# fragment: *//')
crules=$(grep -m1 -o 'concept_rules[ =:]*[0-9]*' "$D/tbox" 2>/dev/null | grep -o '[0-9]*$')

# --- 3. channel ablation: is the data channel load-bearing? ----------------------------
# Answers "would disabling this channel change the OUTCOME", which is the question that
# separates a real lever from inert axiom volume. A prior investigation found 4.2-6.6 M
# disjointness axioms that were entirely INERT -- output byte-identical without them.
read -r nodp_rc nodp_wall <<<"$(probe "$D/nodp" env RUSTDL_DATA_PROPERTIES=0 "$R" classify "$F")"

outcome() { [ "$1" = 124 ] && echo dnf || { [ "$1" = 0 ] && echo ok || echo "err$1"; }; }

cat <<JSON
{"ont": $(j "$stem"), "bytes": $bytes, "classes": $classes,
 "subclassof": $(cnt 'SubClassOf('), "equivclasses": $(cnt 'EquivalentClasses('),
 "some": $(cnt 'ObjectSomeValuesFrom('), "all": $(cnt 'ObjectAllValuesFrom('),
 "omax": $(cnt 'ObjectMaxCardinality('), "omin": $(cnt 'ObjectMinCardinality('),
 "dmax": $(cnt 'DataMaxCardinality('), "dmin": $(cnt 'DataMinCardinality('),
 "func": $(cnt 'FunctionalObjectProperty('), "invfunc": $(cnt 'InverseFunctionalObjectProperty('),
 "oneof": $(cnt 'ObjectOneOf('), "hasvalue": $(cnt 'ObjectHasValue('),
 "trans": $(cnt 'TransitiveObjectProperty('), "symm": $(cnt 'SymmetricObjectProperty('),
 "chain": $(cnt 'ObjectPropertyChain('), "inverseof": $(cnt 'InverseObjectProperties('),
 "classassert": $(cnt 'ClassAssertion('), "opassert": $(cnt 'ObjectPropertyAssertion('),
 "dpassert": $(cnt 'DataPropertyAssertion('), "complement": $(cnt 'ObjectComplementOf('),
 "disjoint": $(cnt 'DisjointClasses('), "disjointunion": $(cnt 'DisjointUnion('),
 "conversion_outcome": $(j "$(outcome $ts_rc)"), "conversion_wall_s": $ts_wall,
 "saturation_outcome": $(j "$(outcome $sat_rc)"), "saturation_wall_s": $sat_wall,
 "full_outcome": $(j "$(outcome $full_rc)"), "full_wall_s": $full_wall,
 "last_phase": $(j "${last_phase:-NONE}"), "peak_trace_rss_gb": ${peak_rss:-null},
 "mode": $(j "${mode:-NA}"), "fragment": $(j "${frag:-NA}"), "concept_rules": ${crules:-null},
 "nodata_outcome": $(j "$(outcome $nodp_rc)"), "nodata_wall_s": $nodp_wall}
JSON
