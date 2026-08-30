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

## 1b. FIRST decide: can the machine BUILD, or only MEASURE?

**Check this before anything else.** A cluster node may have no C toolchain and no root, in which
case `cargo build` cannot link and §2's "clone and build" path is a dead end.

```sh
for c in cc gcc clang make; do printf "%-8s %s\n" "$c" "$(command -v $c || echo MISSING)"; done
sudo -n true 2>/dev/null && echo "sudo: yes" || echo "sudo: NO"
```

Measured on `n3` (2026-08-27): **`cc`, `gcc`, `clang`, `make`, `pkg-config` all MISSING and no
passwordless sudo** — `ld` alone is not enough, and `rustup` itself warns *"no default linker (`cc`)
was found in your PATH"*. There were also no userspace package managers (conda/mamba/spack/brew/nix)
to install one without root. So that node **cannot build rustdl at all.**

### The build-here / measure-there model

This is not a workaround so much as the natural fit: a big node's value is *running* sweeps, and
this project already requires pinning a binary per configuration, so the binary is the unit that
travels.

```sh
# On the BUILD host:
ldd --version | head -1                      # compare with the target host FIRST
cargo build --release                        # per arm
rsync -a target/release/rustdl                       TARGET:/data/$USER/bin/rustdl.ARM_A
rsync -a ../owl-reasoner-harness/target/release/owl-reasoner-harness                                                      TARGET:/data/$USER/owl-reasoner-harness/target/release/
rsync -a --exclude target --exclude .git ../owl-reasoner-harness/ TARGET:/data/$USER/owl-reasoner-harness/
```

**Verify glibc matches before relying on this.** Both hosts here reported
`ldd (Ubuntu GLIBC 2.35-0ubuntu3.14) 2.35`, so copied binaries ran unmodified. A target with an
*older* glibc than the build host will fail at load time with a `GLIBC_x.yz not found` error; build
on the oldest machine you intend to run on, or build a `musl` target.

Everything else the harness needs — `scripts/`, `wrappers/`, `baselines/`, `skills/` — is shell and
Python, so it just copies.

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

### Also set `SCRATCH` — its default will not exist on your machine

`release-corpus-report.sh` defaults to an NFS path specific to the original host:

```sh
SCRATCH=${SCRATCH:-/mnt/um-share-drive/dumontier/missed-net}
RUN="$SCRATCH/runs/$TAG"; RAW="$SCRATCH/raw/$TAG"
```

**Override it.** Found by actually checking a second machine (`n3`, 2026-08-26): that mount was
absent, so a verbatim run of this guide would have failed at the first release report.

```sh
export SCRATCH=/data/$USER/harness-scratch     # local disk is FINE and faster than NFS
```

Budget generously — `raw/` accumulates per-ontology output. On the original host it reached **251 GB**
across 36 sweeps before pruning; a single 1,920-ontology arm is roughly **0.9–2.5 GB**, but census
runs reached 88 GB. Prune old sweeps deliberately rather than letting them accumulate, and **keep
any `konclude/` and `hermit/` directories** — those are oracle outputs, expensive to regenerate and
the basis of every FP=0 adjudication.

### What a bare second machine actually lacked

Measured on `n3` (2026-08-26) — a useful checklist because it is what "bare" really means here:

| present | missing |
|---|---|
| `git`, `python3`, `unzip`, **`perf` matching the running kernel** | **`cargo`/`rustc` (no Rust at all)**, `java` (HermiT), the NFS share, the ORE corpus, both repos |

Note `perf` worked there out of the box, whereas the original host needed a matching
`linux-tools-$(uname -r)` install before `perf record` would run at all. If `perf` is present but
refuses, that mismatch is the first thing to check.

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

### 4a. Behind an egress proxy (measured 2026-08-29, a Coder/k8s workspace)

`sudo apt-get update` failed on every mirror while `curl https://...` worked as the normal
user. **It is not a port-80 firewall** — that was my first diagnosis and it was wrong, because
I compared `sudo apt` against `curl` run *unprivileged*, which is not a controlled comparison.

The host exports `HTTP_PROXY`/`HTTPS_PROXY` (a Squid at `:3128`) and **`sudo`'s `env_reset`
strips them**, so apt had no route out. Two consequences:

```sh
P=http://egress-proxy.platform.svc.cluster.local:3128
printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\n' "$P" "$P" \
  | sudo tee /etc/apt/apt.conf.d/99proxy      # persistent; `sudo apt` then just works
curl -x "$P" ...                              # and use https:// for direct fetches:
```
The proxy tunnels `CONNECT` to 443 but does **not** forward plain HTTP, so an `http://` URL
returns a ~280-byte error page. `dpkg-deb` then says *"not a Debian format archive"*, which
looks like a corrupt download rather than a refused protocol.

### 4b. Konclude's Linux build needs `libpcre.so.3`

PCRE1 is retired, so `libpcre3` is **not in modern Ubuntu repos** and the binary dies with
`rc=127` — indistinguishable from the `Binaries/Konclude` shim trap above. `ldd` names the real
cause. Extract the library from an older `.deb` and point `LD_LIBRARY_PATH` at it:

```sh
curl -sSL -o p.deb https://archive.ubuntu.com/ubuntu/pool/main/p/pcre3/libpcre3_8.39-9ubuntu0.1_amd64.deb
dpkg-deb -x p.deb ext && cp ext/lib/x86_64-linux-gnu/libpcre.so.3* ~/peers/lib/
```

**Do NOT symlink PCRE2 to `libpcre.so.3`.** An ABI mismatch could silently corrupt oracle
output, which is strictly worse than having no oracle. **Validate a fresh peer build against a
known answer before trusting it**: the Linux Konclude reproduced the OSX closure on
`ore_ont_778` exactly (630 = 630), which is what licensed using it.

### 4c. HermiT output must be named `.owx`, whatever is inside it

`missed-net.py` has `FMT_SUFFIX = {"rustdl": ".out", "konclude": ".owx", "hermit": ".owx"}`
while HermiT via robot's CommandLine writes **functional syntax**. Naming its output `.ofn` —
the honest extension — makes the analyser find nothing: 322 real oracle files went invisible,
389 ontologies scored `hermit: NO_OUTPUT`, and the union oracle silently degraded to
**Konclude-only**. Konclude under-reports, so MISSED is then understated with no error emitted
anywhere. Check `oracle_source` before trusting a net: a healthy union run reads
`both / konclude / hermit`, not `konclude` for everything.

### 4d. Kobayashi-MaRust (KM) — a third voice, NOT an oracle

KM ships as Linux ELF (`bin/km-v0232-44d86fa/km`), so it needs a Linux box; point
`KM_BIN_DIR` at the directory containing `km`. Invocation is
`km classify --route production_all` — the route is a CLI flag, and `production_all`
is KM's winning bundle, not its default.

**KM IS NOT AN ORACLE.** It is measured-unsound on ~1795 ORE ontologies, and it
misses: on `ore_ont_6951` it reports `unsat=0`, siding with rustdl against Konclude
AND HermiT, which both say 2. Never let it into a union oracle.

**What it IS good for: a second peer where HermiT dies.** HermiT returned
`NO_OUTPUT` on `ore_ont_16321` / `ore_ont_4198`, so the union oracle silently
degraded to Konclude-only for 82 of 89 corpus-wide missed-unsat classes. KM
supplied the missing independent voice and confirmed both ontologies are
inconsistent — turning a single-peer claim into a corroborated one.

Two corrections to the older notes, measured 2026-08-30 on a 17 GB Linux host:
* **KM classifies `pizza` fine here** (479 subsumptions, 2 unsat, rc=0) — in all
  four combinations of {v0.2.11, v0.2.32} x {`--route production_all`, default}, so
  it is neither a version nor a route effect. The "cannot even classify pizza" note
  describes the ORIGINAL host. **It completes but is incomplete**: 479 vs the
  Konclude==HermiT oracle's **499**, **FP=0, MISSED=20** — precisely the 20
  `X ⊑ InterestingPizza` rows — where rustdl scores **499 / FP=0 / MISSED=0**.
  Score with unsatisfiable classes excluded on both sides (`aligned_closures` does);
  omitting that inflated this to 503/MISSED=4 on a first pass, all four of the phantom
  "misses" being rows about the two already-reported unsat classes.
  The uncapped 237 GB / OOM result was not retested and stands.
* The 20 GB `ulimit -v` cap is still mandatory, and with 17 GB of RAM run **at most
  3 KM processes in parallel**, not 6.

Coverage on the 424-ontology release population, 60 s cap: rustdl v0.4.24
**415 classified / 9 DNF**; KM v0.2.32 **361 / 60 / 3 err_reject**. 356 both;
rustdl completes 59 KM cannot; KM completes 5 rustdl cannot, and those 5 are
rustdl's known tail (`11085`, `1508`, `5368`, `7204`, `7828`).

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

### The actual JSONL schema (verified on a real run, not from memory)

Header record: `kind=header`, `reasoner`, `sha256`, `version`, `marker_checked`, `args_template`,
`threads`, `cap_secs`, `corpus`, `n_candidates`, `host_cores`, `only_requested`, `only_resolved`,
`digest_strip_comments`.

Per-ontology record:

```json
{"kind":"case","ont":"ore_ont_10009","outcome":"ok","wall_s":0.18,
 "peak_rss_kb":9456,"bytes":95858,"skip_reason":null,"out_sha256":null,"out_lines":null}
```

So the field names are **`wall_s`** and **`peak_rss_kb`** — seconds and kilobytes.

> **`out_sha256` is `null` here, and that is the documented trap, live.** The release process records
> that a first comparison pass diffed `out_sha256`, reported "0 differences", and was in fact
> comparing `None != None` for every case in both arms — because the wrapper redirects stdout — while
> 50 ontologies had genuinely changed output, one by 978,892 rows. **Verify a field is populated
> before comparing on it.** Compare answers by re-reading the reasoner's own `--json`, not this
> field.

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
