#!/usr/bin/env python3
"""Consolidate the interleaved 3-repeat pilot: outcomes, correctness, wall, RSS.

Per (reasoner, ontology) the wall/RSS reported is the MEDIAN of 3 repeats run with
ROTATED arm order after a page-cache warm-up. Single-run figures were not defensible:
run-to-run spread on identical binaries is 2.8-8.9%, the same magnitude as the
fixed-arm-order artefact the harness's own notes record.
"""
import json, os, statistics, collections, subprocess, sys

S = "/private/tmp/claude-501/-Users-micheldumontier-code-rustdl/6d1b06f5-6720-4000-b459-8a2e5ba55b2c/scratchpad/pilot2"
POOL = os.path.expanduser("~/data/ore-run/pool_sample/files")
NORM = os.path.expanduser("~/code/owl-reasoner-harness/scripts/normalise.py")
ARMS = ["rustdl", "rustdlx", "km", "konclude", "hermit", "jfact", "elk"]
REFERENCE = ["konclude", "hermit", "jfact"]
FMT = {"rustdl": "rustdl", "rustdlx": "rustdl", "km": "km", "konclude": "konclude",
       "hermit": "hermit", "elk": "hermit", "jfact": "hermit"}
EXT = {"rustdl": ".out", "rustdlx": ".out", "km": ".json", "konclude": ".owx",
       "hermit": ".ofn", "elk": ".ofn", "jfact": ".ofn"}
FLOOR = {"rustdl": 6, "rustdlx": 6, "km": 3, "konclude": 28,
         "hermit": 120, "jfact": 122, "elk": 159}

def load():
    """outcome per (arm, ont) from repeat 1; wall/RSS as the median of 3."""
    oc, wall, rss = {}, {}, {}
    for a in ARMS:
        oc[a], wall[a], rss[a] = {}, collections.defaultdict(list), collections.defaultdict(list)
        for rep in (1, 2, 3):
            p = f"{S}/{a}-r{rep}.jsonl"
            if not os.path.exists(p):
                continue
            for line in open(p):
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("kind") != "case":
                    continue
                o = d["ont"]
                # An outcome that is not stable across repeats is itself a finding:
                # record the WORST, so a cap-boundary ontology is never reported as a
                # clean completion on the strength of one lucky pass.
                rank = {"ok": 0, "declined": 1, "dnf": 2, "err_reject": 3, "err_crash": 4}
                prev = oc[a].get(o)
                if prev is None or rank.get(d["outcome"], 9) > rank.get(prev, 9):
                    oc[a][o] = d["outcome"]
                if d["outcome"] == "ok":
                    wall[a][o].append(d.get("wall_s") or 0.0)
                    if d.get("peak_rss_kb"):
                        rss[a][o].append(d["peak_rss_kb"] / 1024)
    return oc, wall, rss

def closure(a, ont, answered):
    f = f"{S}/out-r1/{a}/{ont}{EXT[a]}"
    if not os.path.exists(f):
        return None
    if os.path.getsize(f) == 0:
        return set() if answered else None      # empty is an ANSWER, absent is not
    r = subprocess.run([sys.executable, NORM, "normalise", "--format", FMT[a], f,
                        "--ontology", f"{POOL}/{ont}.owl"],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        return None
    up = collections.defaultdict(set)
    for line in r.stdout.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        p = line.split("\t")
        if len(p) == 2:
            up[p[0]].add(p[1])
    full = set()
    for n in list(up):
        seen, st = set(), list(up[n])
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x); st.extend(up.get(x, ()))
        for x in seen:
            full.add((n, x))
    import re
    txt = open(f"{POOL}/{ont}.owl", encoding="utf-8", errors="replace").read()
    pfx = dict(re.findall(r"Prefix\(\s*([A-Za-z0-9_.-]*):=<([^>]*)>\s*\)", txt))
    THING = "http://www.w3.org/2002/07/owl#Thing"
    univ = set()
    for m in re.finditer(r"SubClassOf\(\s*(\S+)\s+(\S+?)\s*\)", txt):
        def ex(t):
            t = t.strip()
            if t.startswith("<") and t.endswith(">"): return t[1:-1]
            if ":" in t:
                p_, l_ = t.split(":", 1)
                return pfx[p_] + l_ if p_ in pfx else None
            return None
        if ex(m.group(1)) == THING and ex(m.group(2)):
            univ.add(ex(m.group(2)))
    if univ:
        full = {(x, y) for x, y in full if y not in univ}
    return full

def main():
    oc, wall, rss = load()
    onts = sorted(oc["rustdl"])
    gold, contested, noref = {}, [], []
    for o in onts:
        cl = {r: closure(r, o, oc[r].get(o) == "ok") for r in REFERENCE}
        have = {r: c for r, c in cl.items() if c is not None}
        if len(have) < 2:
            noref.append(o); continue
        v = list(have.values())
        if all(x == v[0] for x in v): gold[o] = v[0]
        else: contested.append(o)
    common = [o for o in onts if all(oc[a].get(o) == "ok" for a in ARMS)]
    print(f"{len(onts)} ontologies = {len(gold)} gold + {len(contested)} contested + {len(noref)} no-ref")
    print(f"common-solved by all {len(ARMS)} arms: {len(common)}   (medians over 3 repeats, rotated order)\n")
    import glob
    def truncated(a):
        """Ontologies where the reasoner SAID its answer may be incomplete.

        Only readable because stderr is now captured; rustdl prints its
        "SOUND ... but may be missing real ones" warning there and nowhere else.
        A reasoner that reports nothing here is not thereby complete -- most have
        no such signal at all, which is itself worth seeing in the table."""
        n = 0
        for f in glob.glob(f"{S}/out-r1/{a}/*.stderr"):
            t = open(f, errors="replace").read()
            if "may be missing real ones" in t or "incomplete" in t:
                n += 1
        return n
    H = ("arm","ans","t/o","decl","fail","inc","MATCH","part","DIFF","n/a","FP","MISSED","medW","maxW","medR","netR","maxR")
    print("".join(f"{h:>8}" if i else f"{h:<9}" for i,h in enumerate(H)))
    print("-"*(9+8*(len(H)-1)))
    for a in ARMS:
        c = collections.Counter(oc[a].values())
        M=D=P=N=0; fp=mi=0
        for o,g in gold.items():
            cl = closure(a, o, oc[a].get(o)=="ok")
            if cl is None: N += 1; continue
            ex, ms = cl-g, g-cl
            fp += len(ex); mi += len(ms)
            if not ex and not ms: M += 1
            elif not ex: P += 1
            else: D += 1
        w = [statistics.median(wall[a][o]) for o in common if wall[a][o]]
        m = [statistics.median(rss[a][o]) for o in common if rss[a][o]]
        row = [a, c["ok"], c["dnf"], c["declined"], c["err_reject"]+c["err_crash"], truncated(a),
               M, P, D, N, fp, mi,
               f"{statistics.median(w):.3f}" if w else "-", f"{max(w):.2f}" if w else "-",
               f"{statistics.median(m):.0f}" if m else "-",
               f"{max(statistics.median(m)-FLOOR[a],0):.0f}" if m else "-",
               f"{max(m):.0f}" if m else "-"]
        print("".join(f"{v:>8}" if i else f"{str(v):<9}" for i,v in enumerate(row)))
    # repeat stability
    print("\nwall spread across the 3 repeats (max-min)/min, median over common-solved:")
    for a in ARMS:
        sp = [ (max(v)-min(v))/min(v)*100 for o in common if (v:=wall[a][o]) and len(v)==3 and min(v)>0 ]
        print(f"  {a:<9} {statistics.median(sp):5.1f}%" if sp else f"  {a:<9}   n/a")

main()
