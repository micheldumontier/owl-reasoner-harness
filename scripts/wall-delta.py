#!/usr/bin/env python3
"""wall-delta.py A.jsonl B.jsonl — wall/RSS distribution over ontologies completing in BOTH arms.

`compare` reports only the >tol outliers, which cannot answer "did the corpus get
slower on average". This reports the full distribution: median and p90 of the
per-ontology delta, plus the worst regressions by ABSOLUTE seconds and by RATIO.

Both are needed. A 0.01 s -> 0.05 s row is +400% and irrelevant; a 40 s -> 52 s row
is +30% and is the one that turns into a DNF at a tighter cap. Ranking by ratio alone
fills the table with sub-second noise, which is how a "worst regression" list ends up
containing nothing that matters.

Also prints the ANSWER-IDENTITY count, refusing to report it when the two runs
disagree on digest mode (raw stdout digests are timing-nondeterministic).
"""

import json
import statistics
import sys


def load(path):
    header, cases = None, {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                print(f"  !! unparseable record in {path}", file=sys.stderr)
                continue
            if rec.get("kind") == "header":
                header = rec
            elif rec.get("kind") == "case":
                cases[rec["ont"]] = rec
    return header, cases


def pct(values, q):
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


def main():
    a_path, b_path = sys.argv[1], sys.argv[2]
    ha, ca = load(a_path)
    hb, cb = load(b_path)

    print(f"# wall-delta  A={a_path}  B={b_path}")
    print(f"  A cases {len(ca)}   B cases {len(cb)}")
    for name, hdr in (("A", ha), ("B", hb)):
        if hdr:
            print(
                f"  {name}: {hdr.get('version')} sha {hdr.get('sha256','')[:12]} "
                f"cap {hdr.get('cap_secs')}s threads {hdr.get('threads')} "
                f"strip={hdr.get('digest_strip_comments')}"
            )

    # Outcome transitions.
    trans = {}
    for ont in sorted(set(ca) | set(cb)):
        oa = ca.get(ont, {}).get("outcome", "MISSING")
        ob = cb.get(ont, {}).get("outcome", "MISSING")
        if oa != ob:
            trans.setdefault((oa, ob), []).append(ont)
    print("\n## outcome transitions")
    if not trans:
        print("  none")
    for (oa, ob), onts in sorted(trans.items(), key=lambda kv: -len(kv[1])):
        tag = ""
        if (oa, ob) in (("dnf", "ok"), ("err_crash", "ok")):
            tag = "  <-- RECOVERED"
        if oa == "ok" and ob != "ok":
            tag = "  <-- REGRESSION"
        print(f"  {oa:>10} -> {ob:<10} {len(onts):>5}{tag}")
        for ont in onts:
            wa = ca.get(ont, {}).get("wall_s")
            wb = cb.get(ont, {}).get("wall_s")
            print(f"      {ont:<20} A={wa}s  B={wb}s")

    # Both-completed set.
    both = [o for o in ca if o in cb and ca[o]["outcome"] == "ok" == cb[o]["outcome"]]
    print(f"\n## both completed: {len(both)}")

    # Answer identity, gated on digest mode agreement.
    sa = bool(ha and ha.get("digest_strip_comments"))
    sb = bool(hb and hb.get("digest_strip_comments"))
    diff = [o for o in both if ca[o].get("out_sha256") != cb[o].get("out_sha256")]
    print("\n## answer identity")
    if sa != sb:
        print(f"  REFUSED: digest modes differ (A strip={sa}, B strip={sb}) — not comparable")
    else:
        mode = "banner-stripped (strict)" if sa else "RAW stdout (timing noise: NOT evidence)"
        print(f"  digest mode: {mode}")
        print(f"  identical {len(both) - len(diff)}   DIFFERENT {len(diff)}")
        for ont in diff:
            print(f"      {ont}")

    # Wall distribution.
    rows = []
    for ont in both:
        wa, wb = ca[ont].get("wall_s"), cb[ont].get("wall_s")
        if wa is None or wb is None:
            continue
        rows.append((ont, wa, wb, wb - wa, (wb - wa) / wa if wa > 0 else 0.0))
    deltas = [r[3] for r in rows]
    ratios = [r[4] for r in rows]
    print(f"\n## wall distribution over {len(rows)} both-completing ontologies")
    print(f"  total A {sum(r[1] for r in rows):9.1f}s     total B {sum(r[2] for r in rows):9.1f}s")
    print(f"  median delta  {statistics.median(deltas):+.4f}s   median ratio {statistics.median(ratios)*100:+.2f}%")
    print(f"  p10 {pct(deltas,0.10):+.3f}s  p90 delta {pct(deltas, 0.90):+.3f}s")
    print(f"  p10 {pct(ratios,0.10)*100:+.1f}%  p90 ratio {pct(ratios, 0.90)*100:+.1f}%")
    print(f"  slower (B>A): {sum(1 for d in deltas if d > 0)}   faster: {sum(1 for d in deltas if d < 0)}   equal: {sum(1 for d in deltas if d == 0)}")

    print("\n### worst 10 regressions by ABSOLUTE seconds")
    for ont, wa, wb, d, r in sorted(rows, key=lambda x: -x[3])[:10]:
        print(f"  {d:+8.2f}s  ({r*100:+7.1f}%)  {ont:<20} {wa:7.2f}s -> {wb:7.2f}s")
    print("\n### worst 10 regressions by RATIO (>=0.5s in A, to exclude sub-second noise)")
    sig = [r for r in rows if r[1] >= 0.5]
    for ont, wa, wb, d, r in sorted(sig, key=lambda x: -x[4])[:10]:
        print(f"  {r*100:+7.1f}%  ({d:+.2f}s)  {ont:<20} {wa:7.2f}s -> {wb:7.2f}s")
    print("\n### biggest 10 speedups by ABSOLUTE seconds")
    for ont, wa, wb, d, r in sorted(rows, key=lambda x: x[3])[:10]:
        print(f"  {d:+8.2f}s  ({r*100:+7.1f}%)  {ont:<20} {wa:7.2f}s -> {wb:7.2f}s")

    # Peak RSS.
    rss = [
        (o, ca[o]["peak_rss_kb"], cb[o]["peak_rss_kb"])
        for o in both
        if ca[o].get("peak_rss_kb") and cb[o].get("peak_rss_kb")
    ]
    if rss:
        rd = [(b - a) / a for _, a, b in rss]
        print(f"\n## peak RSS over {len(rss)} rows: median {statistics.median(rd)*100:+.2f}%  p90 {pct(rd,0.90)*100:+.1f}%")
        grew = [(o, a, b) for o, a, b in rss if b > 2 * a and b - a > 500_000]
        print(f"  >2x AND >500MB growth: {len(grew)}")
        for o, a, b in grew:
            print(f"      {o:<20} {a/1e6:.2f}GB -> {b/1e6:.2f}GB")


if __name__ == "__main__":
    main()
