#!/usr/bin/env python3
"""Partition the rustdl-DNF set by peer outcome: Set A (gap) / B (intrinsic) / C (disagreement).

THE POINT OF THIS PARTITION
---------------------------
rustdl DNF + a peer CLASSIFIED  => an algorithmic gap in rustdl, and the peer's wall is
                                   the target. This is the work set.
rustdl DNF + no peer CLASSIFIED => intrinsic hardness for this generation of reasoners.
                                   Record it and stop; engine work here has no evidence
                                   behind it.

Everything downstream is scoped to Set A, so the cost of getting this wrong is that all
later phases aim at the wrong ontologies.

WHAT COUNTS AS A PEER SUCCESS
-----------------------------
Only `CLASSIFIED` -- meaning the peer parsed the input AND declared a real class. The
distinction matters because Konclude exits 0 on junk while writing an empty hierarchy, so
an exit-code-derived "ok" is not evidence of anything (see scripts/triage.py).

`EMPTY` and `NO_OUTPUT` are FRONT-END failures, and are reported on their own line rather
than folded into either A or B. Folding them into B would claim "no reasoner can do this"
when the truth is "that reasoner could not read it", and a DNF roster that conflates a
converter gap with a reasoning limit is unactionable -- the corpus history here already
records ~23% of ORE being rejected for an anonymous-individuals converter gap, which was
a front-end fix, not a reasoning one.

SET C IS A SOUNDNESS SIGNAL, NOT A PERFORMANCE ONE
--------------------------------------------------
Where two peers both classify an ontology but disagree on closure size, at least one is
wrong. That matters because KM is documented unsound on ~10 ORE ontologies (concrete-domain
collapse) and Konclude is documented to UNDER-report on at least one (10407, where rustdl
matched HermiT). So a disagreement is a reason to adjudicate against Konclude UNION HermiT
rather than to trust a single oracle. Membership in C does not remove an ontology from A or
B -- it is an orthogonal flag.
"""

import argparse
import json
import pathlib
import sys
from collections import Counter, defaultdict


def load(path):
    """Absent or not-yet-run legs load as empty, so the partition can be run
    PROVISIONALLY mid-sweep -- it reports which peers are missing rather than
    silently treating an unrun peer as a peer that failed."""
    rows = {}
    if not path:
        return rows
    p = pathlib.Path(path)
    if not p.exists():
        return rows
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows[r["ont"]] = r
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dnf-list", required=True)
    ap.add_argument("--konclude")
    ap.add_argument("--hermit")
    ap.add_argument("--km")
    ap.add_argument("-o", "--out", required=True, help="triage table JSONL")
    a = ap.parse_args()

    onts = [
        l.strip()
        for l in pathlib.Path(a.dnf_list).read_text().splitlines()
        if l.strip() and not l.startswith("#")
    ]
    peers = {"konclude": load(a.konclude), "hermit": load(a.hermit), "km": load(a.km)}
    present = [k for k, v in peers.items() if v]
    missing_peers = [k for k, v in peers.items() if not v]

    table, tally = [], Counter()
    coverage = defaultdict(Counter)
    for ont in onts:
        row = {"ont": ont, "rustdl": "dnf"}
        solvers = []
        sizes = {}
        for pk in present:
            r = peers[pk].get(ont)
            if r is None:
                row[pk] = "NOT_RUN"
                coverage[pk]["NOT_RUN"] += 1
                continue
            row[pk] = r["verdict"]
            row[f"{pk}_wall_s"] = r.get("wall_s")
            row[f"{pk}_rss_kb"] = r.get("rss_kb")
            coverage[pk][r["verdict"]] += 1
            if r["verdict"] == "CLASSIFIED":
                solvers.append(pk)
                if r.get("pairs") is not None:
                    sizes[pk] = r["pairs"]
                    row[f"{pk}_pairs"] = r["pairs"]

        row["solvers"] = solvers
        row["set"] = "A" if solvers else "B"
        # Disagreement flag: >=2 peers classified and their closure sizes differ.
        #
        # DELIBERATELY ONE-SIDED. Differing sizes prove disagreement; EQUAL sizes prove
        # nothing, because closure size is invariant under relabelling -- two normaliser
        # bugs in this very repo (unexpanded abbreviatedIRI, unresolved relative IRIs)
        # each corrupted hundreds of pairs while leaving the count untouched. So this
        # flag is a cheap LOWER BOUND on Set C, computable for all 257, and the members
        # it finds are real. The actual set-difference (normalise.py compare, on the
        # retained hierarchies) is what establishes the true Set C, and is affordable
        # only because Set A is smaller than 257.
        row["disagree"] = len(set(sizes.values())) > 1 if len(sizes) >= 2 else False
        row["disagree_basis"] = "size-only (lower bound)" if len(sizes) >= 2 else "n/a"
        # Front-end failure is recorded, never silently absorbed into A or B.
        row["frontend_fail"] = [
            pk for pk in present if row.get(pk) in ("EMPTY", "NO_OUTPUT")
        ]
        tally[row["set"]] += 1
        if row["disagree"]:
            tally["C(disagree)"] += 1
        table.append(row)

    pathlib.Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in table))

    setA = [r for r in table if r["set"] == "A"]
    print(f"rustdl-DNF population: {len(onts)}   (cap 120 s, single-thread)")
    if missing_peers:
        print(f"!! PEERS NOT YET RUN: {', '.join(missing_peers)} -- partition is PROVISIONAL")
    for pk in present:
        print(f"  {pk:9s} {dict(coverage[pk])}")
    print(f"\nSet A (>=1 peer CLASSIFIED)  = {len(setA)}")
    print(f"Set B (no peer CLASSIFIED)   = {tally['B']}")
    print(
        f"Set C (peers disagree)       = {tally['C(disagree)']}   [orthogonal flag; "
        f"LOWER BOUND -- size-only, run normalise.py compare for the true set]"
    )
    ff = sum(1 for r in table if r["frontend_fail"])
    print(f"  of which >=1 peer FRONT-END failed (EMPTY/NO_OUTPUT): {ff}")

    if setA:
        walls = [
            (min(r[f"{p}_wall_s"] for p in r["solvers"] if r.get(f"{p}_wall_s")), r["ont"])
            for r in setA
            if any(r.get(f"{p}_wall_s") for p in r["solvers"])
        ]
        walls.sort()
        print(
            f"\nSet A: fastest peer wall -- median {walls[len(walls)//2][0]:.2f}s, "
            f"min {walls[0][0]:.2f}s ({walls[0][1]}), max {walls[-1][0]:.2f}s ({walls[-1][1]})"
        )
        print("  A peer doing in seconds what rustdl cannot do in 120 s is the gap, stated as a ratio.")
    if len(setA) < 20:
        print(
            f"\n!! STOPPING RULE: |Set A| = {len(setA)} < 20. The plan says say this plainly:\n"
            f"   that bounds this characterization's value and is a legitimate reason to stop\n"
            f"   after Phase 2 rather than fund engine work."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
