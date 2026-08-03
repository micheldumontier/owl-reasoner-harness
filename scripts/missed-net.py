#!/usr/bin/env python3
"""The corpus-scale MISSED net: per-ontology completeness loss for a rustdl build.

    missed-net.py manifest --arm v0413 [-o ...]      banner + outcome per ontology
    missed-net.py select   --manifest M --n 400 --seed 20260803
    missed-net.py net      --arm v0413 --population L [--baseline B]

WHAT IT ANSWERS, AND WHAT NO OTHER GATE HERE DOES
-------------------------------------------------
`run-soundness-diff.sh` proves FP=0 on 11 curated fixtures. A harness sweep counts
`dnf -> ok` transitions. Neither answers "how many entailments did this change LOSE
across the corpus?", which is the question every completeness/performance trade turns
on: a lower depth cap that recovers 3 DNFs and costs 4 pairs on one ontology cannot be
judged without it.

DESIGN COMMITMENTS
------------------
1. CLOSURE DIFFING IS NOT REIMPLEMENTED. Every FP/MISSED number comes from
   `normalise.compare`, and every closure from `normalise`'s parsers. This module only
   builds the union oracle (`normalise.read_normalised` -> merged `Normalised` ->
   `.write`) and aggregates.

2. THE ORACLE IS THE UNION OF KONCLUDE AND HERMIT. Konclude is documented to
   UNDER-report (`ore_ont_9540`: Konclude 66 pairs, HermiT 71; and `ore_ont_10407`,
   where rustdl matched HermiT). A "MISSED" against Konclude alone can therefore be
   Konclude's error rather than rustdl's. Where the two peers DISAGREE the ontology is
   recorded `peer_disagreement` and EXCLUDED from the total: a contested oracle is not
   an oracle, and picking a side would launder a guess into a headline number.

3. PEER OUTCOME COMES FROM OUTPUT CONTENT. Konclude exits 0 on a nonexistent file, on
   junk and on a real ontology alike, writing an 896-byte Thing/Nothing-only hierarchy
   in the failure cases; an exit-code-derived "ok" once produced a 58-of-60 success
   reading that was nearly all parse failures. The predicate is `triage.py`'s
   `declared_real_class`, imported, not re-written — it is per-format because a
   format-agnostic version misread 110 of 192 HermiT runs.

4. A MISSED COUNT IS NOT AUTOMATICALLY A BUG. rustdl is a documented sound
   under-approximation in places (`trust_sat` concluding "not subsumed" from its own
   Sat verdict; per-pair budgets; fragment gates). The baseline's job is to make
   *changes* visible as a DELTA, not to indict the current state.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import pathlib
import random
import re
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import normalise  # noqa: E402  (the closure/compare engine — never duplicated below)
import triage  # noqa: E402  (the per-format content predicate)

SCRATCH = pathlib.Path(
    os.environ.get("MISSED_NET_SCRATCH", "/mnt/um-share-drive/dumontier/missed-net")
)
CORPUS = pathlib.Path(
    os.environ.get("MISSED_NET_CORPUS", "/data/dumontier/ore-run/pool_sample/files")
)

FRAGMENTS = ("pure-EL", "Horn", "out-of-EL")


# ── manifest ────────────────────────────────────────────────────────────────


def read_cases(*jsonls: pathlib.Path) -> dict[str, dict]:
    """Case records from one or more JSONLs. Later files win, so a freshly swept row
    overrides an adopted one rather than the reverse."""
    out: dict[str, dict] = {}
    for jsonl in jsonls:
        if not jsonl.exists():
            continue
        for line in jsonl.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("kind") == "case":
                out[rec["ont"]] = rec
    return out


BANNER = {
    "classes": re.compile(r"^# classes:\s*(\d+)"),
    "mode": re.compile(r"^# mode:\s*(\S+)"),
    "fragment": re.compile(r"^# fragment:\s*(\S+)"),
}
SUBS = re.compile(r"^# subsumption:\s*saturation=(\d+)\s+tableau=(\d+)")
PROBES = re.compile(r"^# satisfiability probes:\s*saturation=(\d+)\s+tableau=(\d+)")
LABELS = re.compile(r"^# label heuristic:\s*pruned=(\d+)\s+pass_through=(\d+)\s+misses=(\d+)")


def banner_of(path: pathlib.Path) -> dict:
    """Parse the rustdl banner. Reads only the leading comment block.

    `# fragment:` is the STRATIFICATION VARIABLE. The over-sampling variable is
    `search_exercised` (see `stratum`), which is derived from THREE banner counters
    rather than from `tableau=N` alone -- measured on 546 completers, `tableau>0`
    holds for **2** of them, because the Phase-7 label heuristic prunes 96-100% of
    subsumption oracle calls and `trust_sat` lets the wedge answer the rest. Selecting
    on `tableau>0` would have produced a 2-row stratum and a net that could not see a
    per-pair-budget trade at all -- the proxy-vs-binding-predicate trap.
    """
    got: dict = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith("#"):
                    break
                for key, rx in BANNER.items():
                    if (m := rx.match(line)) and key not in got:
                        got[key] = m.group(1)
                if m := SUBS.match(line):
                    got["sub_saturation"] = int(m.group(1))
                    got["sub_tableau"] = int(m.group(2))
                if m := PROBES.match(line):
                    got["probe_saturation"] = int(m.group(1))
                    got["probe_tableau"] = int(m.group(2))
                if m := LABELS.match(line):
                    got["label_pruned"] = int(m.group(1))
                    got["label_pass_through"] = int(m.group(2))
    except OSError:
        pass
    if "classes" in got:
        got["classes"] = int(got["classes"])
    return got


def cmd_manifest(a) -> int:
    arm = a.arm
    cases = read_cases(SCRATCH / "runs" / arm / f"{arm}.jsonl")
    raw = SCRATCH / "raw" / arm
    rows = []
    for ont in sorted(cases):
        rec = cases[ont]
        out = raw / f"{ont}.out"
        row = {
            "ont": ont,
            "outcome": rec["outcome"],
            "wall_s": rec.get("wall_s"),
            "rss_kb": rec.get("peak_rss_kb"),
            "bytes": rec.get("bytes"),
            "out_bytes": out.stat().st_size if out.exists() else 0,
        }
        # A completer is defined by outcome==ok AND a non-empty captured closure. Not by
        # exit code alone: rustdl exits non-zero on a front-end rejection, and an `ok`
        # with a 0-byte capture would be a wrapper bug, not an answer.
        if row["outcome"] == "ok" and row["out_bytes"] > 0:
            row.update(banner_of(out))
        rows.append(row)
    dest = pathlib.Path(a.out) if a.out else SCRATCH / "work" / f"manifest-{arm}.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(json.dumps(r) + "\n" for r in rows))
    comp = [r for r in rows if r.get("fragment")]
    print(f"manifest {arm}: {len(rows)} cases, {len(comp)} completers with a banner")
    print("  outcomes:", dict(Counter(r["outcome"] for r in rows)))
    print("  fragment:", dict(Counter(r["fragment"] for r in comp)))
    print("  mode:", dict(Counter(r.get("mode", "-") for r in comp)))
    print(
        f"  search-exercised: {sum(1 for r in comp if search_exercised(r))}"
        f"   (main-tableau subsumption calls>0: {sum(1 for r in comp if r.get('sub_tableau', 0))},"
        f" tableau sat probes>0: {sum(1 for r in comp if r.get('probe_tableau', 0))},"
        f" label pass_through>0: {sum(1 for r in comp if r.get('label_pass_through', 0))})"
    )
    print(f"  -> {dest}")
    return 0


# ── select ──────────────────────────────────────────────────────────────────


def search_exercised(r: dict) -> bool:
    """Did a per-pair search actually run on this ontology?

    THE BINDING PREDICATE for the net's primary purpose. A per-pair budget
    (`--pair-timeout-ms`) or a depth cap can only lose an entailment on a pair that
    reaches the wedge/tableau oracle; an ontology answered entirely by the saturation
    fast path is structurally immune, so a population of those rows makes the net
    vacuous however large it is.

    Three counters, ORed, because each alone under-counts:
      * `# subsumption: … tableau=N`   main-tableau subsumption calls (RARE: 2/546)
      * `# satisfiability probes: … tableau=N`  tableau satisfiability probes
      * `# label heuristic: … pass_through=N`   pairs that SURVIVED the Phase-7 label
        prune and were sent to the oracle -- the common case by an order of magnitude
        (51/546), and the one a per-pair budget actually cuts.
    """
    return bool(
        r.get("sub_tableau", 0) or r.get("probe_tableau", 0) or r.get("label_pass_through", 0)
    )


def stratum(r: dict) -> str:
    """(fragment x is-a-per-pair-search-exercised) — the two axes the net must span."""
    return f"{r.get('fragment', '?')}/{'search' if search_exercised(r) else 'nosearch'}"


def cmd_select(a) -> int:
    rows = [json.loads(l) for l in pathlib.Path(a.manifest).read_text().splitlines() if l.strip()]
    frame = [r for r in rows if r.get("fragment")]
    by: dict[str, list[str]] = defaultdict(list)
    for r in frame:
        by[stratum(r)].append(r["ont"])
    for k in by:
        by[k].sort()

    search_strata = [k for k in by if k.endswith("/search")]
    # (the complementary /nosearch strata are enumerated per fragment below)

    # DELIBERATE OVER-SAMPLE of the rows where a per-pair search actually runs: take ALL
    # of them, up to --n-tableau. They are ~10% of the frame but the whole point of the
    # net -- a depth-cap or per-pair-budget trade CANNOT lose a pair on an ontology the
    # saturation fast path answered outright, so a population without them would be
    # vacuous for the net's primary purpose however large it was.
    rng = random.Random(a.seed)
    picked: list[str] = []
    quota: dict[str, int] = {}
    tab_pool = sorted(o for k in search_strata for o in by[k])
    tab_take = min(len(tab_pool), a.n_tableau)
    tab_sel = tab_pool if tab_take == len(tab_pool) else sorted(rng.sample(tab_pool, tab_take))
    picked += tab_sel
    tab_set = set(tab_sel)
    for k in search_strata:
        quota[k] = sum(1 for o in by[k] if o in tab_set)

    # The rest: EQUAL quota per fragment among the no-search rows, not proportional.
    # Proportional sampling would drown out-of-EL and Horn in pure-EL; the point is to
    # span the fragments, and the frame composition is reported alongside so nobody
    # mistakes the sample for a corpus share.
    budget = max(0, a.n - len(picked))
    order = [f"{f}/nosearch" for f in FRAGMENTS if f"{f}/nosearch" in by]
    remaining = budget
    for i, k in enumerate(order):
        share = remaining // (len(order) - i)
        take = min(share, len(by[k]))
        sel = sorted(rng.sample(by[k], take))
        quota[k] = take
        picked += sel
        remaining -= take
    picked = sorted(set(picked))

    dest = pathlib.Path(a.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(o + "\n" for o in picked))
    meta = {
        "seed": a.seed,
        "n_target": a.n,
        "n_search_target": a.n_tableau,
        "n_selected": len(picked),
        "manifest": str(a.manifest),
        "frame_size": len(frame),
        "frame_strata": {k: len(v) for k, v in sorted(by.items())},
        "sample_strata": dict(sorted(quota.items())),
        "list": str(dest),
    }
    (dest.with_suffix(".meta.json")).write_text(json.dumps(meta, indent=1) + "\n")
    print(json.dumps(meta, indent=1))
    return 0


# ── reuse ───────────────────────────────────────────────────────────────────


def cmd_reuse(a) -> int:
    """Adopt ALREADY-COMPUTED peer closures instead of recomputing them.

    The 2026-08-01 DNF-257 triage retained 243 Konclude and 150 HermiT hierarchies on
    the shared drive. Most of those ontologies are not in this population -- rustdl did
    not complete them then -- but v0.4.7..v0.4.13 recovered ~100, so the overlap is
    exactly the HARD tail, which is also the most expensive part of a peer leg (HermiT
    carries a measured 0.56 s docker+JVM floor per invocation on top of the work).

    Only CLASSIFIED rows with a non-empty file are adopted. A retained DNF is NOT
    adopted: it was recorded at a 120 s cap on a different day, and re-running it is the
    only way its outcome is comparable with the rest of this leg.
    """
    tri = {
        json.loads(l)["ont"]: json.loads(l)
        for l in pathlib.Path(a.triage).read_text().splitlines()
        if l.strip()
    }
    pop = [l.strip() for l in pathlib.Path(a.population).read_text().splitlines() if l.strip()]
    src = pathlib.Path(a.src)
    dst = SCRATCH / "raw" / a.peer
    dst.mkdir(parents=True, exist_ok=True)
    reused, remaining = [], []
    for ont in pop:
        row = tri.get(ont)
        cand = None
        if row is not None and row["verdict"] == "CLASSIFIED":
            hits = list(src.glob(f"*/{ont}.owx"))
            cand = next((h for h in hits if h.stat().st_size > 0), None)
        if cand is None:
            remaining.append(ont)
            continue
        target = dst / f"{ont}.owx"
        if not target.exists():
            try:
                os.link(cand, target)  # same volume: costs no space
            except OSError:
                target.write_bytes(cand.read_bytes())
        reused.append(
            {
                "kind": "case",
                "ont": ont,
                "outcome": "ok",
                "wall_s": row.get("wall_s"),
                "peak_rss_kb": row.get("rss_kb"),
                "reused_from": str(cand),
                "reused_cap_secs": 120,
            }
        )
    rdir = SCRATCH / "runs" / a.peer
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "reused.jsonl").write_text("".join(json.dumps(r) + "\n" for r in reused))
    pathlib.Path(a.out_remaining).write_text("".join(o + "\n" for o in remaining))
    print(
        f"reuse {a.peer}: adopted {len(reused)} retained closures, "
        f"{len(remaining)} still to run -> {a.out_remaining}"
    )
    return 0


# ── net ─────────────────────────────────────────────────────────────────────

FMT_SUFFIX = {"rustdl": ".out", "konclude": ".owx", "hermit": ".owx"}


def normalised_path(arm: str, ont: str) -> pathlib.Path:
    return SCRATCH / "tsv" / arm / f"{ont}.tsv"


def ensure_normalised(arm: str, fmt: str, ont: str) -> pathlib.Path | None:
    """Normalise one raw output to a cached TSV. Returns None if there is nothing to
    normalise (missing / empty capture)."""
    raw = SCRATCH / "raw" / arm / f"{ont}{FMT_SUFFIX[fmt]}"
    if not raw.exists() or raw.stat().st_size == 0:
        return None
    dest = normalised_path(arm, ont)
    if dest.exists() and dest.stat().st_mtime >= raw.stat().st_mtime:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = normalise.normalise_file(fmt, str(raw), None)
    tmp = dest.with_suffix(".tsv.part")
    with tmp.open("w", encoding="utf-8") as fh:
        n.write(fh)
    tmp.replace(dest)
    return dest


def peer_verdict(arm: str, fmt: str, ont: str, cases: dict[str, dict]) -> str:
    """DNF / CLASSIFIED / EMPTY / NO_OUTPUT, from the harness outcome plus CONTENT."""
    rec = cases.get(ont)
    if rec is None:
        return "ABSENT"
    if rec["outcome"] == "dnf":
        return "DNF"
    raw = SCRATCH / "raw" / arm / f"{ont}{FMT_SUFFIX[fmt]}"
    if not raw.exists() or raw.stat().st_size == 0:
        return "NO_OUTPUT"
    return "CLASSIFIED" if triage.declared_real_class(raw, fmt) else "EMPTY"


def union_oracle(ont: str, kon: pathlib.Path | None, her: pathlib.Path | None):
    """Konclude ∪ HermiT, as a normalised file on disk.

    Union of EDGES and union of the unsat / Thing-equivalent sidecars. Unioning the
    sidecars is the conservative choice: a class either peer calls unsatisfiable is
    excluded from the diff on both sides, so a satisfiability disagreement can never
    masquerade as thousands of missed pairs.
    """
    parts = [p for p in (kon, her) if p is not None]
    if not parts:
        return None
    merged = normalise.Normalised(source=ont, reasoner="oracle-union")
    for p in parts:
        n = normalise.read_normalised(str(p))
        merged.edges |= n.edges
        merged.unsat |= n.unsat
        merged.thing_equiv |= n.thing_equiv
    dest = normalised_path("oracle", ont)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tsv.part")
    with tmp.open("w", encoding="utf-8") as fh:
        merged.write(fh)
    tmp.replace(dest)
    return dest


def one_ontology(ont: str, arm: str, kcases, hcases, acases) -> dict:
    row: dict = {"ont": ont}
    arec = acases.get(ont)
    row["rustdl_outcome"] = arec["outcome"] if arec else "ABSENT"
    row["rustdl_wall_s"] = arec.get("wall_s") if arec else None

    kv = peer_verdict("konclude", "konclude", ont, kcases)
    hv = peer_verdict("hermit", "hermit", ont, hcases)
    row["konclude"] = kv
    row["hermit"] = hv

    kon = ensure_normalised("konclude", "konclude", ont) if kv == "CLASSIFIED" else None
    her = ensure_normalised("hermit", "hermit", ont) if hv == "CLASSIFIED" else None

    if kon is None and her is None:
        row["status"] = "no_oracle"
        return row

    # Peer-vs-peer FIRST: a contested oracle is not an oracle.
    if kon is not None and her is not None:
        pk = normalise.compare(str(kon), str(her))
        row["peer_pair_diff"] = pk["FP"] + pk["MISSED"]
        row["peer_unsat_diff"] = pk["unsat_disagreement"]
        row["konclude_closure"] = pk["candidate_closure"]
        row["hermit_closure"] = pk["oracle_closure"]
        row["oracle_source"] = "both"
    else:
        row["peer_pair_diff"] = 0
        row["peer_unsat_diff"] = 0
        row["oracle_source"] = "konclude" if kon is not None else "hermit"

    oracle = union_oracle(ont, kon, her)
    cand = ensure_normalised(arm, "rustdl", ont) if row["rustdl_outcome"] == "ok" else None
    if cand is None:
        # The arm did not finish (or produced nothing): there is no closure to diff, so
        # this is NOT a MISSED=0 row. Counted separately -- silently treating it as 0
        # would let a change that turns answers into timeouts look free.
        row["status"] = "arm_no_closure"
        return row

    res = normalise.compare(str(cand), str(oracle))
    row.update(
        {
            "arm_closure": res["candidate_closure"],
            "oracle_closure": res["oracle_closure"],
            "FP": res["FP"],
            "MISSED": res["MISSED"],
            "unsat_disagreement": res["unsat_disagreement"],
            "missed_sample": res["missed_sample"][:3],
            "fp_sample": res["fp_sample"][:3],
        }
    )
    if row["peer_pair_diff"] or row["peer_unsat_diff"]:
        row["status"] = "peer_disagreement"
    else:
        row["status"] = "scored"
    return row


def cmd_net(a) -> int:
    arm = a.arm
    pop = [
        l.strip()
        for l in pathlib.Path(a.population).read_text().splitlines()
        if l.strip() and not l.startswith("#")
    ]
    acases = read_cases(SCRATCH / "runs" / arm / f"{arm}.jsonl")
    kcases = read_cases(
        SCRATCH / "runs" / "konclude" / "reused.jsonl",
        SCRATCH / "runs" / "konclude" / "konclude.jsonl",
    )
    hcases = read_cases(
        SCRATCH / "runs" / "hermit" / "reused.jsonl",
        SCRATCH / "runs" / "hermit" / "hermit.jsonl",
    )

    # Subset to the population before submitting: the case dicts are pickled once PER
    # TASK, and shipping three 1,920-entry dicts to each of 400 tasks costs more than the
    # diffing does.
    keep = set(pop)
    acases = {k: v for k, v in acases.items() if k in keep}
    kcases = {k: v for k, v in kcases.items() if k in keep}
    hcases = {k: v for k, v in hcases.items() if k in keep}

    rows: list[dict] = []
    with futures.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(one_ontology, o, arm, kcases, hcases, acases): o for o in pop}
        for i, f in enumerate(futures.as_completed(futs), 1):
            try:
                rows.append(f.result())
            except Exception as exc:  # noqa: BLE001 — one bad ontology must not kill the net
                rows.append({"ont": futs[f], "status": "error", "error": repr(exc)})
            if i % 50 == 0:
                print(f"  ...{i}/{len(pop)}", file=sys.stderr)
    rows.sort(key=lambda r: r["ont"])

    dest = pathlib.Path(a.out) if a.out else SCRATCH / "work" / f"net-{arm}.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(json.dumps(r) + "\n" for r in rows))

    summary = summarise(rows, arm)
    if a.baseline:
        summary["delta_vs_baseline"] = delta(rows, a.baseline)
    (dest.with_suffix(".summary.json")).write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


def summarise(rows: list[dict], arm: str) -> dict:
    scored = [r for r in rows if r["status"] == "scored"]
    missed = sorted((r["MISSED"] for r in scored), reverse=True)
    total = sum(missed)
    return {
        "arm": arm,
        "population": len(rows),
        "status": dict(Counter(r["status"] for r in rows)),
        "oracle_source": dict(Counter(r.get("oracle_source", "-") for r in rows)),
        "peer_disagreement": sum(1 for r in rows if r["status"] == "peer_disagreement"),
        "scored": len(scored),
        "MISSED_total": total,
        "onts_with_MISSED": sum(1 for m in missed if m),
        "MISSED_top10": [
            [r["ont"], r["MISSED"]] for r in sorted(scored, key=lambda r: -r["MISSED"])[:10]
        ],
        # FP is free here and is a hard invariant: rustdl's contract is FP=0. A nonzero
        # value against a UNION oracle is a soundness alarm, not a completeness datum.
        "FP_total": sum(r.get("FP", 0) for r in scored),
        "onts_with_FP": sum(1 for r in scored if r.get("FP", 0)),
        "oracle_closure_total": sum(r.get("oracle_closure", 0) for r in scored),
    }


def delta(rows: list[dict], baseline_path: str) -> dict:
    """ΔMISSED per ontology against a committed baseline net.

    The whole reason a baseline is committed: an absolute MISSED total is
    uninterpretable (rustdl is a documented sound under-approximation in places), while
    a DELTA is exactly the completeness trade a change is asking for.
    """
    base = {
        json.loads(l)["ont"]: json.loads(l)
        for l in pathlib.Path(baseline_path).read_text().splitlines()
        if l.strip()
    }
    lost, gained, newly_unscored = [], [], []
    dm = 0
    for r in rows:
        b = base.get(r["ont"])
        if b is None:
            continue
        if b["status"] == "scored" and r["status"] != "scored":
            newly_unscored.append([r["ont"], b["status"], r["status"]])
            continue
        if b["status"] != "scored" or r["status"] != "scored":
            continue
        d = r["MISSED"] - b["MISSED"]
        dm += d
        if d > 0:
            lost.append([r["ont"], b["MISSED"], r["MISSED"]])
        elif d < 0:
            gained.append([r["ont"], b["MISSED"], r["MISSED"]])
    return {
        "baseline": baseline_path,
        "delta_MISSED_total": dm,
        "onts_lost_pairs": len(lost),
        "onts_gained_pairs": len(gained),
        "lost": sorted(lost, key=lambda x: x[1] - x[2])[:25],
        "gained": sorted(gained, key=lambda x: x[2] - x[1])[:25],
        # A change that converts scored answers into timeouts is NOT a free win.
        "newly_unscored": newly_unscored[:25],
        "n_newly_unscored": len(newly_unscored),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("manifest", help="banner + outcome per ontology for one arm")
    p.add_argument("--arm", required=True)
    p.add_argument("-o", "--out")

    p = sub.add_parser("select", help="seeded stratified population")
    p.add_argument("--manifest", required=True)
    p.add_argument("--n", type=int, default=400)
    p.add_argument("--n-tableau", type=int, default=200)
    p.add_argument("--seed", type=int, default=20260803)
    p.add_argument("-o", "--out", required=True)

    p = sub.add_parser("reuse", help="adopt retained peer closures; emit the remainder")
    p.add_argument("--peer", required=True, choices=["konclude", "hermit"])
    p.add_argument("--triage", required=True, help="triage jsonl with the verdicts")
    p.add_argument("--src", required=True, help="retained hierarchy dir (batched)")
    p.add_argument("--population", required=True)
    p.add_argument("--out-remaining", required=True)

    p = sub.add_parser("net", help="per-ontology MISSED vs Konclude ∪ HermiT")
    p.add_argument("--arm", required=True)
    p.add_argument("--population", required=True)
    p.add_argument("--baseline", help="baseline net jsonl -> report ΔMISSED")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("-o", "--out")

    a = ap.parse_args()
    return {
        "manifest": cmd_manifest,
        "select": cmd_select,
        "reuse": cmd_reuse,
        "net": cmd_net,
    }[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
