#!/usr/bin/env bash
# Kobayashi-MaRust v0.2.11 @4eb5832, PINNED under bin/ (built in a throwaway /tmp
# worktree). Invocation is `km classify --route production_all` — the ROUTE IS A CLI
# FLAG, not an env bundle. An earlier version of this wrapper exported the KM_* vars
# directly onto `kobayashi-marust` and reproduced KM's DNF instead of its 0.25 s;
# the discriminating control on ore_ont_10019 caught it.
#
# production_all is KM's OWN WINNING BUNDLE, not its default: KM's bare default DNFs
# on ore_ont_10019 where production_all takes 0.25 s. Comparing against the default
# would understate KM.
#
# THE 20GB CAP IS MANDATORY, NOT TUNING: uncapped, KM reached 237 GB on pizza (a
# 100-class ontology) and was OOM-killed after 898 s, degrading every other
# measurement on the host. 20 GB matches upstream AGENTS.md benchmark config.
#
# NOTE: KM emits Tseitin definers (Q_1, Q_10, ...) in `subsumptions`; filter them
# before any closure comparison. This run judges OUTCOME only.
B=/data/dumontier/owl-reasoner-harness/bin/km-v0211-4eb5832
ulimit -v $((20*1024*1024))
if [ -n "${HARNESS_OUT_DIR:-}" ]; then
  mkdir -p "$HARNESS_OUT_DIR"
  exec sh -c "\"\$0\"/km classify --route production_all \"\$1\" | tee \"\$2\"" \
       "$B" "$1" "$HARNESS_OUT_DIR/$(basename "${1%.*}").json"
fi
exec "$B/km" classify --route production_all "$1"
