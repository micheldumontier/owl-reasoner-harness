# Provisioned reasoners (2026-07-31)

Uniform wrappers in `/data/dumontier/reasoners/` so the harness can drive every reasoner
through the same `--reasoner <path> --args '{}'` interface. Each wrapper's header records
the overhead that must be stated when its walls are compared.

| reasoner | version | invocation | overhead floor | bibtex smoke |
|---|---|---|---|---|
| **Konclude** | v0.7.0-1138 (Jun 2021, latest release) | native static binary, reads `.ofn` | **none** | 0.09 s / 21 MB |
| **HermiT** | 1.4.3 via `obolibrary/robot:v1.9.6` | docker + OpenJDK 11 | **0.56 s** (measured, docker+JVM boot) | 2.46 s / 32 MB |
| **KM** (Kobayashi-MaRust) | `c6ced84` (161 commits pulled) | `ofn F \| kobayashi-marust` | negligible; **20 GB cap mandatory** | 0.02 s / 9 MB |

`/data/dumontier/reasoners/run-{konclude,hermit,km}.sh` — all take one ontology path.

## Notes that change how results must be read

**Konclude is the version already used as the FP=0 oracle** (the 2026-07-11 curated MATRIX
cites `konclude-0.7.0-1138`), so historical comparisons remain meaningful. It is a *native
static* binary — no container startup to subtract. This matters: a docker-based Konclude's
~1.5 s container startup previously inflated walls and produced retracted "beats Konclude"
claims.

**Konclude and HermiT both read `.ofn` directly.** The 2026-06-08 ORE harness converted
everything to OWL/XML with ROBOT first; that dependency is gone, removing a conversion step
that could itself distort timings.

**HermiT's 0.56 s floor was measured before use** (`java -version` inside the container, zero
reasoning). Its 2.03 s on pizza is therefore ~1.5 s of work against Konclude's 48 ms *total*.
An unadjusted wall comparison is meaningless at small scale.

**KM's 20 GB cap is a safety requirement, not tuning.** Run uncapped on `pizza.ofn` — a
~100-class ontology — KM reached **237 GB RSS** and was **OOM-killed after 898 s**, degrading
every other measurement running on the host at the time. Under the upstream `AGENTS.md`
config (240 s / 20 GB) it aborts cleanly at 52 s with `memory allocation of 584 bytes failed`.
Never run KM in a sweep without the cap.

> **"KM cannot classify pizza" is HOST-SPECIFIC, not a property of KM (measured
> 2026-08-30, idle 17 GB Linux box).** Under the same 20 GB `ulimit -v`, KM classifies
> `pizza.ofn` fine: **479 subsumptions, rc=0**, in all four combinations of
> {v0.2.11, v0.2.32} x {`--route production_all`, default} — so it is neither a version
> nor a route effect. The uncapped 237 GB / OOM result above was NOT retested and stands;
> the cap remains mandatory.
>
> **But completing is not the same as being right, and the failure mode inverted.** On
> this host KM returns an *incomplete* answer rather than aborting: against the pizza
> oracle (Konclude == HermiT, **499**) KM scores **479, FP=0, MISSED=20** — precisely the
> 20 `X ⊑ InterestingPizza` rows, which it reports none of. rustdl v0.4.24 scores
> **499, FP=0, MISSED=0** on the same oracle. A silent 20-entailment shortfall is
> arguably worse to build on than a visible abort.
>
> **Score with unsatisfiable classes EXCLUDED on both sides, as `aligned_closures` does.**
> A first pass of this comparison did not, and read the oracle as 503 with rustdl at
> MISSED=4. All four of those "misses" were `CheeseyVegetableTopping`/`IceCream` rows —
> the two classes both reasoners already report as unsatisfiable, and an unsat class
> subsumes everything, so the rows are trivially true and say nothing about either
> engine. Calibrate against the committed net's `pizza 499 = 499 FP=0 MISSED=0` before
> believing any number here.

**KM's output needs filtering before closure comparison.** It emits Tseitin definers in
`subsumptions`, e.g. `{"subsumptions":{"Article":["Entry","Q_1","Q_10",…]}}`. The `Q_*` entries
are internal and must be dropped, the way rustdl filters synthetic `DKey` classes via
`reportable_class_iris`. Comparing raw output would report spurious KM subsumptions.

**Output formats differ and are not directly diffable.** Konclude writes an OWL/XML class
hierarchy; HermiT writes `SubClassOf( <iri> <iri> )` lines; KM writes JSON keyed by class;
rustdl writes `direct<TAB>sub<TAB>sup`. `scripts/normalise.py` (below) reconciles them.

**`run-hermit.sh` needs an OUT argument to produce any output.** HermiT's `-c` writes to
the `-o` path and never to stdout, so the original one-arg form (`-o /dev/null`) is
timing-only. `run-hermit.sh ONT OUT` writes the taxonomy; the one-arg form is unchanged.

# The output normaliser

`scripts/normalise.py` — normalises each reasoner to a sorted set of `sub<TAB>sup` lines
over named classes, then diffs two of them for FP/MISSED. Python, not a Rust subcommand:
it reuses the shape of the 2026-06-08 `work/diff.py`, and the gate must be re-runnable
without a rebuild of the system under test.

```sh
python3 scripts/normalise.py gate                  # THE GATE: 11/11 fixtures, exact
python3 scripts/normalise.py selftest              # identity invariants (no corpus needed)
scripts/cross-check.sh                             # 4 reasoners vs the Konclude oracle
python3 scripts/normalise.py normalise --format konclude F.owx -o F.tsv
python3 scripts/normalise.py normalise --format km  F.json --ontology SRC.ofn -o F.tsv
python3 scripts/normalise.py compare CANDIDATE.tsv ORACLE.tsv
```

`compare` reports **FP** (candidate asserts, oracle lacks — soundness, must be 0) and
**MISSED** (oracle has, candidate lacks — completeness), and exits nonzero on FP.
Exclusion is symmetric: the union of both sides' unsatisfiable and Thing-equivalent
classes is removed from both closures first, so a disagreement about *satisfiability* is
reported as `unsat_disagreement` instead of masquerading as thousands of FPs. `normalise`
therefore emits its own unsat / Thing-equivalent sets as `#unsat` / `#thing-equiv` sidecar
lines, since a single-file pass cannot know the other side's.

**This is complementary to, not a replacement for, the Rust `compare`.** The Rust verb
checks answer identity by raw stdout sha256 — byte-identity, valid only for two runs of
the *same* reasoner (build A/B, flag on/off). It cannot compare across reasoners because
the bytes differ by format. Use the Rust `compare` for regression, this for cross-reasoner
FP/MISSED.

## What the normaliser decided, and why

- **Relation: transitive closure.** Determined empirically on a 3-level probe, not
  assumed: rustdl, Konclude *and* HermiT all emit the DIRECT (Hasse) relation; **KM emits
  the full closure**. Closure is the only common target (direct→closure is total;
  closure→direct presumes completeness, which is what is under test) and is the relation
  rustdl's `oracle_diff::aligned_closures` counts, so the committed reference numbers are
  closure counts.
- **`owl:Thing`/`owl:Nothing`/reflexive: dropped**, in all three spellings that occur —
  absolute IRI, bare relative `Thing` (ROBOT), and `abbreviatedIRI="owl:Thing"`. Konclude
  emits `X ⊑ Thing`, HermiT does not; keeping them diffs output conventions, not logic.
- **Equivalence groups: expanded to mutual subsumption.** Load-bearing, not cosmetic —
  HermiT emits only ONE representative of a group in its edges (`E ⊑ C` with `D ≡ E`), so
  without expansion `D ⊑ C` is lost. `≡ owl:Nothing` and `≡ owl:Thing` groups are instead
  recorded as sidecar metadata and excluded.
- **KM's Tseitin definers: a whitelist, never a regex.** Every KM name is checked against
  the classes *declared in the source ontology* (hence `--ontology`), the same shape as
  rustdl's `reportable_class_iris`. A `^Q_\d+$` blacklist would be wrong in both
  directions, because **KM escapes legitimate source classes that look generated**: a real
  class `Q_1` is emitted as `km_src_Q_1` while KM's own definer is the unescaped `Q_0`
  (`engine/src/frontend/iri.rs::reserved_internal_prefix`). Measured on a probe declaring
  `:Q_1`, un-escaping recovers 2 of 3 subsumptions that the plain whitelist dropped.
  The whitelist doubles as the local-name→IRI map KM needs, since **KM reports bare local
  names, not IRIs**.

## Two bugs the count gate could not catch

Closure *size* is invariant under relabelling, so `gate` can pass while every IRI is
wrong. Both of these passed all 11 counts and were caught only by cross-reasoner identity
(`cross-check.sh`) — which is why that script exists alongside the gate:

1. **Unexpanded `abbreviatedIRI`.** wine's Konclude output carries 112 `food:*` abbreviated
   classes; leaving them raw corrupted 344 pair-halves at an unchanged count of 653, and
   showed up only as wine HermiT-vs-Konclude **FP=482**.
2. **Unresolved relative IRIs.** Konclude writes the ontology's own classes as fragment
   references (`<Class IRI="#AlsatianWine"/>`, 248 in wine). These must resolve against
   `ontologyIRI`/`xml:base` to match HermiT's and rustdl's absolute IRIs — and, because
   they start with `#`, they silently collided with this format's own comment sigil,
   costing 481 of wine's 653 pairs on the `compare` path while `gate` still read 653.
   `read_normalised` now hard-errors on a `#`-leading line that is not a known key.

## Not yet done

- The wrappers have now been cross-checked on the curated fixtures (see below), but no
  full-corpus cross-reasoner *sweep* has been run.
- KM is limited to small EL fixtures here: under its mandatory 20 GB cap it cannot
  classify pizza, so `cross-check.sh` runs it on bibtex only.
- ELK and whelk-rs are not provisioned; the 2026-07-11 curated MATRIX covered them.

## Gate status (2026-08-01)

`normalise.py gate` — normalised **Konclude** output vs rustdl's committed FP=0 closure
counts. **11/11 exact**, no fixture absent:

| galen | notgalen | sio | ore-10908 | wine | pizza | alehif | ro | ore-15672 | sulo | bibtex |
|---|---|---|---|---|---|---|---|---|---|---|
| 27997 | 32739 | 8904 | 6001 | 653 | 499 | 247 | 158 | 142 | 51 | 16 |

`cross-check.sh` — every reasoner vs the Konclude oracle, **FP=0 / MISSED=0 throughout**:

| fixture | oracle | rustdl | HermiT | KM |
|---|---|---|---|---|
| bibtex | 16 | 0/0 | 0/0 | 0/0 |
| pizza | 499 | 0/0 | 0/0 | capped |
| ro | 158 | 0/0 | 0/0 | capped |
| sulo | 51 | 0/0 | 0/0 | capped |
| wine | 653 | 0/0 | 0/0 | capped |

The gate is deliberately sensitive: mutating the closure step, the equivalence expansion,
or the Thing policy each break it (measured: pizza 499→171, 499→474, 499→596).

## Cross-reasoner agreement observed in the field (2026-08-01)

The 11-fixture `gate` checks the normaliser against rustdl's committed closures. A much
stronger check fell out of the DNF-257 triage: over the **122 ontologies Konclude and HermiT
BOTH classified**, normalised closure sizes agree **exactly on 121**. Two independent
reasoners, two unrelated output formats (OWL/XML vs functional syntax), 121 exact matches —
that is hard to achieve with a broken normaliser.

The single disagreement is worth keeping: **`ore_ont_9540` — Konclude 66 pairs, HermiT 71.**
Konclude UNDER-reports, the same direction as the previously recorded `ore_ont_10407` case
where rustdl matched HermiT and Konclude was the outlier. It is a live reminder that
**a single oracle is not an oracle**: FP adjudication is against **Konclude ∪ HermiT**, and
a rustdl "FP" that appears only against Konclude must be re-checked against HermiT before it
is called one.

### A predicate bug this section would NOT have caught

Agreement statistics only cover ontologies both reasoners classified. The verdict predicate
that decides *whether* a run counted as classified is a separate failure surface, and it
broke twice in one session — see `scripts/triage.py` and `tests/test_triage_predicate.py`.
The second break misreported **110 of 192** HermiT runs as front-end failures because the
predicate knew only OWL/XML and tab-separated text while HermiT writes functional syntax.
Both bugs yielded a plausible number rather than an error. Validate the predicate per format,
positive and negative, and sabotage the guard before believing it.
