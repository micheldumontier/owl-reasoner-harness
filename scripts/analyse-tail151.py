#!/usr/bin/env python3
"""Deliverable numbers for the 2026-08-04 peer triage of rustdl's v0.4.14 151-ont tail.

Consumes the three per-peer triage JSONLs (verdicts already derived from output CONTENT
by scripts/triage.py) plus the 2026-08-01 baselines, and prints:

  1. the A / B / front-end partition (delegated in spirit to partition.py, which is the
     authority on the definitions; this adds the per-peer wall distributions and the
     apples-to-apples comparison against 2026-08-01 that partition.py does not do)
  2. per-peer wall distribution over Set A
  3. the 2026-08-01 vs 2026-08-04 comparison, on the identical carry-over population
  4. Set A ranked by fastest-peer wall ascending
  5. a run-to-run stability control: the 151 were ALL in the 257, so every ontology has
     a prior verdict from an independent peer run. Disagreement between the two runs
     bounds the reproducibility of a peer leg.
"""
import json, pathlib, statistics, sys
from collections import Counter

H = pathlib.Path("/data/dumontier/owl-reasoner-harness")
RUN = H / "runs/triage-2026-08-04"
PEERS = ["konclude", "hermit", "km"]


def load(p):
    p = pathlib.Path(p)
    if not p.exists():
        return {}
    return {
        r["ont"]: r
        for r in (json.loads(l) for l in p.read_text().splitlines() if l.strip())
    }


def q(xs, f):
    xs = sorted(xs)
    return xs[min(int(f * len(xs)), len(xs) - 1)] if xs else float("nan")


def main():
    onts = [l.strip() for l in (H / "baselines/2026-08-04-tail-v0414-list.txt")
            .read_text().splitlines() if l.strip()]
    now = {p: load(RUN / f"{p}-triage.jsonl") for p in PEERS}
    old = {p: load(H / f"baselines/2026-08-01-triage-{p}-c120.jsonl") for p in PEERS}
    ran = [p for p in PEERS if now[p]]
    if not ran:
        print("no legs complete yet"); return 1
    print(f"# population {len(onts)} (rustdl v0.4.14 DNF, 120 s cap, single-thread)")
    print(f"# legs complete: {', '.join(ran)}"
          + (f"   PROVISIONAL, not run: {', '.join(p for p in PEERS if p not in ran)}"
             if len(ran) < 3 else ""))

    print("\n## 1. Per-peer verdicts")
    for p in ran:
        c = Counter(now[p].get(o, {}).get("verdict", "NOT_RUN") for o in onts)
        print(f"  {p:9s} n={sum(c.values()):3d}  {dict(c)}")

    setA, setB, frontend = [], [], []
    for o in onts:
        solv = [p for p in ran if now[p].get(o, {}).get("verdict") == "CLASSIFIED"]
        ff = [p for p in ran if now[p].get(o, {}).get("verdict") in ("EMPTY", "NO_OUTPUT")]
        (setA if solv else setB).append(o)
        if ff:
            frontend.append((o, ff))
    print(f"\n## 2. Partition")
    print(f"  Set A (>=1 peer CLASSIFIED) = {len(setA)}  ({100*len(setA)/len(onts):.1f}%)")
    print(f"  Set B (no peer CLASSIFIED)  = {len(setB)}  ({100*len(setB)/len(onts):.1f}%)")
    print(f"  >=1 peer front-end failure (EMPTY/NO_OUTPUT), own category, not folded: "
          f"{len(frontend)}")
    for o, ff in frontend:
        print(f"      {o}: {','.join(ff)}")
    if setB:
        print(f"  Set B members: {' '.join(setB)}")

    print("\n## 3. Wall distribution on Set A, per peer (CLASSIFIED only)")
    print(f"  {'peer':9s} {'n':>4s} {'median':>8s} {'p90':>8s} {'max':>8s} {'<10s':>6s} {'<1s':>5s}")
    for p in ran:
        w = [now[p][o]["wall_s"] for o in setA
             if now[p].get(o, {}).get("verdict") == "CLASSIFIED"
             and now[p][o].get("wall_s") is not None]
        if not w:
            print(f"  {p:9s}    0"); continue
        print(f"  {p:9s} {len(w):4d} {statistics.median(w):8.2f} {q(w,.9):8.2f} "
              f"{max(w):8.2f} {sum(1 for x in w if x<10):6d} {sum(1 for x in w if x<1):5d}")
    fastest = {}
    for o in setA:
        cand = [(now[p][o]["wall_s"], p) for p in ran
                if now[p].get(o, {}).get("verdict") == "CLASSIFIED"
                and now[p][o].get("wall_s") is not None]
        if cand:
            fastest[o] = min(cand)
    fw = [v[0] for v in fastest.values()]
    print(f"  {'FASTEST':9s} {len(fw):4d} {statistics.median(fw):8.2f} {q(fw,.9):8.2f} "
          f"{max(fw):8.2f} {sum(1 for x in fw if x<10):6d} {sum(1 for x in fw if x<1):5d}")

    print("\n## 4. Comparison to 2026-08-01 (257 onts). The 151 is a STRICT SUBSET of the")
    print("##    257, so this is the identical population, re-measured.")
    o257 = [l.strip() for l in (H / "baselines/2026-08-01-dnf257-list.txt")
            .read_text().splitlines() if l.strip()]
    recovered = [o for o in o257 if o not in set(onts)]
    oldA = sum(1 for o in o257
               if any(old[p].get(o, {}).get("verdict") == "CLASSIFIED" for p in PEERS))
    print(f"  2026-08-01: |tail|=257  Set A={oldA} ({100*oldA/257:.1f}%)  Set B={257-oldA}")
    print(f"  2026-08-04: |tail|={len(onts)}  Set A={len(setA)} "
          f"({100*len(setA)/len(onts):.1f}%)  Set B={len(setB)}")
    recA = sum(1 for o in recovered
               if any(old[p].get(o, {}).get("verdict") == "CLASSIFIED" for p in PEERS))
    print(f"  rustdl recovered {len(recovered)}; of those {recA} were Set A on 08-01 "
          f"({100*recA/len(recovered):.1f}%) and {len(recovered)-recA} were Set B")
    for p in ran:
        kn = [old[p][o]["wall_s"] for o in recovered
              if old[p].get(o, {}).get("verdict") == "CLASSIFIED" and old[p][o].get("wall_s")]
        ks = [old[p][o]["wall_s"] for o in onts
              if old[p].get(o, {}).get("verdict") == "CLASSIFIED" and old[p][o].get("wall_s")]
        if kn and ks:
            print(f"    {p:9s} 08-01 wall: recovered median {statistics.median(kn):6.2f}s "
                  f"(n={len(kn)})  vs surviving median {statistics.median(ks):6.2f}s (n={len(ks)})")

    print("\n## 5. Run-to-run stability control (same ontologies, two independent peer runs)")
    for p in ran:
        chg = Counter()
        for o in onts:
            a = old[p].get(o, {}).get("verdict"); b = now[p].get(o, {}).get("verdict")
            if a and b and a != b:
                chg[f"{a}->{b}"] += 1
        same = sum(1 for o in onts if old[p].get(o, {}).get("verdict")
                   == now[p].get(o, {}).get("verdict"))
        print(f"  {p:9s} identical verdict on {same}/{len(onts)}"
              + (f"   changes: {dict(chg)}" if chg else ""))

    print("\n## 6. Set A ranked by fastest peer wall ascending (all members)")
    print(f"  {'#':>3s} {'ontology':16s} {'peer':9s} {'wall_s':>8s} {'ratio_vs_120s':>13s} "
          f"{'pairs':>10s}  solvers")
    for i, (o, (w, p)) in enumerate(sorted(fastest.items(), key=lambda kv: kv[1][0]), 1):
        solv = [x for x in ran if now[x].get(o, {}).get("verdict") == "CLASSIFIED"]
        pr = now[p][o].get("pairs")
        print(f"  {i:3d} {o:16s} {p:9s} {w:8.2f} {120/w:13.0f} "
              f"{(pr if pr is not None else -1):10d}  {','.join(solv)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
