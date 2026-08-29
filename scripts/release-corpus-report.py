#!/usr/bin/env python3
"""Analyse a release corpus sweep: publishable stats + a verdict-regression gate.

Encodes the checks that this project has paid for one at a time. Each is here
because omitting it produced a wrong published number at least once:

* OUTCOME FROM CONTENT, NOT EXIT CODE. A reasoner can exit 0 having classified
  nothing.
* VERDICT REGRESSION IS ITS OWN GATE. `ok -> dnf` = 0 and dMISSED < 5% do NOT imply
  the `consistent` answer is unchanged (2026-08-15, ore_ont_16372).
* COMPARE CLOSURES, NOT REDUCTIONS. `direct_subsumptions` is a transitive reduction,
  so losing one subsumption can ADD direct edges. Diffing reductions raised three
  false soundness alarms in one sitting.
* PERCENTILES, NOT MEANS ALONE. This corpus is dominated by sub-second ontologies
  and decided by a heavy tail; a mean hides both.
"""
import argparse, collections, json, os, platform, statistics, sys


def load_case_jsonls(run_dir):
    rows = {}
    for f in sorted(os.listdir(run_dir)):
        if not f.endswith(".jsonl"):
            continue
        for line in open(os.path.join(run_dir, f), errors="replace"):
            if '"kind":"case"' not in line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            rows[os.path.splitext(os.path.basename(r["ont"]))[0]] = r
    return rows


def read_verdicts(raw_dir):
    """Per-ontology verdict, judged from CONTENT. Missing/unparseable -> None."""
    out = {}
    if not os.path.isdir(raw_dir):
        return out
    for f in os.listdir(raw_dir):
        if not f.endswith(".json"):
            continue
        stem, p = f[:-5], os.path.join(raw_dir, f)
        if os.path.getsize(p) == 0:
            continue
        try:
            d = json.load(open(p, errors="replace"))
        except Exception:
            continue
        out[stem] = {
            "consistent": d.get("consistent"),
            "incomplete": d.get("incomplete"),
            "unsat": len(d.get("unsatisfiable", [])),
            # CLOSURE size, not the reduction: expand equivalence groups and
            # transitively close, so a reduction reshuffle is not read as a change.
            "closure": closure_size(d),
        }
    return out


def closure_size(d):
    adj = {}
    for a, b in d.get("direct_subsumptions", []):
        adj.setdefault(a, set()).add(b)
    for g in d.get("equivalent_groups", []):
        for a in g:
            for b in g:
                if a != b:
                    adj.setdefault(a, set()).add(b)
    n = 0
    for s in adj:
        seen, st = set(), [s]
        while st:
            x = st.pop()
            for y in adj.get(x, ()):
                if y not in seen:
                    seen.add(y)
                    st.append(y)
        n += len(seen)
    return n


def pct(v, q):
    if not v:
        return 0.0
    v = sorted(v)
    return v[min(int(q * len(v)), len(v) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--binary-sha", default="")
    ap.add_argument("--cap-secs", type=int, default=60)
    ap.add_argument("--baseline", help="previous release's baseline JSON")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    a = ap.parse_args()

    cases = load_case_jsonls(a.run_dir)
    verd = read_verdicts(a.raw_dir)

    # A BROKEN INSTRUMENT MUST NOT READ AS A RESULT. `skipped` means the harness
    # never ran the ontology (unresolved path, bad --only format); counting those as
    # DNF turns a total run failure into a plausible "0 classified, 424 DNF"
    # catastrophic-regression report. Observed on this script's first invocation.
    skipped = [k for k, r in cases.items() if r.get("outcome") == "skipped"]
    if skipped:
        ex = cases[skipped[0]].get("skip_reason", "")
        sys.exit(f"ABORT: {len(skipped)}/{len(cases)} ontologies were SKIPPED, not run "
                 f"— the sweep did not happen. First reason: {ex}")
    # SAME RULE, SECOND SHAPE (2026-08-29). The `skipped` guard above catches a run
    # the harness never started. It does NOT catch a run where every case STARTED and
    # the wrapper died: those land as `err_reject`, are counted as DNF, and the report
    # reads "0 classified / 424 DNF" — after which the confirmation pass re-runs the
    # "losses" at 3x cap, finds they classify in 0.0s, and prints "CAP-BORDERLINE,
    # gate PASSES". A total measurement failure thus reported as a PASS, twice.
    #
    # Cause that day: `wrappers/*.sh` set `ulimit -v`, which Darwin has no RLIMIT_AS
    # for, so the wrapper exited before invoking the reasoner. An ontology that
    # classifies in 0.0s at 180s was never cap-borderline at 60s.
    by_outcome = collections.Counter(r.get("outcome") for r in cases.values())
    n_ok_outcome = by_outcome.get("ok", 0)
    if cases and n_ok_outcome == 0:
        top = by_outcome.most_common(1)[0]
        sys.exit(f"ABORT: 0 of {len(cases)} ontologies produced outcome `ok` "
                 f"(most common: `{top[0]}` x{top[1]}) — the instrument failed, this is "
                 f"not a result. Check the wrapper runs standalone before re-running.")
    for outcome, n in by_outcome.items():
        if outcome not in ("ok", "timeout") and n > len(cases) // 2:
            sys.exit(f"ABORT: {n}/{len(cases)} ontologies share the single failure "
                     f"outcome `{outcome}` — that is an instrument fault, not a "
                     f"population of hard ontologies.")

    ok = {k: r for k, r in cases.items() if r.get("outcome") == "ok" and k in verd}
    dnf = [k for k, r in cases.items() if r.get("outcome") != "ok"]
    # exit-0-but-no-output: counted as NOT classified, per the content rule
    empty = [k for k, r in cases.items() if r.get("outcome") == "ok" and k not in verd]

    walls = [r["wall_s"] for r in ok.values()]
    rss = [r["peak_rss_kb"] / 1024.0 for r in ok.values()]
    cur = {
        "version": a.version,
        "binary_sha": a.binary_sha,
        "cap_secs": a.cap_secs,
        # HOST PROVENANCE (2026-08-29). The `lost_ontologies` gate is CAP-SENSITIVE:
        # it asks whether an ontology finished inside --cap-secs. That is a property of
        # the MACHINE as much as of the binary, so comparing against a baseline measured
        # elsewhere is not a valid comparison. Measured: a v0.4.23 baseline from a faster
        # host made a good v0.4.24 build report `2 ontologies lost` and FAIL. Re-measuring
        # the SAME v0.4.23 binary on the candidate's host moved the median 0.21s -> 0.53s
        # (2.5x, across all 424) and the gate went to PASS with 0 lost -- the candidate in
        # fact classified one MORE. Both "lost" ontologies were near the cap (~49s and
        # ~59s standalone) and are arm-identical on 3 alternating-order runs.
        # Record the host so a cross-host comparison is at least VISIBLE; re-baseline on
        # the machine you are gating on.
        "host": {"node": platform.node(), "system": platform.system(),
                 "machine": platform.machine(), "cpu_count": os.cpu_count()},
        "population": len(cases),
        "classified": len(ok),
        "dnf": len(dnf),
        "empty_output": len(empty),
        "wall_s": {"mean": round(statistics.fmean(walls), 4) if walls else 0,
                   "median": round(statistics.median(walls), 4) if walls else 0,
                   "p90": round(pct(walls, 0.90), 3), "max": round(max(walls), 2) if walls else 0},
        "peak_rss_mib": {"mean": round(statistics.fmean(rss), 1) if rss else 0,
                         "median": round(statistics.median(rss), 2) if rss else 0,
                         "p90": round(pct(rss, 0.90), 1), "max": round(max(rss), 1) if rss else 0},
        "inconsistent_onts": sorted(k for k, v in verd.items() if v["consistent"] is False),
        "incomplete_onts": sum(1 for v in verd.values() if v["incomplete"]),
        "verdicts": {k: {"consistent": v["consistent"], "closure": v["closure"]}
                     for k, v in verd.items()},
    }

    gate = {"verdict_flips": [], "lost_ontologies": [], "closure_regressions": []}
    base = json.load(open(a.baseline)) if a.baseline and os.path.exists(a.baseline) else None
    if base:
        bv = base.get("verdicts", {})
        for k, v in bv.items():
            if k in cur["verdicts"]:
                if cur["verdicts"][k]["consistent"] != v["consistent"]:
                    gate["verdict_flips"].append(
                        {"ont": k, "was": v["consistent"], "now": cur["verdicts"][k]["consistent"]})
                if cur["verdicts"][k]["closure"] < v["closure"]:
                    gate["closure_regressions"].append(
                        {"ont": k, "was": v["closure"], "now": cur["verdicts"][k]["closure"]})
            elif k in {os.path.splitext(x)[0] for x in cases}:
                gate["lost_ontologies"].append(k)
    cur["gate"] = gate
    json.dump(cur, open(a.out_json, "w"), indent=1, sort_keys=True)

    L = []
    L.append(f"### Corpus report — {a.version}\n")
    L.append(f"Population **{cur['population']}** ontologies · cap **{a.cap_secs}s** · 1 thread"
             + (f" · binary `{a.binary_sha[:12]}`" if a.binary_sha else "") + "\n")
    L.append("| | classified | DNF | empty output |")
    L.append("|---|---|---|---|")
    L.append(f"| count | **{cur['classified']}** | {cur['dnf']} | {cur['empty_output']} |\n")
    w, m = cur["wall_s"], cur["peak_rss_mib"]
    L.append("| | mean | median | p90 | max |")
    L.append("|---|---|---|---|---|")
    L.append(f"| wall (s) | {w['mean']} | {w['median']} | {w['p90']} | {w['max']} |")
    L.append(f"| peak RSS (MiB) | {m['mean']} | {m['median']} | {m['p90']} | {m['max']} |\n")
    L.append(f"Reported inconsistent: **{len(cur['inconsistent_onts'])}** · "
             f"flagged incomplete: **{cur['incomplete_onts']}**\n")
    if base:
        flips, lost, cregs = gate["verdict_flips"], gate["lost_ontologies"], gate["closure_regressions"]
        status = "PASS" if not (flips or lost) else "**FAIL**"
        L.append(f"**Gate vs `{base.get('version','baseline')}`: {status}**\n")
        # CROSS-HOST BASELINES INVALIDATE THE CAP-SENSITIVE HALF OF THIS GATE.
        # `lost_ontologies` asks "did it finish inside the cap", which the machine
        # decides as much as the binary. Say so loudly rather than letting a hardware
        # difference read as a regression (it did once; see the `host` key above).
        bh = base.get("host") or {}
        ch = cur["host"]
        if not bh:
            L.append(f"> ⚠️ Baseline records NO host. If it was measured on different "
                     f"hardware, `ontologies lost` is not a valid comparison — "
                     f"re-baseline on this host (`{ch['node']}`, {ch['cpu_count']} cores).\n")
        elif (bh.get("node"), bh.get("machine")) != (ch["node"], ch["machine"]):
            L.append(f"> ⚠️ CROSS-HOST COMPARISON: baseline `{bh.get('node')}` "
                     f"({bh.get('machine')}, {bh.get('cpu_count')} cores) vs this run "
                     f"`{ch['node']}` ({ch['machine']}, {ch['cpu_count']} cores). "
                     f"`ontologies lost` is cap-sensitive and NOT comparable across hosts; "
                     f"re-baseline before believing a FAIL.\n")
        L.append(f"- consistency-verdict flips: **{len(flips)}** (must be 0)")
        for f in flips[:10]:
            L.append(f"  - `{f['ont']}`: consistent {f['was']} → {f['now']}")
        L.append(f"- ontologies lost (classified → not): **{len(lost)}** (must be 0)")
        for x in lost[:10]:
            L.append(f"  - `{x}`")
        L.append(f"- closure shrank on: {len(cregs)} (informational; a smaller "
                 f"per-pair budget legitimately under-approximates)")
        for c in cregs[:5]:
            L.append(f"  - `{c['ont']}`: {c['was']} → {c['now']}")
    else:
        L.append("_No baseline supplied — this run establishes one._")
    open(a.out_md, "w").write("\n".join(L) + "\n")

    print("\n".join(L))
    if base and (gate["verdict_flips"] or gate["lost_ontologies"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
