# owl-reasoner-harness

Measure OWL reasoners over a corpus so the numbers mean something — and so somebody
else can get the same ones.

Drives **rustdl**, **Kobayashi-MaRust**, **HermiT**, **Konclude**, **ELK** and
**FaCT++/JFact** through one interface, under one declared resource contract, and
scores correctness against a gold signature rather than against exit codes.

## Quickstart

```sh
git clone https://github.com/micheldumontier/owl-reasoner-harness
cd owl-reasoner-harness
cargo build --release
./setup.sh                    # fetch the pinned reasoners for YOUR platform
./setup.sh --check            # report only; --force re-fetches

./target/release/owl-reasoner-harness run \
  --corpus /path/to/ontologies \
  --reasoner wrappers/run-konclude.sh --args '{}' \
  --cap-secs 240 --threads 1 --mem-mb 9216 \
  --out run.jsonl
```

One JSONL record per ontology, plus a header pinning the binary sha256, the cap, the
thread pin and the corpus. `setup.sh` needs no root and installs nothing system-wide.

`setup.sh` reads **`reasoners.lock`** — one row per artifact per platform, each with a
sha256 that is **verified after download**; a mismatch aborts rather than proceeding,
since the point of pinning is knowing which binary produced a number. It fetches
rustdl, Kobayashi-MaRust, Konclude, robot.jar (HermiT + ELK + FaCT++/JFact) and a JDK,
needs no root, and redistributes nothing — `vendor/` is gitignored.

**You supply the corpus** — any directory of `.owl`/`.ofn` files. Not every reasoner
publishes a build for every platform; `./setup.sh --check` says which rows apply to
your host and what is left for you to provide. To measure your own build of a reasoner
rather than the pinned one, point the corresponding wrapper at it (for rustdl,
`export MISSED_NET_RUSTDL=/path/to/rustdl`).

Changing a pin changes your results — a different `robot.jar` bundles different
HermiT/ELK/JFact versions. Bump a row deliberately and re-baseline anything you cite.

## Why it is shaped this way

Every rule below exists because its absence produced a wrong number that was nearly
published.

**Outcome comes from the child's exit status, never from parsing its output.** A
reasoner can exit 0 having printed nothing.

**A wrapper must not end in a pipe.** A pipeline returns the *last* command's status,
so `reasoner | tee out` reports `tee`'s success and a crashed reasoner is recorded as
`ok`. Wrappers use `set -o pipefail`, and must invoke it through `bash` — `dash`
rejects `pipefail` and would fail every case instead.

**Four outcomes, not three.** `answered` / `timeout` / **`declined`** / `failed`. A
reasoner refusing a construct it never claimed to support (SWRL, an inverse role in a
chain) is behaving correctly; pooling that with crashes reports honesty as failure.

**"Answered" is not "correct".** A reasoner can exit 0 with a partial answer, so
ranking on completion counts can order two reasoners the opposite way from ranking on
entailments found. Correctness is adjudicated separately, against the agreement of
independent reasoners, with contested ontologies *excluded* rather than resolved by
majority — a contested oracle is not an oracle.

**Compare normalised closures, never raw rows.** Expand equivalence groups, filter
internal definers, and exclude both unsatisfiable classes and `⊤`-implied rows on all
sides. Reasoners differ on whether to emit rows implied by an asserted `⊤ ⊑ C`; on an
ontology with such an axiom, comparing raw output can make two reasoners that agree
exactly appear to differ by tens of thousands of pairs.

**The resource contract is part of the answer.** A reasoner's output can differ under
different resource limits — deterministically, with both runs exiting 0 — so two sites
running one binary on one file under different caps can get different closures,
silently. The contract is therefore recorded with every run, and where a platform
cannot enforce it the run says so instead of implying it held.

## Reading the results

| field | meaning |
|---|---|
| `outcome` | `ok` / `dnf` / `declined` / `err_reject` / `err_crash` / `skipped` |
| `wall_s` | measured by the harness itself — `time` reports only hundredths, which for a 20 ms reasoner is two ticks |
| `peak_rss_kb` | from GNU `time` or BSD `time -l`; **null** where neither exists, rather than fabricated |
| `out_sha256` | digest of the reasoner's output, for answer-identity comparison |

```sh
python3 scripts/normalise.py normalise --format <rustdl|konclude|hermit|km> FILE --ontology SRC
python3 scripts/normalise.py compare   candidate.tsv oracle.tsv     # FP / MISSED
python3 scripts/normalise.py selftest                               # invariants
```
`--format hermit` also reads ELK and FaCT++ output, which `java/ReasonerCli` emits in
the same shape. `.gz` is read transparently: taxonomy output compresses ~18x and a
full 1,920 x 7-arm run is ~35 GB raw against ~2 GB compressed, so compress after each
arm (`scripts/compress-run-output.sh`) — never by piping the reasoner through gzip.

## Things that will bite you

* **Konclude's Linux static build needs `libpcre.so.3`** (PCRE1). Install the real
  `libpcre3`; do **not** symlink PCRE2 — an ABI mismatch could corrupt oracle output,
  which is worse than no oracle.
* **`--mem-mb` caps ADDRESS SPACE, not memory used, and that distinction is not
  cosmetic.** It is implemented with `ulimit -v` (`RLIMIT_AS`), which bounds what a
  process *reserves*. Reservations track real use closely for a single-threaded native
  reasoner and barely at all for a threaded one: every thread stack is a reservation,
  and a runtime may reserve a heap or class space far larger than it commits. A
  reasoner using tens of megabytes of RSS can therefore be refused by a multi-gigabyte
  cap, and the failure surfaces as a spawn error or an allocation abort rather than
  anything resembling "out of memory".

  Consequences to design around, not work around:
  - **A threaded reasoner is penalised relative to a single-threaded one** under the
    same cap, for reasons unrelated to how much memory either uses.
  - **The JVM wrappers compensate explicitly** — `-Xmx` is sized from the cap (a fixed
    ~2 GiB of reservations, so the share grows as the cap does),
    `-XX:CompressedClassSpaceSize` is trimmed from its 1 GiB default, and
    `-XX:ActiveProcessorCount` is pinned to the harness thread count. Without the last
    of these, GC thread stacks exhaust the address space and the JVM fails to start
    intermittently, **silently, with no error text**.
  - **Prefer a cgroup memory limit if your host offers one**, since that bounds actual
    usage. `RLIMIT_RSS` is not an option — Linux ignores it — and `systemd-run --user`
    needs a session bus that many containers lack.
  - If a cap is small enough to matter, check that a rejection is real before reporting
    it: compare the recorded `peak_rss_kb` against the cap, and look at the captured
    stderr.
* **`--mem-mb` is a no-op on macOS**, which has no `RLIMIT_AS`; such a run records
  memory as unenforced rather than implying the cap held.
* **Wall from a parallel run is not reportable.** Contention manufactures false
  timeouts, and a reasoner's wall can shift substantially depending on which arm ran
  immediately before it — rotating arm order does not fix this, since each arm still
  gets a different neighbour on every pass. Run correctness in parallel and timing
  sequentially on an idle host.
* **`robot.jar` versions bundle different reasoner versions.** Compare the sha256
  across hosts, never the filename.

## Layout

```
src/            runner, reporter, comparator
wrappers/       one per reasoner; env-overridable, defaulting to ./vendor
java/           ReasonerCli — OWLAPI driver for HermiT, ELK, FaCT++/JFact
scripts/        normalise.py (the one to read), plus historical one-offs that
                still carry absolute paths from the machine they were written on
docs/           setup notes and benchmark write-ups, including what was retracted
baselines/      reference runs whose numbers are cited elsewhere
bin/            pinned reference binaries -- ELF x86-64 ONLY, see below
vendor/         fetched by ./setup.sh, gitignored, not redistributed
```

**`bin/` is legacy and Linux x86-64 only.** It holds ~23 historical rustdl builds
(~1 GB) from before `reasoners.lock` existed; a clone on macOS or ARM cannot execute
them. Nothing in the documented workflow needs it — `setup.sh` fetches a verified
binary for your platform instead.

## Licence

MIT OR Apache-2.0.
