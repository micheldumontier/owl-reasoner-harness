#!/usr/bin/env bash
# Kobayashi-MaRust v1.3.0 @f4738bc, PINNED under bin/ (built from the v1.3.0 tag).
#
# ROUTE = `auto`, NOT `production_all`. run-km-latest.sh uses production_all because
# on v0.2.32 KM's bare default DNF'd on ore_ont_10019 while production_all took
# 0.25 s. MEASURED ON v1.3.0 (2026-09-16): `auto` classifies ore_ont_10019 in 175 ms
# and production_all in 145 ms — the rationale is STALE. `auto` is KM's own shipped
# default ("learned source-profile decision tree (classify default)"), so using it
# measures KM as it ships rather than as we tuned it two minor versions ago.
#
# THE 20GB ulimit IS A NO-OP ON DARWIN and this wrapper runs on the Mac. v0.2.32
# reached 237 GB on pizza uncapped; v1.3.0 does NOT reproduce that (pizza completes
# in well under a second). The host has 128 GB. If a future run on a Linux host
# needs the cap, copy the `ulimit -v` guard from run-km-latest.sh.
#
# NOTE ON CONVENTIONS, load-bearing for any closure comparison:
#  - On an INCONSISTENT KB, KM reports `consistent: false` with EMPTY subsumptions
#    and EMPTY unsatisfiable. rustdl instead marks every class unsatisfiable. Do not
#    diff those two shapes directly.
#  - v0.2.32 emitted Tseitin definers (Q_N) in `subsumptions`; v1.3.0 emits none on
#    pizza. Filter defensively before any closure comparison.
B=${KM_BIN_DIR:-$(cd "$(dirname "$0")/../bin" && pwd)}/km-v130-f4738bc
if [ -n "${HARNESS_OUT_DIR:-}" ]; then
  mkdir -p "$HARNESS_OUT_DIR"
  exec bash -c "set -o pipefail; \"\$0\" classify --route auto \"\$1\" | tee \"\$2\"" \
       "$B" "$1" "$HARNESS_OUT_DIR/$(basename "${1%.*}").json"
fi
exec "$B" classify --route auto "$1"
