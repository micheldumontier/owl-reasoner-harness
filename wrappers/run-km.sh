#!/usr/bin/env bash
# Kobayashi-MaRust @c6ced84. Two-stage: ofn -> JSON -> engine (stdin).
# THE 20GB CAP IS MANDATORY, NOT TUNING: uncapped, KM reached 237 GB on pizza
# (a 100-class ontology) and was OOM-killed after 898 s, degrading every other
# measurement on the host. 20 GB matches the upstream AGENTS.md benchmark config.
# NOTE: KM emits Tseitin definers (Q_1, Q_10, ...) in `subsumptions`; filter them
# before any closure comparison.
E=/data/dumontier/kobayashi-marust/engine/target/release
ulimit -v $((20*1024*1024))
# HARNESS_OUT_DIR, if set, tees KM's JSON to a file so outcome can be decided from
# content (see run-konclude.sh). stdout is preserved either way.
if [ -n "${HARNESS_OUT_DIR:-}" ]; then
  mkdir -p "$HARNESS_OUT_DIR"
  exec sh -c "$E/ofn \"\$1\" | $E/kobayashi-marust | tee \"\$2\"" _ "$1" \
       "$HARNESS_OUT_DIR/$(basename "${1%.*}").json"
fi
exec sh -c "$E/ofn \"\$1\" | $E/kobayashi-marust" _ "$1"
