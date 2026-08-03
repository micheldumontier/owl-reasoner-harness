#!/usr/bin/env bash
# rustdl leg WITH OUTPUT CAPTURE, for the MISSED net.
#
# The other three wrappers live in /data/dumontier/reasoners/; this one is in-tree
# because it is not a provisioned third-party reasoner but the system under test, and
# the MISSED net needs to point it at an arbitrary PINNED build (v0.4.13 main, a
# flag-flipped arm, a future branch) without editing anything.
#
#   MISSED_NET_RUSTDL       path to the pinned rustdl binary            (REQUIRED)
#   MISSED_NET_RUSTDL_ARGS  extra `classify` args, e.g. --pair-timeout-ms 1  (optional)
#   HARNESS_OUT_DIR         capture dir; <stem>.out gets rustdl's stdout    (optional)
#
# THREE DELIBERATE CHOICES:
#
# 1. stdout is REDIRECTED, not `tee`d. A pipe would make the wrapper exit with tee's
#    status, so a rustdl failure would read as exit 0 — the harness's `ErrReject` /
#    `ErrCrash` distinction would silently collapse into `Ok`. The cost is that
#    `--digest-output` sees an empty stdout and records no sha; the MISSED net does not
#    use the digest (it diffs normalised closures), so that is the cheaper loss.
#
# 2. Address space is capped at 24 GB. rustdl has a documented multi-GB RSS tail
#    (`ore_ont_11085` once reached 16.96 GB and a peer reached 237 GB on this host,
#    OOM-killing it and degrading every concurrent measurement). A cap turns that into
#    one `ErrCrash` row instead of a lost sweep. It DOES change behaviour on a
#    memory-tail ontology relative to an uncapped run — state it when comparing.
#
# 3. The binary is passed in and NOT hashed here. Hashing 46 MB per invocation would
#    add ~90 GB of reads over a full corpus; missed-net.sh verifies the sha ONCE,
#    before the sweep, and records it in the arm manifest.
set -u
: "${MISSED_NET_RUSTDL:?set MISSED_NET_RUSTDL to the pinned rustdl binary}"
# The harness probes `--reasoner --version` for the run header. Without this arm the
# probe falls through as if `--version` were an ONTOLOGY PATH, and the capture branch
# below writes a garbage-named file into the output directory (the three provisioned
# peer wrappers all do exactly that; missed-net.sh sweeps them out afterwards).
case "${1:-}" in
  --version | -V) exec "$MISSED_NET_RUSTDL" --version ;;
esac
ulimit -v $((24 * 1024 * 1024))
if [ -n "${HARNESS_OUT_DIR:-}" ]; then
  mkdir -p "$HARNESS_OUT_DIR"
  out="$HARNESS_OUT_DIR/$(basename "${1%.*}").out"
else
  out=/dev/null
fi
# shellcheck disable=SC2086  # ARGS is a deliberate word-split argument list
exec "$MISSED_NET_RUSTDL" classify ${MISSED_NET_RUSTDL_ARGS:-} "$1" > "$out"
