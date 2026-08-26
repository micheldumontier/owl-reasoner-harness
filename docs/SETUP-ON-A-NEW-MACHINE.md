# Setting up the measurement harness on a new machine

Everything needed to go from a bare machine to a reproducible two-arm corpus measurement.

**Why this file exists.** The measurement *discipline* was well documented
(`skills/corpus-measurement/SKILL.md`, `rustdl/docs/releases/RELEASE-PROCESS.md`) but the
*provisioning* was not: the ORE corpus existed on the original host only because a 692 MB zip
happened to sit in `/data/dumontier/ore-run/`, and its provenance was recorded in a file that
directory's own README says is "not committed to repo". On a fresh machine you would have been stuck
at step one.

---

## 1. Prerequisites

```sh
rustup default stable          # see the toolchain gotcha below
java -version                  # 11+ , for HermiT
python3 --version              # 3.8+ , for the diff/adjudication scripts
```

> **Toolchain gotcha (carried from `rustdl/CLAUDE.md`).** `rust-toolchain.toml` pins 1.95.0 but that
> toolchain is often installed *without* `cargo` (rustup `profile = minimal`), and a failed build
> then **silently reuses a stale `target/release/` binary**. Build and benchmark with
> `RUSTUP_TOOLCHAIN=stable cargo …`, and always confirm the binary is freshly built.

## 2. Repositories

| repo | purpose |
|---|---|
| `rustdl` | the reasoner under test |
| `owl-reasoner-harness` | this harness — `run` / `report` / `compare` |

Both are ordinary git clones. `rustdl` `[patch]`es a `horned-owl` fork **by git rev**, so cargo
fetches it automatically — no local fork checkout is required.

## 3. The ORE corpus — the part that was missing

**Source: Zenodo record 18578**, DOI **10.5281/zenodo.18578** — "ORE 2015 Reasoner Competition
Corpus" (Matentzoglu & Parsia).

```sh
mkdir -p ~/ore-run && cd ~/ore-run
# ore2015_sample.zip — 725 MB as published (692 MB on disk)
# md5 109f04cf8f124eb551d33c100e549730   <- VERIFY THIS
md5sum ore2015_sample.zip
unzip -q ore2015_sample.zip
```

Expected result: **1,920 `.owl` files** under `pool_sample/files/`. That count is the denominator in
every corpus claim in the design record, so check it:

```sh
ls pool_sample/files/*.owl | wc -l      # must be 1920
```

**The `.owl` files are OWL functional syntax despite the extension.** rustdl content-sniffs via
`detect_format`, so this is fine — but a tool that trusts the extension will mis-parse them. This has
caused a wrong result before.

Point the harness at it with `--corpus /path/to/pool_sample/files`, or set `CORPUS=` for the release
report script.

## 4. Peer reasoners (for oracle adjudication)

Needed only when adjudicating a suspected FP/MISS — but you *will* need them for that, and
`Konclude`'s silence is ambiguous, so you generally want both.

**Konclude** — download the Linux static build, then note the trap:

```sh
# The top-level `Konclude` is a SHIM that fails with rc=127:
#   ./Binaries/Konclude: No such file or directory
# The real executable is one level down. Use it directly:
KONCLUDE=.../Konclude-v0.7.0-*-Linux-x64-*/Binaries/Konclude
"$KONCLUDE" classification -i in.owl -o out.owx
"$KONCLUDE" realisation    -i in.owl -o out.owx     # British spelling
```

**Judge peer outcome from CONTENT, not exit code.** Konclude exits 0 on missing or junk input and
writes an ~896-byte `Thing`/`Nothing` taxonomy. It also prints its *log* to stdout and the taxonomy
to `-o`; reading the wrong stream once made a successful 55 ms classification look like a refusal.

**HermiT** — a JAR invoked via `java -jar`. Expect OOM on the largest ontologies; when both oracles
are unavailable, adjudicate by deriving the disputed entailment from the definitional axioms instead
of picking a side.

## 5. The two-arm method

```sh
cargo build --release                      # arm A
cp target/release/rustdl /tmp/rustdl.A     # PIN IT IMMEDIATELY
# ... change something ...
cargo build --release                      # arm B
cp target/release/rustdl /tmp/rustdl.B

# VERIFY THE PIN DISCRIMINATES on an input whose answer differs between arms,
# before trusting any sweep built on it.
```

**Never measure from a shared build path.** A shared path has twice measured the wrong
configuration here, once wasting a two-hour scan that reported 443 reduced / 0 residual against a
true 325 / 3.

Then per arm:

```sh
owl-reasoner-harness run \
  --corpus .../pool_sample/files \
  --reasoner wrappers/run-rustdl-json.sh --args '{}' \
  --cap-secs 60 --threads 1 --ext owl \
  --out runA.jsonl
owl-reasoner-harness compare runA.jsonl runB.jsonl     # outcome transitions + answer identity
```

`--threads 1` matters: parallel arms contend, and under a *truncating* per-pair budget the hierarchy
is not run-to-run deterministic, so contention manufactures phantom diffs. One release gate flagged
an ontology as lost on three consecutive runs and it was a different ontology each time.

## 6. What gets measured

The run's JSONL opens with a provenance header — `reasoner`, binary `sha256`, `version`,
`threads`, `cap_secs`, `corpus`, `host_cores`, `marker_checked`, `n_candidates` — then one record per
ontology. The metrics that matter:

| metric | where from | trap |
|---|---|---|
| **consistent / inconsistent** | `classify --json` `consistent` | classify and `consistent` disagreed on `family.ofn` for months; the corpus report has a dedicated **verdict gate** because neither a sweep nor a ΔMISSED arm can see a verdict flip |
| **entailments** | `direct_subsumptions` | **compare CLOSURES, not this.** It is a transitive *reduction*: losing one subsumption promotes an endpoint to a direct edge, so a diff shows *additions* where the closure only shrank. Three false alarms in one sitting. Progress also *removes* rows (unsat elision, equivalence collapse), so it is not a monotone progress measure either |
| **wall time** | harness timing | cap-borderline ontologies straddle the cap with ~2× spread; a single run is a coin toss. Re-run a reported loss at 3× the cap before believing it |
| **peak RSS** | harness | the multi-GB tail is real but rarer than assumed; most "memory" wins turn out to be skipped compute |
| **incomplete** | `classify`/`realize --json` | counts pairs *attempted and cut*, **not remaining**. A small value is not evidence of near-completeness: raising a budget took one ontology from `inc=1` to `inc=15,042` with unchanged rows |

**Strip `#` banner lines before diffing output** — they carry per-phase wall timings and differ
between any two runs. Including them once reported 1,322 "unexplained differences" where the truth
was 0.

## 7. Gates before shipping

Full sequence and rationale: `rustdl/docs/releases/RELEASE-PROCESS.md`. In short:

1. `cargo test --workspace --exclude owl-dl-py` + `cargo clippy --workspace --all-targets
   --all-features -- -D warnings` + `cargo fmt --all -- --check`. **Run the clippy line verbatim** —
   dropping `-D warnings` turns the gate into a no-op that still prints reassuringly, which has let
   red CI through twice.
2. `rustdl/scripts/run-soundness-diff.sh` — the FP=0 net (~4 min). Needs ~12 MB of gitignored
   fixtures via `rustdl/scripts/fetch-real-ontologies.sh`. **CI green does not imply FP=0.**
3. `owl-reasoner-harness/scripts/release-corpus-report.sh VERSION BINARY [BASELINE_JSON]` — the
   corpus report + verdict gate (~20 min, 424 ontologies = 400 stratified + 24 sentinels).
4. A two-arm full sweep over all 1,920 for `ok → dnf` regressions.
5. The MISSED net when trading completeness for speed. **Byte-identical output subsumes it** — an
   output-identical change cannot have lost a row.

The three gates are not substitutes: the MISSED net cannot see an `ok → dnf` (its frame is drawn
from completers), and neither a sweep nor the MISSED net can see a verdict change.

## 8. Read this too

* `skills/corpus-measurement/SKILL.md` — the discipline this tool cannot enforce.
* `rustdl/docs/releases/RELEASE-PROCESS.md` — §4 "Comparison rules that have each cost a wrong
  result" is the highest-value page here.
* `docs/missed-net.md` — the ΔMISSED net.
