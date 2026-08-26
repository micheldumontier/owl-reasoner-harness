#!/usr/bin/env bash
# rustdl leg with an INTERNAL global deadline matched to the harness cap.
#
# WHY THIS EXISTS. `--global-timeout-ms` defaults to 0 (unbounded), so a run capped
# only by the harness is killed EXTERNALLY and prints nothing — the worst of both
# worlds, because classify already degrades gracefully to its saturation closure when
# it hits an INTERNAL deadline. Measured on ore_ont_11311: unbounded + external kill =
# no output; `--global-timeout-ms 5000` = the full 10,658-row hierarchy in 5.8 s, which
# is byte-identical to `--saturation-only` and to KM v0.2.32's 79,803-pair closure.
#
#   MISSED_NET_RUSTDL         pinned binary                        (REQUIRED)
#   MISSED_NET_GLOBAL_MS      internal deadline in ms              (REQUIRED)
#   MISSED_NET_RUSTDL_ARGS    extra classify args                  (optional)
set -u
: "${MISSED_NET_RUSTDL:?set MISSED_NET_RUSTDL}"
: "${MISSED_NET_GLOBAL_MS:?set MISSED_NET_GLOBAL_MS}"
case "${1:-}" in --version|-V) exec "$MISSED_NET_RUSTDL" --version ;; esac
ulimit -v $((24 * 1024 * 1024))
if [ -n "${HARNESS_OUT_DIR:-}" ]; then
  mkdir -p "$HARNESS_OUT_DIR"; out="$HARNESS_OUT_DIR/$(basename "${1%.*}").out"
else out=/dev/null; fi
# shellcheck disable=SC2086
exec "$MISSED_NET_RUSTDL" classify --global-timeout-ms "$MISSED_NET_GLOBAL_MS" \
     ${MISSED_NET_RUSTDL_ARGS:-} "$1" > "$out"
