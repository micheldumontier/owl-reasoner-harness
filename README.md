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
./setup.sh                    # fetches a JDK, robot.jar and Konclude into ./vendor
./setup.sh --check            # what is present, what you must supply

./target/release/owl-reasoner-harness run \
  --corpus /path/to/ontologies \
  --reasoner wrappers/run-konclude.sh --args '{}' \
  --cap-secs 240 --threads 1 --mem-mb 9216 \
  --out run.jsonl
```

One JSONL record per ontology, plus a header pinning the binary sha256, the cap, the
thread pin and the corpus. `setup.sh` needs no root and installs nothing system-wide.

**You supply**: the corpus (any directory of `.owl`/`.ofn`), a
[rustdl](https://github.com/MaastrichtU-IDS/rustdl) build if you want that arm
(`export MISSED_NET_RUSTDL=/path/to/rustdl`), and a KM binary if you have one.
Everything else `setup.sh` fetches.

## Why it is shaped this way

Every rule below exists because its absence produced a wrong number that was nearly
published.

**Outcome comes from the child's exit status, never from parsing its output.** A
reasoner can exit 0 having printed nothing.

**A wrapper must not end in a pipe.** A pipeline returns the *last* command's status,
so `reasoner | tee out` reports `tee`'s success. That masked **22 KM failures as `ok`**
until the wrappers gained `set -o pipefail` — and it must be `bash`, since `dash`
rejects `pipefail` and would fail every case instead.

**Four outcomes, not three.** `answered` / `timeout` / **`declined`** / `failed`. A
reasoner refusing a construct it never claimed to support (SWRL, an inverse role in a
chain) is behaving correctly; pooling that with crashes reports honesty as failure.

**"Answered" is not "correct".** In one pilot KM answered 22 of 24 ontologies and was
short 776 entailments while Konclude answered 23 and was short none. Ranking on
completion counts orders those two backwards. Correctness is adjudicated separately,
against the agreement of independent reasoners, with contested ontologies *excluded*
rather than resolved by majority — a contested oracle is not an oracle.

**Compare normalised closures, never raw rows.** Expand equivalence groups, filter
internal definers (`Q_*`, `DKey`), and exclude both unsatisfiable classes and
`⊤`-implied rows on all sides. Skipping the last one made two reasoners that agree
exactly look like they differed by **59,694 pairs**.

**The resource contract is part of the answer.** KM returns 479 subsumptions under a
20 GB cap and 474 under 48 GB — deterministic, both exiting 0. Two labs running one
binary on one file under different limits get different closures, silently. So the
contract is recorded, and where a platform cannot enforce it the run says so instead
of implying it held.

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
* **`ulimit -v` caps address space, and the JVM reserves its whole heap up front.**
  `-Xmx12g` under a 9 GiB cap does not spill, it refuses to boot. The JVM wrappers
  size `-Xmx` from the cap and pin `-XX:ActiveProcessorCount` to the same thread
  count as the native reasoners; without the latter, GC threads exhausted the address
  space and ELK failed ~1 run in 5 **silently, with no error text**.
  Consequence: under one cap a native reasoner gets nearly all of it and a JVM
  reasoner about half. That asymmetry is real and must be stated, not averaged away.
* **`--mem-mb` is a no-op on macOS**, which has no `RLIMIT_AS`.
* **Wall from a parallel run is not reportable.** Contention manufactures false
  timeouts, and an intermittent 2x penalty was measured on one reasoner from nothing
  but which arm ran immediately before it. Run correctness in parallel and timing
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

**`bin/` is Linux x86-64 only.** It holds ~23 pinned rustdl builds (~1 GB) that the
sha-pinning reproducibility model relies on, but they are ELF binaries and a clone on
macOS or ARM cannot execute them -- a macOS KM build committed here failed on Linux
with `Exec format error`, which is the same hazard in the other direction. Build or
fetch reasoners for your own platform; `setup.sh` does that for the ones it can.

## Licence

MIT OR Apache-2.0.
