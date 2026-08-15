#!/usr/bin/env bash
# release-corpus-report.sh — the per-release corpus report and verdict gate.
#
# Produces the numbers that go in a release note, and FAILS if the release changed
# an answer. Modelled on the discipline visible in Kobayashi-MaRust's releases
# (a fixed named subset, per-release wall and RSS percentiles, sweeps identified by
# binary hash) — note their coverage figure is the AUTO ROUTE's, published from a
# hand-run sweep via CHANGELOG.md, not a CI gate. This is the local equivalent.
#
#   ./scripts/release-corpus-report.sh v0.4.19 /path/to/rustdl [BASELINE_JSON]
#
# env: JOBS (default 8), CAP (default 60), LIST (default the 400-ont population)
#
# WHY THIS EXISTS, beyond nice numbers: on 2026-08-15 a change passed BOTH
# pre-registered gate clauses (`ok -> dnf` = 0, dMISSED +0.78%) while flipping
# ore_ont_16372 from `consistent=false` to `consistent=true` on an ontology three
# reasoners call inconsistent. Neither clause could see it — both arms completed, and
# the MISSED net excludes unsat classes on both sides. Verdict correctness needs its
# own gate, and this is it.
set -euo pipefail
H=$(cd "$(dirname "$0")/.." && pwd)
VERSION=${1:?usage: release-corpus-report.sh VERSION RUSTDL_BIN [BASELINE_JSON]}
BIN=${2:?usage: release-corpus-report.sh VERSION RUSTDL_BIN [BASELINE_JSON]}
BASELINE=${3:-}
JOBS=${JOBS:-8}; CAP=${CAP:-60}
LIST=${LIST:-$H/baselines/2026-08-03-missed-net-population.txt}
CORPUS=${CORPUS:-/data/dumontier/ore-run/pool_sample/files}
SCRATCH=${SCRATCH:-/mnt/um-share-drive/dumontier/missed-net}
TAG="relreport-$VERSION"
RUN="$SCRATCH/runs/$TAG"; RAW="$SCRATCH/raw/$TAG"
rm -rf "$RUN"; mkdir -p "$RUN" "$RAW"

# PIN THE BINARY BY HASH AND RECORD IT. A shared build path has twice produced a
# measurement of the wrong configuration in this project; one of those was a 2h scan.
sha=$(sha256sum "$BIN" | cut -d' ' -f1)
ver=$("$BIN" --info 2>/dev/null | head -1 || echo unknown)
echo "release report $VERSION: $ver sha ${sha:0:12} cap ${CAP}s jobs $JOBS n=$(wc -l < "$LIST")"

# One JSONL per chunk: concurrent writers on a single --out interleave and corrupt.
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
split -n "l/$JOBS" -d "$LIST" "$d/c"
for c in "$d"/c*; do
  MISSED_NET_RUSTDL="$BIN" HARNESS_OUT_DIR="$RAW" \
  "$H/target/release/owl-reasoner-harness" run \
    --corpus "$CORPUS" --only "$c" \
    --reasoner "$H/wrappers/run-rustdl-json.sh" --args '{}' \
    --cap-secs "$CAP" --threads 1 --ext owl \
    --out "$RUN/$(basename "$c").jsonl" > "$RUN/$(basename "$c").log" 2>&1 &
done
wait

mkdir -p "$H/baselines"
OUT_JSON="$H/baselines/corpus-report-$VERSION.json"
OUT_MD="$H/baselines/corpus-report-$VERSION.md"
set +e
python3 "$H/scripts/release-corpus-report.py" \
  --run-dir "$RUN" --raw-dir "$RAW" --version "$VERSION" --binary-sha "$sha" \
  --cap-secs "$CAP" ${BASELINE:+--baseline "$BASELINE"} \
  --out-json "$OUT_JSON" --out-md "$OUT_MD"
rc=$?
set -e
echo
echo "wrote $OUT_JSON"
echo "wrote $OUT_MD   <- paste into the release notes"
[ $rc -ne 0 ] && echo "GATE FAILED — an answer changed. Do not release." >&2
exit $rc
