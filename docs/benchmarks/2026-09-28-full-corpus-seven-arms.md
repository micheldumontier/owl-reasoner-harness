# Full ORE corpus, seven arms: the oracle was the thing that was wrong

**2026-09-16 → 2026-09-28.** 1,920 ORE ontologies × 7 arms, one contract, adjudicated
against a gold signature. The headline is not the per-arm scores. It is that the
reference reasoners used to build the gold set were **incomplete on nearly every
disputed case that was checked** — which changes how a cross-reasoner comparison
should be adjudicated at all.

## Contract

```
cap 240s · threads 1 · mem 10240 MB (ulimit -v) · 6 parallel workers
host: 16 vCPU AMD EPYC 7402 (cgroup slice), 64 GiB
corpus: ORE-2015 pool, 1,920 ontologies, verified identical to the reference host
        by a full name+size manifest
```

Binaries sha-pinned in the run's `contract.txt`. `km140` ran with **no memory cap** —
see *The memory contract measured the wrong thing* — and is therefore its own contract
row, not comparable to the rest.

## Outcomes

| arm | answered | timeout | declined | failed |
|---|---:|---:|---:|---:|
| ELK | 1912 | 8 | 0 | **0** |
| Konclude | 1897 | 17 | 0 | 6 |
| KM v1.4.0 *(uncapped)* | 1804 | 45 | 10 | 61 |
| rustdl 0.4.28 | 1781 | 113 | 0 | 26 |
| KM v1.3.0 | 1769 | 65 | 10 | 76 |
| HermiT | 1747 | 157 | 7 | 9 |
| FaCT++/JFact | 1442 | 444 | 0 | 34 |

`declined` is a reasoner refusing a construct it never claimed to support (SWRL, an
inverse role in a chain). It is sound behaviour and is deliberately not pooled with
failures.

## Correctness

Gold = ontologies where Konclude and HermiT both answered and produced the **same**
normalised closure; where they disagree the ontology is excluded rather than resolved
by majority. Closures compared with equivalence groups expanded, internal definers
filtered, and unsatisfiable classes and `⊤`-implied rows excluded on all sides.

gold **1671** · contested **15** · no-reference 225 · oversized 9

| arm | MATCH | partial | DIFF | n/a |
|---|---:|---:|---:|---:|
| Konclude | 1671 | 0 | 0 | 0 |
| HermiT | 1671 | 0 | 0 | 0 |
| KM v1.4.0 | 1599 | 97 | 25 | 0 |
| KM v1.3.0 | 1573 | 51 | 26 | 71 |
| rustdl | 1529 | 187 | **1** | 4 |
| ELK | 1357 | 331 | 33 | 0 |
| JFact | 1280 | 91 | 17 | 333 |

`partial` = a sound SUBSET of gold: a lower bound, not a wrong answer. Konclude and
HermiT scoring 1671/1671 is **definitional, not a result** — they are the gold.

## THE FINDING: agreement-based gold does not work here

Every `DIFF` that was investigated turned out to be the **gold** being wrong, with one
exception.

**Konclude omits whole classes.** On `ore_ont_14861`, its normalised output contains
**zero** pairs mentioning `GO_0006948`, while KM has 12. The class is declared, has an
asserted superclass, and a per-pair query proves the disputed subsumptions hold. KM was
scored with 1,440 false positives **for being more complete**.

**HermiT inherits the omissions.** Konclude and HermiT agree on 1671 of 1686 adjudicable
ontologies (99.1%), so where both omit the same entailments the ontology is never
flagged contested — it is silently accepted as gold. Excluding contested ontologies
protects against *disagreement*, not against a *shared blind spot*.

**A majority vote would not fix it.** On `ore_ont_14861` Konclude, HermiT **and
rustdl's classify** all report 2802 pairs while KM reports 5690; the omission is
correlated across engines. Only a per-pair prover settles it.

**Verified by independent entailment**, sampling disputed pairs and proving them
directly: **15 of 20 confirmed entailed** — KM 10/10, ELK 5/5 — i.e. the arms were
right and the gold was short.

### Where Konclude and HermiT do disagree, Konclude is usually the outlier

Of the 15 contested ontologies, a third and fourth reasoner side **against Konclude 8
times and against HermiT once**. In four of those eight Konclude reports **zero**
subsumptions where the others find 10 to 168.

| ontology | Konclude | HermiT | KM | rustdl | ELK |
|---|---:|---:|---:|---:|---:|
| 15063 | **0** | 168 | 168 | 168 | 168 |
| 2526 | **0** | 82 | 82 | 82 | 78 |
| 7345 | **0** | 10 | 10 | 10 | 10 |
| 13035 | **511** | 731 | 731 | 731 | 731 |
| 762 | 504224 | **25455** | 504224 | 504224 | 504224 |

**Consequence for anyone building a gold standard from Konclude alone** — which is
KM's published methodology — the reference is demonstrably incomplete.

## The one confirmed soundness defect

**FaCT++/JFact derives unentailed subsumptions on `ore_ont_15655`.** 3 of 3 sampled
disputed pairs are *not* entailed, established with HermiT (complete for SROIQ) on a
probe ontology, against controls run **on that same ontology**: the base has 0
unsatisfiable classes, two known-entailed gold pairs swell the `owl:Nothing` group to
all 1,594 classes, and the JFact pairs leave it at 0.

That is the only confirmed unsound inference across 7 arms and 1,920 ontologies. JFact
has 17 `DIFF` ontologies, 9 of them missed inconsistencies, so at most 8 are affected;
one was verified.

## ELK's deviations are a profile limit, not unsoundness

**29 of ELK's 33 DIFFs are missed inconsistencies.** On those ontologies Konclude and
HermiT both derive inconsistency — so gold is correctly empty — while ELK reports a
full taxonomy, because the contradiction lives outside the EL profile. Correct
behaviour for a profile reasoner, and the same story as its 331 sound partials.

Reported raw, that is 60,090 "false positives" for an arm that is behaving exactly as
specified. **A results table needs to separate: genuinely unentailed pairs; pairs the
gold is missing; and an entire taxonomy emitted because inconsistency was not
detected.** Only the first is a defect.

## The memory contract measured the wrong thing

`--mem-mb` uses `ulimit -v` (`RLIMIT_AS`), which bounds what a process **reserves**, not
what it uses. Reservations track real use for a single-threaded native reasoner and
barely at all for a threaded one.

**KM v1.4.0 was refused on an ontology where it uses 37 MB of RSS**, because its
hypertableau workers could not reserve thread stacks under a 10 GiB cap: `spawn HT
phase-1 worker: Resource temporarily unavailable`. **232 of its 302 failures were this
artifact.** Re-run uncapped it answered 243 more ontologies.

The same mechanism costs the JVM arms a fixed ~2 GiB of heap and, unpinned, lets GC
thread stacks exhaust the address space — ELK failed to start 1 run in 5, silently.

**A memory contract needs cgroups.** `RLIMIT_RSS` is ignored by Linux and
`systemd-run --user` needs a session bus many containers lack.

This also reframes an earlier observation that KM returns 479 subsumptions under a
20 GB cap and 474 under 48 GB. That was read as "more memory, smaller closure" and
called unexplained. The likely mechanism is now obvious: a tighter address-space cap
changes how many threads KM can spawn, which changes its search. Not a memory effect —
a concurrency effect the cap was incidentally controlling. Untested, and flagged as a
hypothesis.

## Platform portability

**KM builds and runs natively on Apple Silicon**: pure Rust, no arch-gated code, and it
returns **474 on pizza — identical to the Linux x86_64 result uncapped**.

**Konclude compiles for arm64 but does not work.** 5,288 sources build clean with no
x86 intrinsics, and the binary then **hangs during precomputing on a three-class
ontology** that the x86 build classifies in 0.16 s. It is the "Uni Ulm Parallel
Reasoner", and code synchronised correctly under x86's strong memory ordering can
deadlock under ARM's weak ordering. Konclude on Apple Silicon needs Rosetta 2 — fine
for correctness, not comparable for timing.

## What this run does NOT establish

**No timing data.** Everything here ran in parallel, and parallel wall is not
reportable: an intermittent 2× penalty was measured on one reasoner from nothing but
which arm ran immediately before it, and rotating arm order redistributes that rather
than removing it. A defensible timing pass must be sequential on an idle host.

**The DIFF investigation was sampled, not exhaustive.** ELK's remaining 4, JFact's
other 8 and KM's ~24 are unexamined.

**`MISSED` is dominated by configuration, not capability.** rustdl's 11.8M sits almost
entirely in 187 partials produced by its shipped 5 ms per-pair budget truncating on
large ontologies. Its exhaustive arm exists for exactly this and was not run at corpus
scale.

## Method notes that cost something to learn

**Verify the fix is on the machine you are running.** Three consecutive restarts tested
code that was not there: `git pull -q` had been failing silently for hours because
files had been `scp`'d into the same checkout, leaving it dirty. A `grep -c` for a
marker takes two seconds.

**`ast.parse` is not a syntax check.** It parses but does not resolve bindings, so a
`nonlocal` with no binding passed it and the run exited instantly, writing nothing —
indistinguishable from the OOM stalls it had been written to prevent. Use `compile()`,
or import the module.

**An instrument must be shown to discriminate in BOTH directions, on the ontology being
tested.** The first inconsistency criterion grepped for `owl:Nothing` anywhere — but a
*consistent* ontology with unsatisfiable classes emits that group too (47 of 27,899 on
one input). It returned "inconsistent" for everything including its own negative
control, and was caught only because two supposedly identical verdicts had different
output sizes.

**Checkpoint anything long.** Scoring crashed four times, each on a different
pathological ontology, each `BrokenProcessPool` discarding every in-flight result.
Per-ontology checkpointing turned those from full restarts into minutes.

**An exit code is not an answer.** Inconsistency was reported by OWLAPI as a thrown
exception, so 139 correct verdicts across three arms were recorded as failures —
including every one of ELK's 22. Konclude separately exits 0 on an input it cannot
parse, writing an empty result.
