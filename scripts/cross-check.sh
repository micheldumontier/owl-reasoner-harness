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
# HermiT needs docker; KM is capped at 20 GB by its wrapper and CANNOT do pizza
# (237 GB / OOM, see REASONERS.md), so KM is run only on the small EL fixtures.
set -uo pipefail
cd "$(dirname "$0")/.."
N="python3 scripts/normalise.py"
R=/data/dumontier/rustdl
OUT="${1:-$(mktemp -d -t cross-check-XXXX)}"
mkdir -p "$OUT"
echo "artifacts: $OUT"

# fixture -> source ontology ; oracle owx
FIX="bibtex pizza ro sulo wine"
declare -A SRC ORACLE
for k in $FIX; do SRC[$k]="$R/ontologies/real/$k.ofn"; ORACLE[$k]="$R/ontologies/real/konclude-input/$k-classified.owx"; done
KM_OK="bibtex"   # KM: small EL only, see cap note above

printf '%-8s %-7s %-22s %-22s %-22s\n' fixture oracle rustdl hermit km
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
    r=$($N compare "$OUT/$k.rustdl.tsv" "$OUT/$k.kon.tsv" | awk '/^(FP|MISSED)/{printf "%s=%s ",$1,$2}')
  else r="exit=$rc"; fi

  # HermiT (docker). Wall includes a 0.56s JVM floor -- never quote it as reasoning time.
  timeout 900 ./wrappers/run-hermit.sh "${SRC[$k]}" "$OUT/$k.hermit.txt" >"$OUT/$k.hermit.log" 2>&1
  rc=$?
  if [ $rc -eq 0 ] && [ -s "$OUT/$k.hermit.txt" ]; then
    $N normalise --format hermit "$OUT/$k.hermit.txt" -o "$OUT/$k.hermit.tsv" 2>/dev/null
    h=$($N compare "$OUT/$k.hermit.tsv" "$OUT/$k.kon.tsv" | awk '/^(FP|MISSED)/{printf "%s=%s ",$1,$2}')
  else h="exit=$rc"; fi

  m="not-run"
  case " $KM_OK " in *" $k "*)
    timeout 300 ./wrappers/run-km.sh "${SRC[$k]}" >"$OUT/$k.km.json" 2>"$OUT/$k.km.err"
    rc=$?
    if [ $rc -eq 0 ]; then
      $N normalise --format km "$OUT/$k.km.json" --ontology "${SRC[$k]}" -o "$OUT/$k.km.tsv" 2>/dev/null
      m=$($N compare "$OUT/$k.km.tsv" "$OUT/$k.kon.tsv" | awk '/^(FP|MISSED)/{printf "%s=%s ",$1,$2}')
    else m="exit=$rc"; fi ;;
  esac

  printf '%-8s %-7s %-22s %-22s %-22s\n' "$k" "$n_oracle" "$r" "$h" "$m"
done
