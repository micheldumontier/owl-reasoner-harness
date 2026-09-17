# Six-reasoner pilot: 24 ORE ontologies, one contract (2026-09-17)

First end-to-end run of rustdl, KM, Konclude, HermiT, ELK and FaCT++/JFact through one
harness under one contract. The point was to test the *design* — contract-as-data,
four-valued outcomes, adjudication against a gold signature — not to rank anything.
24 ontologies is a pilot, not a population.

## Contract

```
cap_secs   30      threads 1
mem_bytes  UNENFORCED   <- macOS has no RLIMIT_AS; `ulimit -v` is a no-op here
host       Darwin arm64, 1 thread pinned
slice      seeded stratified (seed 20260917), 4 size strata x 6
```

**The memory limit could not be enforced, and that is recorded rather than glossed.**
Memory demonstrably changes answers (KM: pizza 479 at 20 GB vs 474 at 48 GB), so a
contract must declare which hosts can enforce it. Neither available host can carry all
six *and* the full contract: g1 has no JVM at all, so HermiT/ELK/JFact cannot run
there; this Mac has all six but no `RLIMIT_AS`.

## Outcomes

| reasoner | answered | timeout | failed |
|---|---:|---:|---:|
| Konclude | 23 | 1 | 0 |
| ELK | 23 | 1 | 0 |
| KM v1.3.0 | 22 | 1 | 1 |
| rustdl 0.4.28 | 19 | 5 | 0 |
| HermiT | 19 | 4 | 1 |
| FaCT++/JFact | 18 | 6 | 0 |

## Correctness, over the gold set only

Gold = **agreement of Konclude, HermiT and JFact**. Where they disagree the ontology is
EXCLUDED, never resolved by majority: a contested oracle is not an oracle. Of 24, gold
was established on **16**, 4 contested, 4 with no reference answer.

| reasoner | MATCH | DIFF | partial | no answer | FP | MISSED |
|---|---:|---:|---:|---:|---:|---:|
| Konclude | 16 | 0 | 0 | 0 | 0 | 0 |
| HermiT | 16 | 0 | 0 | 0 | 0 | 0 |
| **rustdl** | **15** | **0** | 0 | 1 | **0** | **0** |
| KM | 14 | 0 | 2 | 0 | 0 | 776 |
| ELK | 14 | 0 | 2 | 0 | 0 | 55 |
| JFact | 13 | 0 | 0 | 3 | 0 | 0 |

`partial` = a sound SUBSET of gold (FP=0, MISSED>0) — a lower bound, not a wrong
answer. `DIFF` = emitted at least one pair gold does not contain.

**Nobody produced a DIFF, and FP is 0 for all six.** On this slice every reasoner was
sound; they differ only in how much they derive and how often they finish. **rustdl
matched gold on every ontology it completed** — its cost here is the 5 timeouts at
30 s, not correctness.


## Performance: wall and peak RSS

Over the **16** ontologies all six answered. Startup floor is min-of-5 on a trivial
2-class ontology; `net` subtracts it.

| reasoner | median wall | median RSS | max RSS | floor RSS | net RSS |
|---|---:|---:|---:|---:|---:|
| rustdl | **0.050 s** | 49 MB | 447 MB | 6 MB | 43 MB |
| KM | 0.070 s | **35 MB** | 200 MB | 3 MB | 32 MB |
| Konclude | 0.140 s | 56 MB | 221 MB | 28 MB | 28 MB |
| ELK | 0.710 s | 178 MB | 475 MB | 159 MB | **19 MB** |
| JFact | 1.320 s | 360 MB | 1,626 MB | 122 MB | 238 MB |
| HermiT | 1.360 s | 253 MB | 2,656 MB | 120 MB | 133 MB |

**Subtracting the floor reverses the memory ranking.** ELK looks like the second
heaviest reasoner at 178 MB median and is in fact the *lightest* — **19 MB** of actual
work, 89% of its footprint being the JVM. Reported raw, a memory table measures the
runtime and calls it the reasoner. The three JVM reasoners cost **120–159 MB** and
**0.26–0.37 s** before any reasoning happens, against rustdl's 6 MB / 0.00 s and KM's
3 MB / 0.02 s.

**Tails are where the memory is.** Medians span 35–360 MB but maxima span 200 MB to
**2.7 GB** (HermiT on `ore_ont_1422`, 10x its own median; JFact 1.6 GB on
`ore_ont_15013`, 4x). A median-only memory claim would miss the entire problem.

### Two measurement caveats, both found the hard way

**Cold cache moves the medians, by up to 3.7x.** Two runs of the identical binaries
over the identical slice gave different wall medians — KM 0.262 s then 0.070 s, ELK
1.152 s then 0.710 s, rustdl 0.131 s then 0.050 s — because the first run was the first
touch of each ontology file. The same effect made a single-shot Konclude startup
measurement read **1.07 s** against its true **0.06 s** (stable 5/5), a ~100 MB static
binary paying page-cache cost once. **Warm the cache or interleave arms; a first run is
not a measurement.** This is the same hazard already recorded for a fixed arm order
buying a ~3.4% phantom.

**RSS is meaningless without the thread pin, measured at 1.9x here.** `ore_ont_2182`
reads 87,104 kB at `RAYON_NUM_THREADS=1` and 165,664 kB unpinned — same binary, same
input. Every figure above is at 1 thread.

## The finding that nearly became a false headline

The first adjudication scored **5 of 20** ontologies as oracle-contested, including
`ore_ont_7455` where Konclude and HermiT appeared to differ by **59,694 pairs**. That
would have been a striking methodological claim: the two canonical oracles disagreeing
at scale.

It was the **⊤ convention**. The ontology asserts `SubClassOf(owl:Thing, X)` twice, so
every class is trivially a subclass of both; HermiT emits those rows and Konclude does
not. The tell is the arithmetic — the hermit-only pairs are exactly **2 per subject
across 29,847 subjects** = 59,694, i.e. 2 extra superclasses each, matching the 2
asserted `⊤ ⊑ X` axioms.

Excluding ⊤-implied rows symmetrically (the mirror of excluding unsatisfiable classes,
which subsume everything from the other end) moves `ore_ont_7455` into the gold set with
Konclude and HermiT agreeing **exactly**, and takes contested from 5 to 4.

**Corrected headline: Konclude and HermiT agree on every ontology where both answered.**
All four remaining disputes involve JFact — in three it is short against a
Konclude=HermiT consensus (`13621` by 3 pairs, `15152` by 261), and `15753` is a 2-way
where Konclude reports nothing and JFact 124.

This project has been bitten by the ⊤ convention before — 73% of an apparent ~1,795-row
gap against another reasoner. **It must be in the normalisation contract, not left to
whoever writes the next comparison.**

## What the pilot says about the design

* **Four-valued outcomes earn their place immediately.** ELK answers 23/24 and matches
  gold on 14 with FP=0 — it is not a weak reasoner here, it is a *sound partial* one.
  A three-valued scheme would have to call its 2 partials either correct or wrong, and
  both are false.
* **"Answered" is not "correct", measurably.** KM answers 22/24 and is short by 776
  entailments; Konclude answers 23 and is short by none. Ranking on completion counts
  would order these two the wrong way round.
* **The contract must record what it could not enforce.** See the memory note above.
* A JSONL that can end mid-record after a killed run needs a tolerant reader; three of
  the six files carried a truncated final line.

---

# Re-run with interleaving, repeats and the timing fix (2026-09-17, second pass)

Five instrument fixes, then 24 ontologies x 7 arms x 3 repeats, arm order rotated per
pass, after a page-cache warm-up. `rustdlx` is rustdl at `--pair-timeout-ms 0
--global-timeout-ms 0`, carried as its own arm because rustdl's SHIPPED default has a
5 ms per-pair budget the other five reasoners do not have.

| arm | ans | t/o | decl | fail | inc | MATCH | part | DIFF | n/a | FP | MISSED | medW | maxW | medR | netR | maxR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rustdl | 19 | 5 | 0 | 0 | 1 | 16 | 0 | 0 | 1 | 0 | 0 | 0.022 | 0.87 | 16 | 10 | 447 |
| rustdlx | 18 | 6 | 0 | 0 | 0 | 15 | 0 | 0 | 2 | 0 | 0 | 0.022 | 0.98 | 16 | 10 | 448 |
| KM | 22 | 1 | 1 | 0 | 0 | 15 | 2 | 0 | 0 | 0 | 776 | 0.092 | 0.97 | 12 | 9 | 194 |
| Konclude | 23 | 1 | 0 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 0.092 | 0.61 | 39 | 11 | 222 |
| HermiT | 19 | 4 | 1 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 0.677 | 21.71 | 252 | 132 | 2430 |
| JFact | 18 | 6 | 0 | 0 | 0 | 14 | 0 | 0 | 3 | 0 | 0 | 0.889 | 10.28 | 312 | 190 | 1607 |
| ELK | 23 | 1 | 0 | 0 | 0 | 15 | 2 | 0 | 0 | 0 | 55 | 0.596 | 2.16 | 182 | 23 | 517 |

## `fail` is now zero everywhere

Both cells previously reported as failures were honest refusals of SWRL — KM's
`unsupported: DL-safe rules`, HermiT's `built-in atoms are not supported yet`. They are
`decl` now. The four-valued outcome was argued for on principle and is carried here by
exactly two cells; the mechanism is verified, its frequency is not.

`inc` is readable only because stderr is now captured, and shows that **rustdl is the
only one of the six that reports its own incompleteness at all**. A blank in that column
means "no such signal exists", not "complete".

## rustdl's shipped budget strictly dominates its exhaustive setting

`rustdlx` answers one FEWER ontology (loses `ore_ont_2182` to the cap) for identical
correctness — FP=0, MISSED=0 both ways. The 5 ms per-pair budget costs nothing on this
slice and buys a completion.

## THE WALL NUMBERS ARE NOT ALL COMPARABLE, AND THE PATTERN IS NOT THE OBVIOUS ONE

Spread across the three repeats, median over common-solved:

| rustdl | Konclude | rustdlx | ELK | JFact | HermiT | **KM** |
|---:|---:|---:|---:|---:|---:|---:|
| 5.9% | 5.4% | 21.0% | 35.8% | 42.5% | 43.7% | **65.8%** |

The expected story was "native reasoners stable, JVM reasoners jittery from JIT and GC".
**That is wrong: KM is native and is the LEAST stable arm of the seven.** Only rustdl and
Konclude are stable to ~5%.

Consequence: `medW` for KM, HermiT, JFact and ELK carries a +-35-66% error bar, so
**KM 0.092 vs Konclude 0.092 is not a tie** — one is solid, the other could be 0.05 or
0.15. Only differences of roughly 2x or more are claimable for four of the seven arms.

**The number that would have falsified the story was the one that went missing.** The
first version of this table printed KM's spread as `n/a` — a transient read of a
still-flushing JSONL — and the tidy native/JVM split was nearly published on that basis.

## Instrument fixes this pass required

1. **Wall came from `time`, which reports hundredths of a second.** A 20 ms reasoner was
   measured in two ticks, so one tick of jitter is 50% error; the distinct wall values
   were literally {0.01, 0.02, 0.03, ...}. A reported "0.0% spread" for rustdl and KM was
   quantization mistaken for stability. Wall now comes from the nanosecond `Instant`
   already spanning the same invocation; RSS still from `time`, its only source.
2. **Fixed arm order and a single run per cell.** Now 3 repeats with rotated order.
3. **Cold page cache**, worth up to 3.7x on medians. Now a warm-up pass.
4. **stderr discarded**, which is where incompleteness is reported. Now captured.
5. **`declined` pooled with failure.** Now its own outcome.

## Still not supported by these numbers

Memory is UNENFORCED on this host, so `maxR` is what the reasoners chose to use, not what
they would do under a limit. `netR` for the JVM three subtracts a constant floor measured
on a 2-class ontology and is approximate. `maxW`/`maxR` are single observations at n=24.

## Why KM's spread is 65.8%: arm ADJACENCY, not arm order

Run back-to-back on an otherwise idle machine KM is stable and deterministic — 5.5% /
5.6% / 9.0% spread on three ontologies, with a single distinct output hash across six
repeats. So the 65.8% is not KM being nondeterministic.

Nor is it host contention, and the control that rules that out is in the table itself:
**rustdl ran in the same three passes and is stable to under 3%** (0.018 / 0.020 / 0.019
where KM gives 0.058 / 0.104 / 0.093 on the same ontology). Whatever moves KM does not
move rustdl.

It is what ran IMMEDIATELY BEFORE. KM preceded by a 2.4 GB JVM run, five times, against
KM alone five times: medians 0.073 s vs 0.062 s (1.19x), but the distribution is bimodal
— **2 of 5 post-JVM runs are ~2x slower** (0.109, 0.119 against a 0.048-0.067 baseline).
An intermittent ~2x penalty is exactly what produces a 65.8% median spread over three
samples.

**Rotating arm order does not fix this; it redistributes it.** Rotation balances which
arm runs FIRST, but each arm still has a different NEIGHBOUR on every pass, and for a
memory-sensitive reasoner the neighbour is what matters. Over three passes that is three
samples of a bimodal distribution.

What actually works, in order of cost: run each arm on an idle host with nothing else
resident; or many more repeats and report the distribution rather than a median; or
accept that only differences above the measured spread are claimable — which is what
this document does.

**rustdl and Konclude are measurable at 3 repeats. KM, HermiT, JFact and ELK are not.**
