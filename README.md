# owl-corpus-harness

A **reasoner-agnostic corpus measurement harness**. Point it at a directory of ontologies
and a reasoner command; it produces one durable record per ontology — wall time, peak RSS,
and an exit-code-derived outcome — then aggregates and compares runs.

Modelled on [horned-roundtrip](https://github.com/micheldumontier/horned-roundtrip)'s
`fetch / run / report` shape, and built because the *harness* is what keeps producing wrong
numbers, not the reasoner.

## Why this exists

Every feature below exists because its absence produced a retracted measurement. These are
not hypothetical:

| Feature | Failure it prevents |
|---|---|
| **Binary fingerprint** (sha256 + `--version` + optional marker grep) recorded per run | A ~2-hour sweep measured a *sabotaged debug build* whose source had been reverted without rebuilding. The headline was wrong in both directions. |
| **Exit-code outcome categories**, never row-count heuristics | Two ontologies streamed partial output before being killed at a cap; a `rows > 0` heuristic scored them "complete". |
| **Record actual wall; never bake in a timeout** | Choosing a cap up front throws away every other threshold and forces re-runs. |
| **Explicit excluded/skipped accounting** | A 30 s cap silently dropped the 17 largest ontologies. Because the largest happened to be the least interesting, a corpus-share figure came out 3× too high and had to be retracted. A per-item timeout is **not a neutral sampler** — it selects against large items. |
| **Thread pin recorded per run** | Peak RSS swings ~35× with fan-out (one ontology: 42 MB single-thread vs 1.47 GB across cores). RSS without a recorded pin is uninterpretable. |
| **One invocation per ontology** | A draft harness ran the reasoner twice per file — double cost, and the two runs could disagree. |
| **Streaming JSONL, resumable** | A pipeline through `tail` lost everything when an outer timeout killed the loop; `tail` buffers to EOF. |
| **`compare` as a first-class verb** | Answer-identity across two builds (e.g. "286 ontologies, 0 diffs") was hand-rolled each time it was needed. |

## Model

```
run     corpus + reasoner-cmd ──► per-ontology: fingerprint-checked invocation
                                   ─► wall + peak RSS + exit code ─► JSONL (streamed)
report  results.jsonl ──────────► summary.json + cases.csv + report.md
compare run-a.jsonl run-b.jsonl ─► outcome deltas + answer-identity diff
```

- **The reasoner is a command, not a dependency.** It is invoked by path, so the harness can
  measure several builds of the same reasoner (`v0.4.5` vs `v0.4.6`, flag ON vs OFF) and other
  reasoners (Konclude, HermiT, ELK, whelk) with the same code. A harness compiled *inside* the
  system under test can only measure itself — which is exactly how the stale-binary failures
  happened.
- **Outcomes are derived from the exit code**, and kept distinct:

| Outcome | Meaning | Actionable as |
|---|---|---|
| `Ok` | exit 0 | completed |
| `Dnf` | killed at the cap | search/scale blowup |
| `ErrReject` | non-zero, non-signal exit | front-end rejection (unsupported construct) — usually a *cheaper, different* problem |
| `ErrCrash` | killed by a signal other than the cap | panic / OOM |
| `Skipped` | excluded by `--max-bytes` or a filter | **counted, never silently dropped** |

  Collapsing `ErrReject` into `Dnf` is how a DNF roster becomes unactionable: one is a
  converter gap, the other a reasoning limit.

## Usage

```sh
cargo build --release

# measure. --require-marker greps the binary and ABORTS if absent, so an
# instrumented/sabotaged build can never be mistaken for the real one.
owl-corpus-harness run \
    --corpus /data/ore/files \
    --reasoner ./target/release/rustdl --args 'classify {}' \
    --cap-secs 30 --threads 1 --max-bytes 400000000 \
    --out runs/v046.jsonl

# aggregate; --at derives would-miss counts for any cap <= the run's cap, no re-run
owl-corpus-harness report runs/v046.jsonl --at 1,5,10,30 --top-rss 25

# two builds or two flag settings
owl-corpus-harness compare runs/v045.jsonl runs/v046.jsonl
```

`{}` in `--args` is replaced by the ontology path. `--threads` sets `RAYON_NUM_THREADS`
(recorded in the header; omit only if the reasoner is single-threaded anyway).

## The run header

Every JSONL file opens with one `Header` record. It is the reproducibility contract:

```json
{"kind":"header","reasoner":"./target/release/rustdl","sha256":"9f2c…","version":"rustdl 0.4.6",
 "marker_checked":"XCLONEX","threads":1,"cap_secs":30,"max_bytes":400000000,
 "corpus":"/data/ore/files","n_candidates":1920,"host_cores":32}
```

If two runs disagree, compare headers first. Most disagreements in practice were not
behaviour changes but different binaries, different thread pins, or different caps.

## Reporting rules

`report` refuses to print a corpus-share percentage without also printing the excluded set,
and refuses to print an RSS figure without the thread pin. Both rules exist because the
opposite happened and produced retracted numbers. A share whose denominator excluded the
largest items is not a share.
