#!/usr/bin/env python3
"""Adjudicate a sweep: correctness against a gold signature built from agreement.

GOLD = ontologies where the independent reference reasoners BOTH answered and produced
the SAME normalised closure. Where they disagree the ontology is EXCLUDED, never
resolved by majority -- a contested oracle is not an oracle.

    SWEEP_DIR=... CORPUS=... [ARMS=a,b,c] [REFS=x,y] [W=3] [CLOSURE_CAP=20000000] \
        python3 scripts/adjudicate-sweep.py

Reports, per arm: MATCH (closure equals gold), part (a sound SUBSET of gold -- a lower
bound, not a wrong answer), DIFF (emitted a pair gold does not contain), n/a (never
answered), and total FP / MISSED pairs.
"""
import json, glob, os, sys, collections, re, importlib.util
from concurrent.futures import ProcessPoolExecutor

_here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "norm", os.path.join(_here, "normalise.py"))
norm = importlib.util.module_from_spec(spec); spec.loader.exec_module(norm)

SW = os.environ.get("SWEEP_DIR") or sys.exit(
    "set SWEEP_DIR to the sweep output directory (holding <arm>-chunk-*.jsonl and out/)")
POOL = os.environ.get("CORPUS") or sys.exit("set CORPUS to the ontology directory")
FMT = {"rustdl": "rustdl", "km130": "km", "km140": "km", "konclude": "konclude",
       "hermit": "hermit", "elk": "hermit", "jfact": "hermit"}
EXT = {"rustdl": ".out", "km130": ".json", "km140": ".json", "konclude": ".owx",
       "hermit": ".ofn", "elk": ".ofn", "jfact": ".ofn"}
REF = os.environ.get("REFS", "konclude,hermit").split(",")
ARMS = os.environ.get("ARMS", "rustdl,km130,km140,konclude,hermit,elk").split(",")
CAP = int(os.environ.get("CLOSURE_CAP", "20000000"))


def outcomes(a):
    o = {}
    for f in glob.glob("%s/%s-chunk-*.jsonl" % (SW, a)):
        for line in open(f):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("kind") == "case":
                o[d["ont"]] = d["outcome"]
    return o


OC = {a: outcomes(a) for a in set(ARMS) | set(REF)}
_univ = {}


def universal(ont):
    """Classes X with an asserted TOP <= X: trivially true of every class, so excluded
    on all sides, exactly as unsatisfiable classes are."""
    if ont in _univ:
        return _univ[ont]
    txt = open("%s/%s.owl" % (POOL, ont), encoding="utf-8", errors="replace").read()
    pfx = dict(re.findall(r"Prefix\(\s*([A-Za-z0-9_.-]*):=<([^>]*)>\s*\)", txt))
    T = "http://www.w3.org/2002/07/owl#Thing"
    out = set()

    def ex(t):
        t = t.strip()
        if t.startswith("<") and t.endswith(">"):
            return t[1:-1]
        if ":" in t:
            p, l = t.split(":", 1)
            return pfx[p] + l if p in pfx else None
        return None

    for m in re.finditer(r"SubClassOf\(\s*(\S+)\s+(\S+?)\s*\)", txt):
        if ex(m.group(1)) == T and ex(m.group(2)):
            out.add(ex(m.group(2)))
    _univ[ont] = out
    return out


def closure(arm, ont, answered, ids):
    """Transitive closure as (int,int) pairs.

    `ids` is a SHARED interning map, created once per ontology and passed to every
    arm. It must be shared: with a per-arm map the same IRI gets different integers in
    different arms, so comparing one arm's pairs against another compares arbitrary
    numbers -- which showed up as the reference reasoners "disagreeing" on 65% of
    ontologies instead of none.

    IRIs are interned because a dense hierarchy yields tens of millions of pairs,
    and holding those as string tuples exhausted memory -- one worker reached 6.8 GB
    and climbing on a single ontology while the others sat idle, because
    ProcessPoolExecutor.map cannot return until the straggler does.

    Past CAP pairs the ontology is abandoned as OVERSIZED rather than adjudicated. An
    honest exclusion beats an unbounded run.
    """
    p = "%s/out/%s/%s%s" % (SW, arm, ont, EXT[arm])
    for cand in (p, p + ".gz"):
        if not os.path.exists(cand):
            continue
        if os.path.getsize(cand) == 0:
            return set() if answered else None
        try:
            n = norm.normalise_file(FMT[arm], cand, "%s/%s.owl" % (POOL, ont))
        except Exception:
            return None
        def i(x):
            v = ids.get(x)
            if v is None:
                v = ids[x] = len(ids)
            return v

        up = collections.defaultdict(set)
        for a_, b_ in n.pairs():
            up[i(a_)].add(i(b_))
        u = {ids[x] for x in universal(ont) if x in ids}
        full = set()
        for x in list(up):
            seen, st = set(), list(up[x])
            while st:
                y = st.pop()
                if y in seen:
                    continue
                seen.add(y)
                st.extend(up.get(y, ()))
            for y in seen:
                if y not in u:
                    full.add((x, y))
            if len(full) > CAP:
                return "OVERSIZED"
        return full
    return set() if answered else None


def job(ont):
    ids = {}          # ONE map per ontology, shared by every arm
    cl = {r: closure(r, ont, OC[r].get(ont) == "ok", ids) for r in REF}
    if any(c == "OVERSIZED" for c in cl.values()):
        return (ont, "oversized", None)
    have = {r: c for r, c in cl.items() if c is not None}
    if len(have) < 2:
        return (ont, "noref", None)
    v = list(have.values())
    if v[0] != v[1]:
        return (ont, "contested", None)
    g = v[0]
    res = {}
    for a in ARMS:
        c = closure(a, ont, OC[a].get(ont) == "ok", ids)
        if c is None or c == "OVERSIZED":
            res[a] = ("na", 0, 0)
        else:
            e, m = len(c - g), len(g - c)
            res[a] = ("match" if not e and not m else ("part" if not e else "diff"), e, m)
    return (ont, "gold", res)


if __name__ == "__main__":
    onts = sorted(OC["konclude"])
    agg = {a: collections.Counter() for a in ARMS}
    fp = {a: 0 for a in ARMS}
    miss = {a: 0 for a in ARMS}
    gold = cont = noref = over = done = 0
    with ProcessPoolExecutor(max_workers=int(os.environ.get("W", "3"))) as ex:
        for ont, kind, res in ex.map(job, onts, chunksize=4):
            done += 1
            if kind == "gold":
                gold += 1
                for a, (k, e, m) in res.items():
                    agg[a][k] += 1; fp[a] += e; miss[a] += m
            elif kind == "contested":
                cont += 1
            elif kind == "oversized":
                over += 1
            else:
                noref += 1
            if done % 25 == 0:
                print("  ...%d/%d  gold=%d contested=%d oversized=%d"
                      % (done, len(onts), gold, cont, over), flush=True)
    print("\ngold=%d contested=%d no-reference=%d oversized=%d  (of %d)"
          % (gold, cont, noref, over, len(onts)))
    print("%-9s %7s %6s %6s %6s %12s %12s"
          % ("arm", "MATCH", "part", "DIFF", "n/a", "FP", "MISSED"))
    for a in ARMS:
        c = agg[a]
        print("%-9s %7d %6d %6d %6d %12d %12d"
              % (a, c["match"], c["part"], c["diff"], c["na"], fp[a], miss[a]))
