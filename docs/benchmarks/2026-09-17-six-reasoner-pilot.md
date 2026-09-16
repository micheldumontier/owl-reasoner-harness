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
