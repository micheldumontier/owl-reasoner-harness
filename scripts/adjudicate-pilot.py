#!/usr/bin/env python3
"""Adjudicate a multi-reasoner pilot: outcomes + correctness against a gold signature.

Correctness is scored against AGREEMENT among the DL reference reasoners, not against
any single one. Where they disagree the ontology is EXCLUDED rather than resolved by
majority -- a contested oracle is not an oracle.

Metrics are computed over CORRECT COMPLETIONS and over the COMMON-SOLVED subset,
never over "exited zero": a reasoner can exit 0 with a wrong or partial answer, which
is the whole reason this script exists separately from the runner.
"""
import json, os, subprocess, sys, collections

S = os.path.dirname(os.path.abspath(__file__))
POOL = os.path.expanduser("~/data/ore-run/pool_sample/files")
NORM = os.path.expanduser("~/code/owl-reasoner-harness/scripts/normalise.py")
FMT = {"rustdl": "rustdl", "km": "km", "konclude": "konclude",
       "hermit": "hermit", "elk": "hermit", "jfact": "hermit"}
EXT = {"rustdl": ".out", "km": ".json", "konclude": ".owx",
       "hermit": ".ofn", "elk": ".ofn", "jfact": ".ofn"}
REFERENCE = ["konclude", "hermit", "jfact"]          # independent DL reasoners
ALL = ["rustdl", "km", "konclude", "hermit", "jfact", "elk"]


import re

_UNIV_CACHE = {}

def universal_classes(ont):
    """Classes X with an asserted `⊤ ⊑ X` (or `⊤ ≡ X`).

    Every class is trivially a subclass of these, so the rows carry no information
    -- the exact mirror of excluding unsatisfiable classes, which subsume everything
    from the other end. They MUST be excluded symmetrically because reasoners differ
    on whether to emit them: on ore_ont_7455 HermiT propagates ⊤ ⊑ X to every class
    and Konclude does not, producing a 59,694-pair "disagreement" that is exactly
    2 extra superclasses x 29,847 subjects -- the two classes this ontology asserts
    ⊤ ⊑ X for. Read raw, that scores the two canonical oracles as contested and
    silently drops the ontology from the gold set.

    This project has been bitten by the same convention before: 73% of an apparent
    ~1,795-row gap against another reasoner was ⊤ rows alone.
    """
    if ont in _UNIV_CACHE:
        return _UNIV_CACHE[ont]
    txt = open(f"{POOL}/{ont}.owl", encoding="utf-8", errors="replace").read()
    pfx = dict(re.findall(r"Prefix\(\s*([A-Za-z0-9_.-]*):=<([^>]*)>\s*\)", txt))

    def expand(tok):
        tok = tok.strip()
        if tok.startswith("<") and tok.endswith(">"):
            return tok[1:-1]
        if ":" in tok:
            p, local = tok.split(":", 1)
            return pfx[p] + local if p in pfx else None
        return None

    THING = "http://www.w3.org/2002/07/owl#Thing"
    out = set()
    for m in re.finditer(r"SubClassOf\(\s*(\S+)\s+(\S+?)\s*\)", txt):
        a, b = expand(m.group(1)), expand(m.group(2))
        if a == THING and b:
            out.add(b)
    _UNIV_CACHE[ont] = out
    return out


def outcomes():
    out = {}
    for r in ALL:
        p = f"{S}/{r}.jsonl"
        if not os.path.exists(p):
            continue
        out[r] = {}
        for line in open(p):
            # A killed run can leave a truncated final record; skip unparseable
            # lines rather than abort, but the count is checked by the caller.
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("kind") == "case":
                out[r][d["ont"]] = (d["outcome"], d.get("wall_s"))
    return out

def closure(r, ont):
    """Normalised transitive closure for one (reasoner, ontology), or None."""
    f = f"{S}/out/{r}/{ont}{EXT[r]}"
    if not os.path.exists(f) or os.path.getsize(f) == 0:
        return None
    cmd = [sys.executable, NORM, "normalise", "--format", FMT[r], f,
           "--ontology", f"{POOL}/{ont}.owl"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None
    if res.returncode != 0:
        return None
    edges = set()
    for line in res.stdout.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            edges.add((parts[0], parts[1]))
    # expand transitively: per-node BFS, NOT memoised recursion -- equivalence
    # groups are cycles and a memoised walk gives wrong answers on them.
    up = collections.defaultdict(set)
    for a, b in edges:
        up[a].add(b)
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
    univ = universal_classes(ont)
    if univ:
        full = {(a, b) for a, b in full if b not in univ}
    return full

def main():
    oc = outcomes()
    onts = sorted({o for r in oc for o in oc[r]})
    print(f"# {len(onts)} ontologies x {len(oc)} reasoners\n")

    print("## outcomes")
    hdr = f"{'reasoner':<10}" + "".join(f"{k:>9}" for k in ("answered","timeout","declined","failed"))
    print(hdr)
    for r in ALL:
        if r not in oc: continue
        c = collections.Counter(v[0] for v in oc[r].values())
        # the harness cannot see `declined` yet: it is exit code 3, which lands in
        # err_reject. Split it out here from the wrapper's own exit convention.
        print(f"{r:<10}{c['ok']:>9}{c['dnf']:>9}{'-':>9}{c['err_reject']:>9}")

    print("\n## gold signature (agreement of %s)" % ", ".join(REFERENCE))
    gold, contested, nogold = {}, [], []
    for o in onts:
        cl = {r: closure(r, o) for r in REFERENCE}
        have = {r: c for r, c in cl.items() if c is not None}
        if len(have) < 2:
            nogold.append(o); continue
        vals = list(have.values())
        if all(v == vals[0] for v in vals):
            gold[o] = vals[0]
        else:
            contested.append((o, {r: len(c) for r, c in have.items()}))
    print(f"  gold established : {len(gold)}")
    print(f"  contested (EXCLUDED, not majority-resolved): {len(contested)}")
    for o, sizes in contested:
        print(f"      {o}: {sizes}")
    print(f"  no reference answer: {len(nogold)}")

    print("\n## correctness over the gold set")
    print(f"{'reasoner':<10}{'MATCH':>7}{'DIFF':>6}{'partial':>9}{'none':>6}{'FP':>8}{'MISSED':>9}")
    for r in ALL:
        if r not in oc: continue
        m = d = part = none = 0; fp = mi = 0
        for o, g in gold.items():
            c = closure(r, o)
            if c is None:
                none += 1; continue
            extra, missing = c - g, g - c
            fp += len(extra); mi += len(missing)
            if not extra and not missing: m += 1
            elif not extra:                part += 1     # sound lower bound
            else:                          d += 1
        print(f"{r:<10}{m:>7}{d:>6}{part:>9}{none:>6}{fp:>8}{mi:>9}")
    print("\n  partial = sound subset of gold (FP=0, MISSED>0): a LOWER BOUND, not a"
          "\n  wrong answer. DIFF = emitted at least one pair the gold set does not.")

main()
