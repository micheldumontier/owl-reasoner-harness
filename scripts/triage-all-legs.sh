#!/usr/bin/env bash
# Run the three peer legs SEQUENTIALLY. Sequential on purpose: a peer's wall is the
# target rustdl is measured against, and cross-leg contention would inflate it. Within
# a leg, 4 batches run concurrently (documented in the run header).
H=/data/dumontier/owl-reasoner-harness
cd $H
echo "=== KONCLUDE $(date -Is) ==="
./runs/triage/leg.sh konclude /data/dumontier/reasoners/run-konclude.sh '{}' 120
echo "=== HERMIT $(date -Is) ==="
./runs/triage/leg.sh hermit /data/dumontier/reasoners/run-hermit.sh '{}' 120
echo "=== KM $(date -Is) ==="
./runs/triage/leg.sh km /data/dumontier/reasoners/run-km.sh '{}' 120
echo "=== ALL LEGS DONE $(date -Is) ==="
