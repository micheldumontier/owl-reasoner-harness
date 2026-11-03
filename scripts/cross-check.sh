#!/usr/bin/env bash
# Cross-reasoner IDENTITY check: normalise several reasoners on the same ontology and
# diff each against the committed Konclude oracle. Expect FP=0 / MISSED=0 everywhere
# on the curated fixtures -- these are ontologies where rustdl is documented complete
# and Konclude/HermiT are the oracle, so any nonzero here is a NORMALISER bug first.
#
# WHY THIS EXISTS AND `gate` IS NOT ENOUGH: closure SIZE is invariant under
# relabelling. Dropping abbreviatedIRI expansion left all 11 gate counts exact while
# corrupting 344 of wine's pair-halves; only a cross-reasoner diff (which compares
# IRIs, not counts) catches that class of bug. Measured: it moved wine
# HermiT-vs-Konclude from FP=482 to FP=0.
#
# Usage: scripts/cross-check.sh [OUTDIR]   (default: a fresh mktemp dir)
# HermiT needs docker. KM must stay capped at 20 GB by its wrapper (uncapped it hit
# 237 GB / OOM -- see REASONERS.md), and is run here only on the small EL fixtures.
# NOTE: "KM cannot do pizza" was HOST-SPECIFIC. Measured 2026-08-30 on an idle 17 GB
# Linux box, KM classifies pizza under the same cap (479 subsumptions, rc=0) -- but
# with MISSED=20 against the Konclude==HermiT oracle (the 20 X ⊑ InterestingPizza
# rows), so it is excluded here for INCOMPLETENESS, not for capacity.
set -uo pipefail
cd "$(dirname "$0")/.."
N="python3 scripts/normalise.py"
R=/data/dumontier/rustdl
OUT="${1:-$(mktemp -d -t cross-check-XXXX)}"
mkdir -p "$OUT"
echo "artifacts: $OUT"

# `normalise compare` exits 1 on a pair FP or an unsat FP (a class the candidate calls
# unsatisfiable that the oracle has satisfiable). Its exit code is the verdict: this
# script used to read only the FP/MISSED lines, so an unsat FP, which the pair diff
# cannot show, passed in silence. Any failing compare makes the script exit 1.
FAILED=0
# Called inside $(...), a subshell, so it cannot set FAILED itself: it prints FAIL in
# the cell and the caller records it.
cmp_cell() {  # cmp_cell CAND_TSV ORACLE_TSV -> prints the cell, with FAIL on rc != 0
  local out rc
  out=$($N compare "$1" "$2")
  rc=$?
  printf '%s\n' "$out" | awk '/^(FP|MISSED|unsat_FP|unsat_MISSED) /{printf "%s=%s ",$1,$2}'
  if [ $rc -ne 0 ]; then
    # rc 1 with an FP line is a verdict; without one, compare itself crashed.
    if printf '%s\n' "$out" | grep -q '^FP '; then printf 'FAIL(rc=%s)' "$rc"
    else printf 'ERR(rc=%s)' "$rc"; fi
  fi
}

# fixture -> source ontology ; oracle owx
FIX="bibtex pizza ro sulo wine"
declare -A SRC ORACLE
for k in $FIX; do SRC[$k]="$R/ontologies/real/$k.ofn"; ORACLE[$k]="$R/ontologies/real/konclude-input/$k-classified.owx"; done
KM_OK="bibtex"   # KM: small EL only, see cap note above

printf '%-8s %-7s %-56s %-56s %-56s\n' fixture oracle rustdl hermit km
for k in $FIX; do
  [ -f "${ORACLE[$k]}" ] || { printf '%-8s SKIP (no oracle)\n' "$k"; continue; }
  $N normalise --format konclude "${ORACLE[$k]}" -o "$OUT/$k.kon.tsv" 2>/dev/null
  n_oracle=$(grep -vc '^#' "$OUT/$k.kon.tsv")

  # rustdl. --pair-timeout-ms bounds wine's hard SROIQ pair tail (unbounded it DNFs).
  "$R/target/release/rustdl" classify --pair-timeout-ms 200 "${SRC[$k]}" \
      >"$OUT/$k.rustdl.out" 2>"$OUT/$k.rustdl.err"
  rc=$?
  if [ $rc -eq 0 ]; then
    $N normalise --format rustdl "$OUT/$k.rustdl.out" -o "$OUT/$k.rustdl.tsv" 2>/dev/null
    r=$(cmp_cell "$OUT/$k.rustdl.tsv" "$OUT/$k.kon.tsv"); [[ $r == *FAIL* || $r == *ERR* ]] && FAILED=1
  else r="exit=$rc"; fi

  # HermiT (docker). Wall includes a 0.56s JVM floor -- never quote it as reasoning time.
  timeout 900 ./wrappers/run-hermit.sh "${SRC[$k]}" "$OUT/$k.hermit.txt" >"$OUT/$k.hermit.log" 2>&1
  rc=$?
  if [ $rc -eq 0 ] && [ -s "$OUT/$k.hermit.txt" ]; then
    $N normalise --format hermit "$OUT/$k.hermit.txt" -o "$OUT/$k.hermit.tsv" 2>/dev/null
    h=$(cmp_cell "$OUT/$k.hermit.tsv" "$OUT/$k.kon.tsv"); [[ $h == *FAIL* || $h == *ERR* ]] && FAILED=1
  else h="exit=$rc"; fi

  m="not-run"
  case " $KM_OK " in *" $k "*)
    timeout 300 ./wrappers/run-km.sh "${SRC[$k]}" >"$OUT/$k.km.json" 2>"$OUT/$k.km.err"
    rc=$?
    if [ $rc -eq 0 ]; then
      $N normalise --format km "$OUT/$k.km.json" --ontology "${SRC[$k]}" -o "$OUT/$k.km.tsv" 2>/dev/null
      m=$(cmp_cell "$OUT/$k.km.tsv" "$OUT/$k.kon.tsv"); [[ $m == *FAIL* || $m == *ERR* ]] && FAILED=1
    else m="exit=$rc"; fi ;;
  esac

  printf '%-8s %-7s %-56s %-56s %-56s\n' "$k" "$n_oracle" "$r" "$h" "$m"
done

if [ $FAILED -ne 0 ]; then
  echo "cross-check: FAILED (FAIL = a pair FP or an unsat FP; ERR = compare itself failed)"
  exit 1
fi
echo "cross-check: no FP and no unsat FP"
