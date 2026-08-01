#!/usr/bin/env bash
# Validate the rustdl side of the triage: are the 257 REALLY DNF at 120 s uncontended?
#
#   validate-dnf.sh <sample_size> [cap_secs]
#
# WHY THIS IS NOT OPTIONAL
# -----------------------
# Set A means "rustdl DNF and a peer classified". The peer half is measured directly, but
# the rustdl half is INHERITED from a 120 s re-run that executed FOUR ONTOLOGIES
# CONCURRENTLY. Concurrency inflates wall, so a borderline ontology could have been pushed
# past the cap and recorded as DNF while actually completing at, say, 110 s. Every such
# case is a phantom member of Set A -- an ontology rustdl can already classify, presented
# as an algorithmic gap.
#
# This matters more than usual here because the SAME confound has already bitten this arc
# twice: 55 of 312 "DNF" ontologies turned out to complete once given a larger budget, and
# a separate wall-clock-timeout measurement was found to be inflated 9x by running -P4.
#
# So: re-run a RANDOM sample strictly SEQUENTIALLY, one ontology at a time, nothing else
# heavy on the host, and report how many complete. A single completion means the 257 needs
# a full uncontended re-run before any of it is called a gap.
#
# Sampling is seeded and the seed is printed, so the sample is reproducible -- a sample
# nobody can reconstruct is not evidence.
set -u
N=${1:-20}
CAP=${2:-120}
SEED=${SEED:-20260801}
H=/data/dumontier/owl-reasoner-harness
LIST=$H/baselines/2026-08-01-dnf257-list.txt
CORPUS=/data/dumontier/ore-run/pool_sample/files
R=${RUSTDL:-/data/dumontier/rustdl/target/release/rustdl}

# Refuse to run alongside a sweep -- the whole point is an uncontended measurement.
#
# `pgrep -c` PRINTS "0" AND EXITS 1 when nothing matches, so the obvious
#   busy=$(pgrep -fc ... || echo 0)
# yields the two-line string "0\n0", and `[ "$busy" -gt 0 ]` then dies with
# "integer expression expected" -- the guard ERRORS OUT instead of evaluating, and
# execution falls through. It happened to fall through in the safe direction here,
# but a guard that errors is not a guard. Same shape as the `grep -c` bug that
# produced invalid JSON in attribute.sh; this family of tools reports "none found"
# through the exit code, not the output.
busy=$({ pgrep -fc 'owl-reasoner-harnes[s] run|Konclud[e]|run-hermi[t]|kobayashi-marus[t]' 2>/dev/null || true; } | head -1)
busy=${busy:-0}
if [ "$busy" -gt 0 ] && [ "${FORCE:-0}" != "1" ]; then
  echo "REFUSING: $busy measurement process(es) running. This check is only meaningful" >&2
  echo "uncontended -- that is the confound it exists to rule out. Wait, or FORCE=1." >&2
  exit 2
fi

python3 - "$LIST" "$N" "$SEED" > /tmp/dnf-sample.txt <<'PY'
import random, sys
lines = [l.strip() for l in open(sys.argv[1]) if l.strip()]
random.seed(int(sys.argv[3]))
print("\n".join(random.sample(lines, min(int(sys.argv[2]), len(lines)))))
PY

echo "validate-dnf: $(wc -l < /tmp/dnf-sample.txt) of $(wc -l < "$LIST") sampled, seed=$SEED, cap=${CAP}s, SEQUENTIAL"
echo "binary: $R  sha256: $(sha256sum "$R" | cut -c1-16)"
completed=0; dnf=0; other=0
while read -r stem; do
  t0=$(date +%s.%N)
  ( ulimit -v $((24*1024*1024)); RAYON_NUM_THREADS=1 timeout "$CAP" "$R" classify "$CORPUS/$stem.owl" ) \
      > /tmp/vd-out.txt 2>/dev/null
  rc=$?
  t1=$(date +%s.%N)
  w=$(python3 -c "print(f'{$t1-$t0:.1f}')")
  case $rc in
    0)   completed=$((completed+1)); echo "  COMPLETED  $stem  ${w}s   <-- PHANTOM Set A member";;
    124) dnf=$((dnf+1));             echo "  dnf        $stem  ${w}s";;
    *)   other=$((other+1));         echo "  err$rc     $stem  ${w}s";;
  esac
done < /tmp/dnf-sample.txt

echo
echo "RESULT: completed=$completed  dnf=$dnf  err=$other"
if [ "$completed" -gt 0 ]; then
  echo "!! $completed of the sample COMPLETE uncontended at ${CAP}s. The 257 list is"
  echo "   contaminated by contention from the 4-way re-run and MUST be re-measured"
  echo "   sequentially before any of it is characterised as an algorithmic gap."
  exit 1
fi
echo "The rustdl DNF side holds on this sample: no ontology completed uncontended."
