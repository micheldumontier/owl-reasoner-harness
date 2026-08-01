#!/usr/bin/env python3
"""Cluster Set A by (last phase reached x structural signature) — Phase 2 of the plan.

WHY BY THIS KEY, AND NOT BY INTUITION
-------------------------------------
The previous taxonomy for this tail ("Bucket A per-pair-bound" vs "Bucket B
label-cache-bound") was FALSIFIED: it turned out to be an artifact of WHICH BUDGET
EACH PHASE HONOURS, not of two mechanisms. `--pair-timeout-ms` does not bound the
label-cache build, so "still DNF at pair=5ms" was read as "cost is outside the
per-pair loop" when it only meant "that budget does not apply here".

So this clusters on two things that are *observed*, not inferred:

  last_phase  the last RUSTDL_TRACE_RSS marker the process actually emitted before
              the cap. This is the one honest phase signal on a DNF, because the
              `# wall breakdown ms:` banner prints only on COMPLETION -- and its
              tier_walk field is a residual subtraction that mis-attributes all
              unbudgeted prep to the tier walk anyway (ore_ont_1028 reports
              tier_walk=7198 ms for an 80 ms tier walk).

  signature   a coarse structural bucket from counts in the source.

A cluster is a HYPOTHESIS GENERATOR, not a finding. Two ontologies sharing a key may
still fail for different reasons; the key exists so that per-cluster root-causing has
a defensible sample rather than whichever ontology was in front of us. This arc twice
investigated a cluster because it was salient rather than because it was the largest
tractable one.
"""

import argparse
import json
import pathlib
import sys
from collections import Counter, defaultdict


def signature(r):
    """Coarse structural bucket. Deliberately few, wide categories: a fine-grained
    key would produce clusters of size 1 and simply rename the input list."""
    cls = r.get("classes") or 0
    dp = r.get("dpassert") or 0
    abox = (r.get("classassert") or 0) + (r.get("opassert") or 0)
    card = (r.get("omax") or 0) + (r.get("omin") or 0) + (r.get("dmax") or 0) + (r.get("dmin") or 0)
    nom = (r.get("oneof") or 0) + (r.get("hasvalue") or 0)
    disj = (r.get("disjoint") or 0) + (r.get("complement") or 0)
    forall = r.get("all") or 0

    # Ordered most-specific-first; the first match wins, so the order encodes which
    # feature we believe dominates when several are present.
    if dp >= 1000:
        return "data-flood"
    if cls >= 20000:
        return "many-classes"
    if nom and card:
        return "nominal+cardinality"
    if forall and disj:
        return "forall+disjointness"
    if card:
        return "cardinality"
    if nom:
        return "nominal"
    if abox >= 1000:
        return "abox-heavy"
    if cls <= 100:
        return "small-dense"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--attrib", required=True, help="JSONL of attribute.sh rows")
    ap.add_argument("--peers", help="triage table JSONL, to attach the peer target wall")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    rows = [json.loads(l) for l in pathlib.Path(a.attrib).read_text().splitlines() if l.strip()]
    peers = {}
    if a.peers:
        for l in pathlib.Path(a.peers).read_text().splitlines():
            if l.strip():
                p = json.loads(l)
                peers[p["ont"]] = p

    clusters = defaultdict(list)
    for r in rows:
        r["signature"] = signature(r)
        key = (r.get("last_phase", "NONE"), r["signature"])
        pk = peers.get(r["ont"], {})
        best = [pk.get(f"{p}_wall_s") for p in ("konclude", "hermit", "km") if pk.get(f"{p}_wall_s")]
        r["peer_best_s"] = min(best) if best else None
        clusters[key].append(r)

    ordered = sorted(clusters.items(), key=lambda kv: -len(kv[1]))
    print(f"{len(rows)} ontologies -> {len(ordered)} clusters\n")
    print(f"{'last_phase':<22}{'signature':<22}{'n':>4}  {'med rustdl':>10} {'med peer':>9}  ratio")
    print("-" * 78)
    for (phase, sig), members in ordered:
        n = len(members)
        pw = sorted(m["peer_best_s"] for m in members if m.get("peer_best_s"))
        med_peer = pw[len(pw) // 2] if pw else None
        # rustdl DNF'd on all of these, so its wall is the cap; report the cap and
        # make the ratio a LOWER bound rather than pretending to know the true wall.
        med_rustdl = 120.0
        ratio = f"{med_rustdl / med_peer:>6.0f}x" if med_peer else "     -"
        mp = f"{med_peer:9.2f}" if med_peer else "        -"
        print(f"{phase:<22}{sig:<22}{n:>4}  {'>=120.0':>10} {mp}  {ratio}")

    print("\nrustdl wall is the CAP (every one of these DNF'd), so every ratio is a LOWER bound.")
    print("\nphase totals:", dict(Counter(r.get("last_phase", "NONE") for r in rows)))
    print("signature totals:", dict(Counter(r["signature"] for r in rows)))

    # A cluster nobody can act on is noise; surface where the leverage is.
    print("\nLargest clusters carry the most leverage IF the mechanism is shared -- which is")
    print("a hypothesis to test per cluster, not a conclusion. Root-cause the top 3 first.")

    if a.out:
        pathlib.Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
