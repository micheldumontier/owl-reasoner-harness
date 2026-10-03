#!/usr/bin/env python3
"""Settle disputed subsumption pairs with a COMPLETE reasoner, one pair at a time.

WHY THIS EXISTS. adjudicate-sweep.py scores each arm against a gold set built from
reference-reasoner AGREEMENT. That gold set is demonstrably incomplete: on one corpus
ontology Konclude, HermiT and a third engine all omitted the same entailed pairs, so a
fourth arm that derived them was scored with 1,440 "false positives" for being MORE
complete. Neither agreement nor majority can settle that, because the omission is
correlated across engines. Only a per-pair entailment check can.

WHY NOT A SUBSUMPTION QUERY. Every engine here is sound but not guaranteed complete,
so a "no" means NOT PROVEN, never "not entailed"; and an incomplete satisfiability
check answering "satisfiable" may simply have missed the contradiction. Neither
direction from an incomplete engine decides anything.

THE METHOD. HermiT is complete for SROIQ. For a pair sub <= sup, append

    ClassAssertion(ObjectIntersectionOf(sub ObjectComplementOf(sup)) <fresh>)

and classify. If the probe is INCONSISTENT the pair is ENTAILED; if it is CONSISTENT
the pair is NOT ENTAILED.

THE CRITERION, and the bug it replaces. The OWLAPI driver reports inconsistency as an
owl:Nothing group holding every class -- but a CONSISTENT ontology with unsatisfiable
classes ALSO emits an owl:Nothing group (47 of 27,899 classes on one input). Grepping
for owl:Nothing therefore reads "has unsat classes" as "inconsistent" and returns
ENTAILED for everything, including its own negative control. So the probe's group size
is compared with the SAME ontology classified without the probe:
    unchanged                      -> consistent   -> NOT ENTAILED
    swollen to ~every class        -> inconsistent -> ENTAILED
    anything else, or a failed run -> INCONCLUSIVE

CONTROLS, ON EVERY ONTOLOGY. An instrument validated on one ontology need not
discriminate on another, so each ontology gets its own:
    positive: a pair the reference derives          -> must come back ENTAILED
    negative: the reverse of a reference pair that
              neither the reference nor the arm has -> at least one must come back
                                                       NOT ENTAILED
A broken instrument returns the same verdict for both, so requiring both outcomes is
what proves it discriminates. A negative control coming back ENTAILED is not itself a
failure -- the reference is known to under-report -- so up to three are tried.
If the controls do not pass, the ontology's verdicts are reported INSTRUMENT_INVALID.

    SWEEP_DIR=... CORPUS=... python3 scripts/settle-pairs.py ARM ONT [ONT ...] \\
        [--ref konclude] [--n 5] [--seed 11] [--direction extra|missed] [--out f.jsonl]

--direction extra   pairs ARM derives and REF does not  (is ARM unsound, or REF short?)
--direction missed  pairs REF derives and ARM does not  (is REF unsound, or ARM short?)

Env: SETTLE_TIMEOUT (s per HermiT run, default 900), HARNESS_MEM_MB (default 10240),
RAYON_NUM_THREADS (default 1). Corpus inputs must be OWL functional syntax.

COST: one full HermiT classification per probe, plus one for the base and up to four
for the controls -- minutes per ontology on large inputs. Sample, do not sweep.
"""
import argparse, json, os, random, shutil, subprocess, sys, tempfile, time, re, importlib.util

_here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("adj", os.path.join(_here, "adjudicate-sweep.py"))
adj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adj)

WRAPPER = os.path.join(_here, "..", "wrappers", "run-hermit-owlapi.sh")
TIMEOUT = int(os.environ.get("SETTLE_TIMEOUT", "900"))
NOTHING = re.compile(rb"^EquivalentClasses\( <http://www\.w3\.org/2002/07/owl#Nothing>([^)]*)", re.M)
DECL = re.compile(rb"Declaration\(\s*Class\(")


def corpus_file(ont):
    for ext in (".owl", ".ofn", ""):
        p = os.path.join(adj.POOL, ont + ext)
        if os.path.isfile(p):
            return p
    return None


def count_classes(path):
    n = 0
    with open(path, "rb") as fh:
        for line in fh:
            n += len(DECL.findall(line))
    return n


def write_probe(src, dst, sub, sup):
    """Copy src to dst with the probe axiom inserted before the closing ')' of the
    Ontology(...) block. Streamed, because corpus inputs reach ~500 MB."""
    size = os.path.getsize(src)
    with open(src, "rb") as fh:
        fh.seek(max(0, size - 65536))
        tail = fh.read()
    cut = tail.rstrip().rfind(b")")
    if cut < 0:
        raise ValueError("no closing ')' -- not functional syntax?")
    cut += max(0, size - 65536)
    probe = ("\nDeclaration(NamedIndividual(<urn:settle-pairs#probe>))\n"
             "ClassAssertion(ObjectIntersectionOf(<%s> ObjectComplementOf(<%s>)) "
             "<urn:settle-pairs#probe>)\n" % (sub, sup)).encode()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        remaining = cut
        while remaining:
            chunk = fi.read(min(1 << 20, remaining))
            if not chunk:
                break
            fo.write(chunk)
            remaining -= len(chunk)
        fo.write(probe)
        shutil.copyfileobj(fi, fo)


def nothing_size(src):
    """Classify with HermiT via the shared wrapper; return (size of the owl:Nothing
    group, rc, seconds). size is None when the run produced no usable output."""
    work = tempfile.mkdtemp(prefix="settle-")
    try:
        env = dict(os.environ, HARNESS_OUT_DIR=work)
        env.setdefault("HARNESS_MEM_MB", "10240")
        env.setdefault("RAYON_NUM_THREADS", "1")
        t0 = time.time()
        try:
            rc = subprocess.run(["bash", WRAPPER, src], env=env, capture_output=True,
                                timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            return None, "timeout", time.time() - t0
        dt = time.time() - t0
        out = os.path.join(work, os.path.splitext(os.path.basename(src))[0] + ".ofn")
        if rc != 0 or not os.path.exists(out):
            return None, rc, dt
        with open(out, "rb") as fh:
            m = NOTHING.search(fh.read())
        return (len(re.findall(rb"<http", m.group(1))) if m else 0), rc, dt
    finally:
        shutil.rmtree(work, ignore_errors=True)


def verdict(n, base, nclass):
    if n is None:
        return "INCONCLUSIVE"
    if n == base:
        return "NOT_ENTAILED"
    if n >= 0.99 * nclass:
        return "ENTAILED"
    return "INCONCLUSIVE"


def probe(src, sub, sup, base, nclass, workdir):
    p = os.path.join(workdir, "probe.ofn")
    write_probe(src, p, sub, sup)
    n, rc, dt = nothing_size(p)
    os.remove(p)
    return {"sub": sub, "sup": sup, "nothing": n, "rc": rc, "secs": round(dt, 1),
            "verdict": verdict(n, base, nclass)}


def settle(arm, ont, ref, n_pairs, rng, direction, emit):
    src = corpus_file(ont)
    if not src:
        return emit({"ont": ont, "status": "NO_INPUT"})
    with open(src, "rb") as fh:
        head = fh.read(4096).lstrip()
    if not (head.startswith(b"Prefix(") or head.startswith(b"Ontology(")):
        return emit({"ont": ont, "status": "NOT_FUNCTIONAL_SYNTAX"})

    ids = {}
    g = adj.closure(ref, ont, True, ids)
    c = adj.closure(arm, ont, True, ids)
    if g in (None, "OVERSIZED") or c in (None, "OVERSIZED"):
        return emit({"ont": ont, "status": "NO_CLOSURE", "ref": str(g)[:20], "arm": str(c)[:20]})
    inv = {v: k for k, v in ids.items()}
    disputed = sorted((a, b) for a, b in ((c - g) if direction == "extra" else (g - c)) if a != b)
    if not disputed:
        return emit({"ont": ont, "status": "NO_DISPUTE"})

    nclass = count_classes(src)
    base, rc, dt = nothing_size(src)
    if base is None:
        return emit({"ont": ont, "status": "BASE_FAILED", "rc": rc, "secs": round(dt, 1)})
    if base >= 0.99 * nclass:
        # Every probe of an inconsistent ontology is inconsistent: nothing to decide.
        return emit({"ont": ont, "status": "BASE_INCONSISTENT"})

    work = tempfile.mkdtemp(prefix="settle-probe-")
    try:
        gold = sorted(p for p in g if p[0] != p[1])
        a, b = rng.choice(gold)
        pos = probe(src, inv[a], inv[b], base, nclass, work)
        negs = []
        cands = [(b2, a2) for a2, b2 in gold if (b2, a2) not in g and (b2, a2) not in c]
        rng.shuffle(cands)
        for b2, a2 in cands[:3]:
            negs.append(probe(src, inv[b2], inv[a2], base, nclass, work))
            if negs[-1]["verdict"] == "NOT_ENTAILED":
                break
        valid = pos["verdict"] == "ENTAILED" and any(x["verdict"] == "NOT_ENTAILED" for x in negs)

        rows = []
        if valid:
            for a, b in rng.sample(disputed, min(n_pairs, len(disputed))):
                rows.append(probe(src, inv[a], inv[b], base, nclass, work))
        tally = {}
        for r in rows:
            tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
        emit({"ont": ont, "arm": arm, "ref": ref, "direction": direction,
              "status": "OK" if valid else "INSTRUMENT_INVALID",
              "classes": nclass, "base_nothing": base, "disputed": len(disputed),
              "control_positive": pos, "control_negative": negs,
              "pairs": rows, "tally": tally})
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("arm")
    ap.add_argument("onts", nargs="+")
    ap.add_argument("--ref", default="konclude")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--direction", choices=("extra", "missed"), default="extra")
    ap.add_argument("--out")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    sink = open(a.out, "a") if a.out else None

    def emit(row):
        line = json.dumps(row)
        if sink:
            sink.write(line + "\n"); sink.flush()
        t = row.get("tally")
        print("%-16s %-20s %s" % (row["ont"], row["status"],
              ("disputed=%d sampled=%d %s" % (row["disputed"], len(row["pairs"]), t)) if t is not None else ""),
              flush=True)

    for ont in a.onts:
        settle(a.arm, ont, a.ref, a.n, rng, a.direction, emit)


if __name__ == "__main__":
    main()
