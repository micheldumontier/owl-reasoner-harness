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
from concurrent.futures import ProcessPoolExecutor, as_completed

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
# 20M pairs was far too generous: the p99 closure is orders of magnitude smaller, so
# the cap almost never bit and a single dense ontology could occupy a worker for hours.
CAP = int(os.environ.get("CLOSURE_CAP", "3000000"))
CKPT = os.environ.get("CHECKPOINT")   # append per-ontology results as they land


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
    on all sides, exactly as unsatisfiable classes are.

    STREAMED LINE BY LINE, deliberately. Reading the ontology whole cost a worker as
    much memory as the file -- and the corpus holds 526 MB, 450 MB and 333 MB inputs,
    so a handful of workers on large files exhausted the box and the OOM killer took
    one, which broke the whole process pool and stalled the run three times. The
    axioms matched here never span lines in this corpus's functional syntax.
    """
    if ont in _univ:
        return _univ[ont]
    T = "http://www.w3.org/2002/07/owl#Thing"
    pfx = {}
    out = set()
    pre_re = re.compile(r"Prefix\(\s*([A-Za-z0-9_.-]*):=<([^>]*)>\s*\)")
    sub_re = re.compile(r"SubClassOf\(\s*(\S+)\s+(\S+?)\s*\)")

    def ex(t):
        t = t.strip()
        if t.startswith("<") and t.endswith(">"):
            return t[1:-1]
        if ":" in t:
            p, l = t.split(":", 1)
            return pfx[p] + l if p in pfx else None
        return None

    with open("%s/%s.owl" % (POOL, ont), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "Prefix(" in line:
                for m in pre_re.finditer(line):
                    pfx[m.group(1)] = m.group(2)
            if "SubClassOf(" in line:
                for m in sub_re.finditer(line):
                    if ex(m.group(1)) == T:
                        b = ex(m.group(2))
                        if b:
                            out.add(b)
    _univ[ont] = out
    return out


def i_of(x, ids):
    v = ids.get(x)
    if v is None:
        v = ids[x] = len(ids)
    return v


def _expand(up, ont, ids):
    """Transitive closure of a direct-pair graph, minus TOP-implied rows."""
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
            # CHECK INSIDE THE WALK, not only after it. Checking per-node let a single
            # node with a huge reachable set grow `seen` unbounded before the cap was
            # ever consulted -- which OOM-killed a worker and took the whole pool with
            # it (BrokenProcessPool), twice, losing every unwritten result.
            if len(full) + len(seen) > CAP:
                return "OVERSIZED"
        for y in seen:
            if y not in u:
                full.add((x, y))
        if len(full) > CAP:
            return "OVERSIZED"
    return full


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
    # Prefer the cached normalisation (scripts/normalise-arm.py) over re-parsing the
    # raw output: taxonomies run to 100+ MB, and re-scoring under changed rules used
    # to pay the full parse again every time. Falls back to raw when no cache exists,
    # so an older sweep still scores.
    cache = "%s/norm/%s/%s.tsv.gz" % (SW, arm, ont)
    if os.path.exists(cache):
        import gzip as _gz
        up = collections.defaultdict(set)
        with _gz.open(cache, "rt", encoding="utf-8") as fh:
            for line in fh:
                t = line.rstrip("\n").split("\t")
                if len(t) == 2:
                    up[i_of(t[0], ids)].add(i_of(t[1], ids))
        return _expand(up, ont, ids)

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
    onts = sorted(OC[REF[0]])
    done_already = {}
    if CKPT and os.path.exists(CKPT):
        # RESUME. Results used to live only in the driver's memory, so a crash or a
        # kill discarded every hour of work; each ontology is now appended as it lands.
        for line in open(CKPT):
            try:
                r = json.loads(line)
            except Exception:
                continue
            done_already[r["ont"]] = r
        print("resuming: %d ontologies already scored" % len(done_already), flush=True)
    todo = [o for o in onts if o not in done_already]

    agg = {a: collections.Counter() for a in ARMS}
    fp = {a: 0 for a in ARMS}
    miss = {a: 0 for a in ARMS}
    gold = cont = noref = over = 0

    def tally(rec):
        global gold, cont, noref, over
        k = rec["kind"]
        if k == "gold":
            gold += 1
            for a, v in rec["res"].items():
                agg[a][v[0]] += 1; fp[a] += v[1]; miss[a] += v[2]
        elif k == "contested": cont += 1
        elif k == "oversized": over += 1
        else: noref += 1

    for rec in done_already.values():
        tally(rec)

    ck = open(CKPT, "a") if CKPT else None
    done = len(done_already)
    with ProcessPoolExecutor(max_workers=int(os.environ.get("W", "10"))) as ex:
        # as_completed, NOT map: map yields in submission order, so one expensive
        # ontology blocks every result behind it and the other workers idle. That is
        # what took a run to 125 of 1920 in 3.5 hours at load 1.0 on a 16-CPU box.
        futs = {ex.submit(job, o): o for o in todo}
        for f in as_completed(futs):
            ont, kind, res = f.result()
            rec = {"ont": ont, "kind": kind, "res": res}
            tally(rec)
            if ck:
                ck.write(json.dumps(rec) + "\n"); ck.flush()
            done += 1
            if done % 25 == 0:
                print("  ...%d/%d  gold=%d contested=%d oversized=%d"
                      % (done, len(onts), gold, cont, over), flush=True)
    if ck:
        ck.close()

    print("\ngold=%d contested=%d no-reference=%d oversized=%d  (of %d)"
          % (gold, cont, noref, over, len(onts)))
    print("%-9s %7s %6s %6s %6s %12s %12s"
          % ("arm", "MATCH", "part", "DIFF", "n/a", "FP", "MISSED"))
    for a in ARMS:
        c = agg[a]
        print("%-9s %7d %6d %6d %6d %12d %12d"
              % (a, c["match"], c["part"], c["diff"], c["na"], fp[a], miss[a]))
