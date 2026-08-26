#!/usr/bin/env bash
# Run the three peer legs SEQUENTIALLY over the v0.4.14 151-ont tail.
# Sequential on purpose: a peer's wall is the target rustdl is measured against, and
# cross-leg contention would inflate it. Within a leg, 4 batches run concurrently
# (same as the 2026-08-01 baseline, so walls stay comparable).
H=/data/dumontier/owl-reasoner-harness
L=$H/scripts/triage-leg-tail151.sh
cd $H
echo "=== KONCLUDE $(date -Is) ==="
$L konclude /data/dumontier/reasoners/run-konclude.sh '{}' 120
echo "=== HERMIT $(date -Is) ==="
$L hermit /data/dumontier/reasoners/run-hermit.sh '{}' 120
echo "=== KM $(date -Is) ==="
$L km /data/dumontier/reasoners/run-km.sh '{}' 120
echo "=== ALL LEGS DONE $(date -Is) ==="
